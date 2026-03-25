import asyncio
import logging
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
            logging.getLogger(__name__).info(
                "WebSocket client registered",
                extra={
                    "message_type": "websocket",
                    "source": "realtime",
                    "state": f"connections:{len(self._connections)}",
                    "client_ip": websocket.client.host if websocket.client else "unknown",
                },
            )

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            self._connections.discard(websocket)
            logging.getLogger(__name__).info(
                "WebSocket client removed",
                extra={
                    "message_type": "websocket",
                    "source": "realtime",
                    "state": f"connections:{len(self._connections)}",
                    "client_ip": websocket.client.host if websocket.client else "unknown",
                },
            )

    async def broadcast(self, payload: dict[str, Any]):
        async with self._lock:
            sockets = list(self._connections)

        logging.getLogger(__name__).info(
            "Broadcasting websocket payload",
            extra={
                "message_type": payload.get("kind", "broadcast"),
                "source": "realtime",
                "state": f"targets:{len(sockets)}",
                "event_id": payload.get("event", {}).get("event_id", payload.get("event_id", "-")),
            },
        )

        for ws in sockets:
            try:
                await ws.send_json(payload)
            except Exception:
                logging.getLogger(__name__).warning(
                    "Broadcast send failed; disconnecting websocket",
                    extra={
                        "message_type": payload.get("kind", "broadcast"),
                        "source": "realtime",
                        "state": "send_failed",
                        "client_ip": ws.client.host if ws.client else "unknown",
                    },
                )
                await self.disconnect(ws)


manager = ConnectionManager()
