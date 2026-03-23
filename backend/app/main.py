import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal, engine, get_db
from .models import Base
from .realtime import manager
from .repository import (
    bootstrap,
    create_ack,
    expire_ack,
    get_active_acks,
    get_component_statuses_for_store,
    get_active_incidents_for_entity,
    get_store_statuses,
    get_summary_counts,
    ingest_event,
    sweep_expired_acks,
    sweep_timeout_statuses,
)
from .schemas import AckIn, AckOut, BootstrapOut, ComponentStatusOut, EventAck, EventIn, IncidentEventOut, StoreStatusOut


def _is_expired(dt: datetime) -> bool:
    if dt.tzinfo is not None:
        return dt.astimezone() <= datetime.now().astimezone()
    return dt <= datetime.utcnow()


def _ensure_column(table: str, column: str, ddl: str) -> None:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns(table)}
    if column in existing:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def _backfill_stale_interval_seconds() -> None:
    inspector = inspect(engine)
    if "entity_status" not in inspector.get_table_names():
        return

    existing = {c["name"] for c in inspector.get_columns("entity_status")}
    if "stale_interval_seconds" not in existing or "expected_green_interval_seconds" not in existing:
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE entity_status
                SET stale_interval_seconds = expected_green_interval_seconds
                WHERE stale_interval_seconds IS NULL
                  AND expected_green_interval_seconds IS NOT NULL
                """
            )
        )


def _drop_incident_category_if_present() -> None:
    inspector = inspect(engine)
    if "incident_events" not in inspector.get_table_names():
        return

    existing = {c["name"] for c in inspector.get_columns("incident_events")}
    if "category" not in existing:
        return

    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE incident_events DROP COLUMN category"))
            return
        except Exception:
            # Fallback for SQLite builds that do not support DROP COLUMN.
            conn.execute(
                text(
                    """
                    CREATE TABLE incident_events_new (
                        id INTEGER PRIMARY KEY,
                        event_id VARCHAR(64) NOT NULL UNIQUE,
                        dedup_key VARCHAR(128) NOT NULL,
                        store_id VARCHAR(64) NOT NULL,
                        component VARCHAR(128) NOT NULL,
                        event_type VARCHAR(16) NOT NULL,
                        severity VARCHAR(16) NOT NULL,
                        message TEXT NOT NULL,
                        source VARCHAR(128) NOT NULL,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        happened_at DATETIME NOT NULL,
                        expires_at DATETIME,
                        created_at DATETIME NOT NULL,
                        active BOOLEAN NOT NULL DEFAULT 1
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO incident_events_new (
                        id,
                        event_id,
                        dedup_key,
                        store_id,
                        component,
                        event_type,
                        severity,
                        message,
                        source,
                        metadata_json,
                        happened_at,
                        expires_at,
                        created_at,
                        active
                    )
                    SELECT
                        id,
                        event_id,
                        dedup_key,
                        store_id,
                        component,
                        event_type,
                        severity,
                        message,
                        source,
                        metadata_json,
                        happened_at,
                        expires_at,
                        created_at,
                        active
                    FROM incident_events
                    """
                )
            )
            conn.execute(text("DROP TABLE incident_events"))
            conn.execute(text("ALTER TABLE incident_events_new RENAME TO incident_events"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_incident_events_event_id ON incident_events (event_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_incident_events_dedup_key ON incident_events (dedup_key)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_incident_events_store_id ON incident_events (store_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_incident_events_component ON incident_events (component)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_incident_events_event_type ON incident_events (event_type)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_incident_events_severity ON incident_events (severity)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_incident_events_source ON incident_events (source)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_incident_events_happened_at ON incident_events (happened_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_incident_events_expires_at ON incident_events (expires_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_incident_events_created_at ON incident_events (created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_incident_events_active ON incident_events (active)"))


def ensure_schema_compat() -> None:
    Base.metadata.create_all(bind=engine)
    _drop_incident_category_if_present()
    _ensure_column("incident_events", "expires_at", "expires_at DATETIME")
    _ensure_column("entity_status", "expected_green_interval_seconds", "expected_green_interval_seconds INTEGER")
    _ensure_column("entity_status", "stale_interval_seconds", "stale_interval_seconds INTEGER")
    _ensure_column("entity_status", "last_checkin_at", "last_checkin_at DATETIME")
    _ensure_column("entity_status", "disabled_at", "disabled_at DATETIME")
    _backfill_stale_interval_seconds()


async def _sweeper_loop() -> None:
    while True:
        await asyncio.sleep(60)
        db = SessionLocal()
        try:
            timeout_payloads = sweep_timeout_statuses(db)
            ack_payloads = sweep_expired_acks(db)
        finally:
            db.close()

        for payload in timeout_payloads + ack_payloads:
            await manager.broadcast(payload)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_schema_compat()
    sweeper = asyncio.create_task(_sweeper_loop())
    try:
        yield
    finally:
        sweeper.cancel()
        try:
            await sweeper
        except asyncio.CancelledError:
            pass


app = FastAPI(title="SherMon API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_ingest_key(x_monitor_key: str = Header(default="")) -> None:
    if x_monitor_key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid monitor API key")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/events", response_model=EventAck)
async def post_event(
    event: EventIn,
    _: None = Depends(require_ingest_key),
    db: Session = Depends(get_db),
) -> EventAck:
    accepted, deduplicated, sequence, payload = ingest_event(db, event)
    if payload:
        await manager.broadcast(payload)
    return EventAck(accepted=accepted, deduplicated=deduplicated, sequence=sequence)


@app.get("/api/v1/acks", response_model=list[AckOut])
def get_acks(db: Session = Depends(get_db)) -> list[AckOut]:
    return get_active_acks(db)


@app.post("/api/v1/acks", response_model=AckOut)
async def post_ack(
    ack: AckIn,
    _: None = Depends(require_ingest_key),
    db: Session = Depends(get_db),
) -> AckOut:
    if _is_expired(ack.expires_at):
        raise HTTPException(status_code=422, detail="expires_at must be in the future")

    ack_out, payload = create_ack(db, ack)
    if ack_out is None:
        raise HTTPException(status_code=404, detail="event_id not found")
    await manager.broadcast(payload)
    return ack_out


@app.delete("/api/v1/acks/{event_id}")
async def delete_ack(
    event_id: str,
    _: None = Depends(require_ingest_key),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    payload = expire_ack(db, event_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="acknowledgement not found")
    await manager.broadcast(payload)
    return {"expired": True}


@app.get("/api/v1/bootstrap", response_model=BootstrapOut)
def get_bootstrap(db: Session = Depends(get_db)) -> BootstrapOut:
    return bootstrap(db, settings.recent_event_limit)


@app.get("/api/v1/summary")
def get_summary(db: Session = Depends(get_db)) -> dict:
    return {
        "counts": get_summary_counts(db),
    }


@app.get("/api/v1/status/stores", response_model=list[StoreStatusOut])
def get_store_hierarchy_status(db: Session = Depends(get_db)) -> list[StoreStatusOut]:
    return get_store_statuses(db)


@app.get("/api/v1/status/stores/{store_id}/components", response_model=list[ComponentStatusOut])
def get_component_hierarchy_status(store_id: str, db: Session = Depends(get_db)) -> list[ComponentStatusOut]:
    return get_component_statuses_for_store(db, store_id)


@app.get("/api/v1/active-alerts", response_model=list[IncidentEventOut])
def get_active_alerts_for_entity(
    store_id: str,
    component: str,
    db: Session = Depends(get_db),
) -> list[IncidentEventOut]:
    return get_active_incidents_for_entity(db, store_id, component)


@app.websocket("/ws/updates")
async def ws_updates(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)
