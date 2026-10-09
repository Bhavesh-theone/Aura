import asyncio
import logging
from contextlib import suppress
from typing import Callable

from fastapi import WebSocket
from sqlalchemy import select

logger = logging.getLogger(__name__)


def wall_usernames(deal_id: int) -> set[str]:
    """Usernames currently on the deal's wall: the only people who may hear about it."""
    from aura.data.engine import SessionLocal
    from aura.data.models.tables import UserRow, WallMemberRow, WallRow
    from aura.data.walls import SYSTEM, bind_viewer
    with SessionLocal() as s:
        bind_viewer(s, SYSTEM)  # reads the wall itself, across every deal (RLS)
        return set(s.scalars(
            select(UserRow.username)
            .join(WallMemberRow, WallMemberRow.user_id == UserRow.id)
            .join(WallRow, WallRow.id == WallMemberRow.wall_id)
            .where(WallRow.deal_id == deal_id, WallMemberRow.removed_at.is_(None),
                   UserRow.active.is_(True))))


class EventHub:
    """In-process fan-out. Satisfies core.ports.events.EventPublisher.

    An event whose payload names a deal reaches only users on that deal's wall; an event
    about no deal reaches every connected user. If the wall cannot be looked up the event
    is dropped, never broadcast."""

    def __init__(self, members_for_deal: Callable[[int], set[str]] = wall_usernames) -> None:
        self._clients: dict[WebSocket, str] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._members_for_deal = members_for_deal

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, ws: WebSocket, username: str = "") -> None:
        await ws.accept()
        self._clients[ws] = username

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.pop(ws, None)

    def recipients(self, payload: dict) -> set[str] | None:
        """None means everyone; otherwise the usernames allowed to hear it."""
        deal_id = payload.get("deal_id")
        return None if deal_id is None else self._members_for_deal(deal_id)

    def publish(self, event_type: str, payload: dict) -> None:
        """Thread-safe: callable from the worker thread."""
        message = {"type": event_type, "payload": payload}
        if self._loop is None:
            return
        try:
            allowed = self.recipients(payload)
        except Exception:
            logger.exception("could not look up the wall for %s; event dropped", event_type)
            return
        with suppress(RuntimeError):
            asyncio.run_coroutine_threadsafe(self._broadcast(message, allowed), self._loop)

    async def _broadcast(self, message: dict, allowed: set[str] | None) -> None:
        for ws, username in list(self._clients.items()):
            if allowed is not None and username not in allowed:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)


hub = EventHub()