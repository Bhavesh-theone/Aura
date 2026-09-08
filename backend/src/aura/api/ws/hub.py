import asyncio
from contextlib import suppress

from fastapi import WebSocket


class EventHub:
    """In-process fan-out. Satisfies core.ports.events.EventPublisher."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    def publish(self, event_type: str, payload: dict) -> None:
        """Thread-safe: callable from the worker thread."""
        message = {"type": event_type, "payload": payload}
        if self._loop is None:
            return
        with suppress(RuntimeError):
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)

    async def _broadcast(self, message: dict) -> None:
        for ws in list(self._clients):
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)


hub = EventHub()
