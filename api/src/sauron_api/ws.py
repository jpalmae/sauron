from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .auth import ws_auth
from .db import get_session_factory

log = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks /ws/alerts clients and broadcasts live alert payloads."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        dead: list[WebSocket] = []
        for ws in self._clients:
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 - any send failure means a dead client
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)


manager = ConnectionManager()
router = APIRouter()


@router.websocket("/ws/alerts")
async def alerts_ws(ws: WebSocket) -> None:
    async with get_session_factory()() as session:
        await ws_auth(ws, session)  # raises WebSocketException(4401) on auth failure
    await manager.connect(ws)
    log.info("ws client connected (%d total)", manager.client_count)
    try:
        while True:
            await ws.receive_text()  # keepalive / client pings
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)
