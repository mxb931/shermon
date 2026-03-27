import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal, engine, get_db
from .logging_setup import configure_logging, logging_ready
from .models import Base
from .realtime import manager
from .repository import (
    bootstrap,
    create_ack,
    expire_ack,
    get_maintenance_list,
    list_log_files,
    get_active_acks,
    get_component_statuses_for_store,
    get_active_incidents_for_entity,
    get_recent_events_for_entity,
    get_runtime_config,
    get_store_statuses,
    get_summary_counts,
    ingest_event,
    query_log_filter_values,
    query_logs,
    restore_component,
    restore_store,
    retire_component,
    retire_component_globally,
    retire_store,
    sweep_expired_acks,
    set_entity_disabled,
    sweep_timeout_statuses,
    update_runtime_config,
)
from .schemas import (
    AckIn,
    AckOut,
    BootstrapOut,
    ComponentStatusOut,
    EntityDisabledPatchIn,
    EventAck,
    EventIn,
    IncidentEventOut,
    LogFilterValuesOut,
    LogFileOut,
    LogQueryOut,
    MaintenanceListOut,
    RetiredComponentOut,
    RetiredStoreOut,
    RetireComponentGlobalIn,
    RetireComponentIn,
    RetireStoreIn,
    RuntimeConfigOut,
    RuntimeConfigUpdateIn,
    StoreStatusOut,
)


logger = logging.getLogger(__name__)


def _is_expired(dt: datetime) -> bool:
    if dt.tzinfo is not None:
        return dt.astimezone() <= datetime.now().astimezone()
    return dt <= datetime.utcnow()


def _client_ip_from_request(request: Request) -> str:
    forwarded_for = (request.headers.get("x-forwarded-for") or "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _configure_runtime_logging() -> None:
    db = SessionLocal()
    try:
        runtime_cfg = get_runtime_config(db)
        configure_logging(
            log_dir=settings.log_dir,
            file_name=settings.log_file_name,
            max_mb=runtime_cfg.log_max_mb,
            backup_count=runtime_cfg.log_backup_count,
        )
        logger.info(
            "Runtime logging configuration applied",
            extra={
                "message_type": "startup",
                "source": "server",
                "state": "logging_configured",
            },
        )
    except Exception:
        configure_logging(
            log_dir=settings.log_dir,
            file_name=settings.log_file_name,
            max_mb=settings.log_max_mb_default,
            backup_count=settings.log_backup_count_default,
        )
        logger.exception("Failed loading runtime logging config, using defaults")
    finally:
        db.close()


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


def _backfill_recovery_event_type_to_ok() -> None:
    inspector = inspect(engine)
    if "incident_events" not in inspector.get_table_names():
        return

    existing = {c["name"] for c in inspector.get_columns("incident_events")}
    if "event_type" not in existing:
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE incident_events
                SET event_type = 'ok'
                WHERE event_type = 'recovery'
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
    _ensure_column("acknowledgements", "expired_at", "expired_at DATETIME")
    _ensure_column("entity_status", "expected_green_interval_seconds", "expected_green_interval_seconds INTEGER")
    _ensure_column("entity_status", "stale_interval_seconds", "stale_interval_seconds INTEGER")
    _ensure_column("entity_status", "last_checkin_at", "last_checkin_at DATETIME")
    _ensure_column("entity_status", "disabled_at", "disabled_at DATETIME")
    _ensure_column("runtime_config", "log_max_mb", "log_max_mb INTEGER")
    _ensure_column("runtime_config", "log_backup_count", "log_backup_count INTEGER")
    _backfill_stale_interval_seconds()
    _backfill_recovery_event_type_to_ok()


async def _sweeper_loop() -> None:
    logger.info("Sweeper loop started", extra={"message_type": "startup", "source": "sweeper", "state": "running"})
    try:
        while True:
            interval_seconds = 60
            db = SessionLocal()
            try:
                interval_seconds = get_runtime_config(db).sweeper_interval_seconds
            except Exception:
                interval_seconds = 60
                logger.exception("Failed to load sweeper interval, using default")
            finally:
                db.close()

            await asyncio.sleep(interval_seconds)
            db = SessionLocal()
            try:
                timeout_payloads = sweep_timeout_statuses(db)
                ack_payloads = sweep_expired_acks(db)
                logger.info(
                    "Sweeper cycle completed",
                    extra={
                        "message_type": "sweeper_cycle",
                        "source": "sweeper",
                        "state": f"timeouts:{len(timeout_payloads)} acks:{len(ack_payloads)}",
                    },
                )
            finally:
                db.close()

            for payload in timeout_payloads + ack_payloads:
                await manager.broadcast(payload)
    except asyncio.CancelledError:
        logger.info(
            "Sweeper loop cancelled",
            extra={
                "message_type": "shutdown",
                "source": "sweeper",
                "state": "cancelled",
            },
        )
        raise


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not logging_ready():
        logger.info(
            "Applying initial logging configuration",
            extra={
                "message_type": "startup",
                "source": "server",
                "state": "logging_bootstrap",
            },
        )
        configure_logging(
            log_dir=settings.log_dir,
            file_name=settings.log_file_name,
            max_mb=settings.log_max_mb_default,
            backup_count=settings.log_backup_count_default,
        )
    logger.info("Server startup initiated", extra={"message_type": "startup", "source": "server", "state": "begin"})
    logger.info("Schema compatibility check started", extra={"message_type": "startup", "source": "server", "state": "schema_check"})
    ensure_schema_compat()
    _configure_runtime_logging()
    logger.info("Schema compatibility check complete", extra={"message_type": "startup", "source": "server", "state": "schema_ready"})
    logger.info("Starting sweeper task", extra={"message_type": "startup", "source": "server", "state": "starting_sweeper"})
    sweeper = asyncio.create_task(_sweeper_loop())
    logger.info("Sweeper task started", extra={"message_type": "startup", "source": "server", "state": "ready"})
    try:
        yield
    finally:
        logger.info("Server shutdown initiated", extra={"message_type": "shutdown", "source": "server", "state": "begin"})
        logger.info("Cancelling sweeper task", extra={"message_type": "shutdown", "source": "server", "state": "stopping_sweeper"})
        sweeper.cancel()
        try:
            await sweeper
        except asyncio.CancelledError:
            logger.info(
                "Sweeper task cancellation confirmed",
                extra={
                    "message_type": "shutdown",
                    "source": "server",
                    "state": "sweeper_stopped",
                },
            )
        logger.info("Server shutdown complete", extra={"message_type": "shutdown", "source": "server", "state": "complete"})


app = FastAPI(title="SherMon API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = str(uuid4())
    client_ip = _client_ip_from_request(request)
    request.state.request_id = request_id
    request.state.client_ip = client_ip
    start = datetime.utcnow()
    logger.info(
        f"Incoming request method={request.method} path={request.url.path}",
        extra={
            "request_id": request_id,
            "client_ip": client_ip,
            "message_type": "http_request",
            "source": "http",
        },
    )

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
        logger.exception(
            f"Unhandled request error method={request.method} path={request.url.path} duration_ms={duration_ms}",
            extra={
                "request_id": request_id,
                "client_ip": client_ip,
                "message_type": "http_request",
                "source": "http",
                "state": "exception",
            },
        )
        raise

    duration_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
    log_fn = logger.warning if response.status_code >= 400 else logger.info
    log_fn(
        f"Completed request method={request.method} path={request.url.path} status={response.status_code} duration_ms={duration_ms}",
        extra={
            "request_id": request_id,
            "client_ip": client_ip,
            "message_type": "http_request",
            "source": "http",
            "state": str(response.status_code),
        },
    )
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(
        f"Validation failed path={request.url.path}",
        extra={
            "request_id": getattr(request.state, "request_id", "-"),
            "client_ip": getattr(request.state, "client_ip", _client_ip_from_request(request)),
            "message_type": "validation_error",
            "source": "http",
            "state": "422",
        },
    )
    return JSONResponse(status_code=422, content=jsonable_encoder({"detail": exc.errors()}))


def require_ingest_key(request: Request, x_monitor_key: str = Header(default="")) -> None:
    if x_monitor_key != settings.api_key:
        logger.warning(
            "Invalid API key",
            extra={
                "client_ip": _client_ip_from_request(request),
                "request_id": getattr(request.state, "request_id", "-"),
                "message_type": "auth_failure",
                "source": "auth",
                "state": "401",
            },
        )
        raise HTTPException(status_code=401, detail="invalid monitor API key")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/events", response_model=EventAck)
async def post_event(
    request: Request,
    event: EventIn,
    _: None = Depends(require_ingest_key),
    db: Session = Depends(get_db),
) -> EventAck:
    client_ip = _client_ip_from_request(request)
    logger.info(
        "Client event received",
        extra={
            "client_ip": client_ip,
            "request_id": getattr(request.state, "request_id", "-"),
            "message_type": "client_event",
            "source": event.source,
            "event_id": event.event_id,
        },
    )
    accepted, deduplicated, sequence, payload = ingest_event(db, event)
    if payload:
        await manager.broadcast(payload)
    return EventAck(accepted=accepted, deduplicated=deduplicated, sequence=sequence)


@app.get("/api/v1/acks", response_model=list[AckOut])
def get_acks(db: Session = Depends(get_db)) -> list[AckOut]:
    return get_active_acks(db)


@app.post("/api/v1/acks", response_model=AckOut)
async def post_ack(
    request: Request,
    ack: AckIn,
    _: None = Depends(require_ingest_key),
    db: Session = Depends(get_db),
) -> AckOut:
    if _is_expired(ack.expires_at):
        raise HTTPException(status_code=422, detail="expires_at must be in the future")

    ack_out, payload = create_ack(db, ack)
    if ack_out is None:
        if payload.get("error") == "not_ackable":
            raise HTTPException(status_code=422, detail="only problem alerts can be acknowledged")
        raise HTTPException(status_code=404, detail="event_id not found")
    await manager.broadcast(payload)
    logger.info(
        "Ack accepted",
        extra={
            "client_ip": _client_ip_from_request(request),
            "request_id": getattr(request.state, "request_id", "-"),
            "message_type": "ack_update",
            "source": "ack",
            "event_id": ack.event_id,
            "state": "active",
        },
    )
    return ack_out


@app.delete("/api/v1/acks/{event_id}")
async def delete_ack(
    request: Request,
    event_id: str,
    _: None = Depends(require_ingest_key),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    payload = expire_ack(db, event_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="acknowledgement not found")
    await manager.broadcast(payload)
    logger.info(
        "Ack manually expired",
        extra={
            "client_ip": _client_ip_from_request(request),
            "request_id": getattr(request.state, "request_id", "-"),
            "message_type": "ack_expired",
            "source": "ack",
            "event_id": event_id,
            "state": "expired",
        },
    )
    return {"expired": True}


@app.get("/api/v1/bootstrap", response_model=BootstrapOut)
def get_bootstrap(db: Session = Depends(get_db)) -> BootstrapOut:
    return bootstrap(db, settings.recent_event_limit)


@app.get("/api/v1/config", response_model=RuntimeConfigOut)
def get_config(db: Session = Depends(get_db)) -> RuntimeConfigOut:
    return get_runtime_config(db)


@app.put("/api/v1/config", response_model=RuntimeConfigOut)
def put_config(
    request: Request,
    payload: RuntimeConfigUpdateIn,
    _: None = Depends(require_ingest_key),
    db: Session = Depends(get_db),
) -> RuntimeConfigOut:
    updated = update_runtime_config(db, payload)
    _configure_runtime_logging()
    logger.info(
        "Runtime config updated via API",
        extra={
            "client_ip": _client_ip_from_request(request),
            "request_id": getattr(request.state, "request_id", "-"),
            "message_type": "runtime_config_update",
            "source": "config",
            "state": "applied",
        },
    )
    return updated


@app.get("/api/v1/log-files", response_model=list[LogFileOut])
def get_log_files() -> list[LogFileOut]:
    files = list_log_files(settings.log_dir, settings.log_file_name)
    return [LogFileOut(**item) for item in files]


@app.get("/api/v1/logs", response_model=LogQueryOut)
def get_logs(
    file_name: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    severity: Optional[str] = None,
    message_type: Optional[str] = None,
    source: Optional[str] = None,
    state: Optional[str] = None,
    event_id: Optional[str] = None,
    client_ip: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> LogQueryOut:
    payload = query_logs(
        log_dir=settings.log_dir,
        active_file_name=settings.log_file_name,
        file_name=file_name,
        since=since,
        until=until,
        severity=severity,
        message_type=message_type,
        source=source,
        state=state,
        event_id=event_id,
        client_ip=client_ip,
        q=q,
        limit=limit,
        offset=offset,
    )
    return LogQueryOut(**payload)


@app.get("/api/v1/logs/filter-values", response_model=LogFilterValuesOut)
def get_log_filter_values(values_limit: int = Query(default=500, ge=1, le=5000)) -> LogFilterValuesOut:
    payload = query_log_filter_values(
        log_dir=settings.log_dir,
        active_file_name=settings.log_file_name,
        values_limit=values_limit,
    )
    return LogFilterValuesOut(**payload)


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


@app.get("/api/v1/entity-events", response_model=list[IncidentEventOut])
def get_recent_events_by_entity(
    store_id: str,
    component: str,
    hours: int = 24,
    limit: int = 1000,
    db: Session = Depends(get_db),
) -> list[IncidentEventOut]:
    return get_recent_events_for_entity(db, store_id, component, hours, limit)


@app.get("/api/v1/maintenance/retired", response_model=MaintenanceListOut)
def get_retired_entities(db: Session = Depends(get_db)) -> MaintenanceListOut:
    return get_maintenance_list(db)


@app.post("/api/v1/maintenance/retire-store", response_model=RetiredStoreOut)
def post_retire_store(
    request: Request,
    body: RetireStoreIn,
    _: None = Depends(require_ingest_key),
    db: Session = Depends(get_db),
) -> RetiredStoreOut:
    result = retire_store(db, body.store_id)
    logger.info(
        "Store retired",
        extra={
            "client_ip": _client_ip_from_request(request),
            "request_id": getattr(request.state, "request_id", "-"),
            "message_type": "maintenance",
            "source": body.store_id,
            "state": "retired_store",
        },
    )
    return result


@app.post("/api/v1/maintenance/retire-component", response_model=RetiredComponentOut)
def post_retire_component(
    request: Request,
    body: RetireComponentIn,
    _: None = Depends(require_ingest_key),
    db: Session = Depends(get_db),
) -> RetiredComponentOut:
    result = retire_component(db, body.store_id, body.component)
    logger.info(
        "Component retired",
        extra={
            "client_ip": _client_ip_from_request(request),
            "request_id": getattr(request.state, "request_id", "-"),
            "message_type": "maintenance",
            "source": f"{body.store_id}/{body.component}",
            "state": "retired_component",
        },
    )
    return result


@app.post("/api/v1/maintenance/retire-component-global", response_model=list[RetiredComponentOut])
def post_retire_component_global(
    request: Request,
    body: RetireComponentGlobalIn,
    _: None = Depends(require_ingest_key),
    db: Session = Depends(get_db),
) -> list[RetiredComponentOut]:
    results = retire_component_globally(db, body.component)
    logger.info(
        "Component retired globally",
        extra={
            "client_ip": _client_ip_from_request(request),
            "request_id": getattr(request.state, "request_id", "-"),
            "message_type": "maintenance",
            "source": body.component,
            "state": "retired_component_global",
        },
    )
    return results


@app.post("/api/v1/maintenance/restore-store", response_model=dict)
def post_restore_store(
    request: Request,
    body: RetireStoreIn,
    _: None = Depends(require_ingest_key),
    db: Session = Depends(get_db),
) -> dict:
    found = restore_store(db, body.store_id)
    if not found:
        raise HTTPException(status_code=404, detail="store not found in retired list")
    logger.info(
        "Store restored",
        extra={
            "client_ip": _client_ip_from_request(request),
            "request_id": getattr(request.state, "request_id", "-"),
            "message_type": "maintenance",
            "source": body.store_id,
            "state": "restored_store",
        },
    )
    return {"restored": True}


@app.post("/api/v1/maintenance/restore-component", response_model=dict)
def post_restore_component(
    request: Request,
    body: RetireComponentIn,
    _: None = Depends(require_ingest_key),
    db: Session = Depends(get_db),
) -> dict:
    found = restore_component(db, body.store_id, body.component)
    if not found:
        raise HTTPException(status_code=404, detail="component not found in retired list")
    logger.info(
        "Component restored",
        extra={
            "client_ip": _client_ip_from_request(request),
            "request_id": getattr(request.state, "request_id", "-"),
            "message_type": "maintenance",
            "source": f"{body.store_id}/{body.component}",
            "state": "restored_component",
        },
    )
    return {"restored": True}


@app.patch("/api/v1/entity-status/disabled")
async def patch_entity_disabled(
    request: Request,
    body: EntityDisabledPatchIn,
    _: None = Depends(require_ingest_key),
    db: Session = Depends(get_db),
) -> dict:
    status_dict = set_entity_disabled(db, body.store_id, body.component, body.disabled)
    await manager.broadcast({"kind": "status_timeout", "status": status_dict})
    logger.info(
        "Entity disabled state changed",
        extra={
            "client_ip": _client_ip_from_request(request),
            "request_id": getattr(request.state, "request_id", "-"),
            "message_type": "maintenance",
            "source": f"{body.store_id}/{body.component}",
            "state": "disabled" if body.disabled else "enabled",
        },
    )
    return status_dict


@app.websocket("/ws/updates")
async def ws_updates(websocket: WebSocket):
    client_ip = websocket.client.host if websocket.client else "unknown"
    await manager.connect(websocket)
    logger.info(
        "WebSocket connected",
        extra={
            "client_ip": client_ip,
            "message_type": "websocket",
            "source": "ws",
            "state": "connected",
        },
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
        logger.info(
            "WebSocket disconnected",
            extra={
                "client_ip": client_ip,
                "message_type": "websocket",
                "source": "ws",
                "state": "disconnected",
            },
        )
    except Exception:
        logger.exception(
            "WebSocket error",
            extra={
                "client_ip": client_ip,
                "message_type": "websocket",
                "source": "ws",
                "state": "error",
            },
        )
        await manager.disconnect(websocket)
