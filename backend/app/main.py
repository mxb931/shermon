from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .config import settings
from .database import engine, get_db
from .models import Base
from .realtime import manager
from .repository import bootstrap, get_summary_counts, ingest_event
from .schemas import BootstrapOut, EventAck, EventIn


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Xstore Monitor API", version="0.1.0")

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


@app.get("/api/v1/bootstrap", response_model=BootstrapOut)
def get_bootstrap(db: Session = Depends(get_db)) -> BootstrapOut:
    return bootstrap(db, settings.recent_event_limit)


@app.get("/api/v1/summary")
def get_summary(db: Session = Depends(get_db)) -> dict:
    return {
        "counts": get_summary_counts(db),
    }


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
