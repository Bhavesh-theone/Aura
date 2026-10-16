"""Machinery for the demo dataset (see aura.data.demo).

Every write goes through the real core services, acting as a named user with wall-scoped
repositories, one unit of work per event. The only thing the builder controls is the clock:
a ReplayClock is put in effect (aura.core.clock.use_clock) and moved to each event's time,
so stage history, guard evaluations, audit entries and handoffs carry a realistic past
timeline. Events of all deals run in one global chronological order.
"""
from __future__ import annotations

import zlib

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable

from sqlalchemy.orm import Session

from aura.core.domain.errors import GuardBlocked
from aura.data.filestore import LocalFileStore
from aura.data.repositories.sql import (SqlAuditRepository, SqlHandoffRepository,
                                        SqlJobRepository, SqlSegmentRepository,
                                        SqlTaskRepository, SqlUserRepository)
from aura.data.repositories.sql_deals import (SqlConditionRepository, SqlDealRepository,
                                              SqlDiligenceRepository, SqlDocumentRepository,
                                              SqlExtractionRepository, SqlFindingRepository,
                                              SqlGuardRepository, SqlMandateRepository,
                                              SqlPartyRepository, SqlSignoffRepository,
                                              SqlStageHistoryRepository, SqlWallRepository)
from aura.data.uow import SqlUnitOfWork

IST = timezone(timedelta(hours=5, minutes=30))


class ReplayClock:
    """Returns the time of the event being replayed. Each read moves it on by one second,
    so the writes inside one event keep their order; setting it never moves it back."""

    def __init__(self, start: datetime):
        self._t = start

    def set(self, when: datetime) -> None:
        if when > self._t:
            self._t = when

    def now(self) -> datetime:
        current = self._t
        self._t = current + timedelta(seconds=1)
        return current


def business_days(count: int, today: date) -> list[date]:
    """The `count` most recent weekdays strictly before `today`, oldest first."""
    days: list[date] = []
    d = today - timedelta(days=1)
    while len(days) < count:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))


class NullEvents:
    """No live UI is listening while the dataset is built."""

    def publish(self, event_type: str, payload: dict) -> None:
        pass


@dataclass
class Repos:
    """Every repository, scoped to one viewer (a username, or SYSTEM)."""
    s: Session
    viewer: object

    def __post_init__(self) -> None:
        s, v = self.s, self.viewer
        self.deals = SqlDealRepository(s, v)
        self.history = SqlStageHistoryRepository(s, v)
        self.guards = SqlGuardRepository(s)
        self.parties = SqlPartyRepository(s, v)
        self.mandates = SqlMandateRepository(s, v)
        self.documents = SqlDocumentRepository(s, v)
        self.diligence = SqlDiligenceRepository(s, v)
        self.conditions = SqlConditionRepository(s, v)
        self.findings = SqlFindingRepository(s, v)
        self.signoffs = SqlSignoffRepository(s, v)
        self.extractions = SqlExtractionRepository(s, v)
        self.walls = SqlWallRepository(s, v)
        self.users = SqlUserRepository(s)
        self.jobs = SqlJobRepository(s, v)
        self.segments = SqlSegmentRepository(s)
        self.tasks = SqlTaskRepository(s, v)
        self.handoffs = SqlHandoffRepository(s, v)
        self.audit = SqlAuditRepository(s, v)


@dataclass(order=True)
class Event:
    when: datetime
    seq: int
    label: str = field(compare=False)
    run: Callable[[], None] = field(compare=False)
    expect_block: bool = field(default=False, compare=False)


class Desk:
    """Runs scheduled events against one database session."""

    def __init__(self, session: Session, clock: ReplayClock, store: LocalFileStore,
                 orchestrator, live_orchestrator=None, log: Callable[[str], None] = print):
        self.s, self.clock, self.store = session, clock, store
        self.orchestrator, self.live_orchestrator = orchestrator, live_orchestrator
        self.log = log
        self.events: list[Event] = []
        self._seq = 0

    def repos(self, viewer) -> Repos:
        return Repos(self.s, viewer)

    def schedule(self, when: datetime, label: str, run: Callable[[], None],
                 expect_block: bool = False) -> None:
        self._seq += 1
        # People do not act on the minute: a fixed, label-derived offset of up to 3m59s.
        jitter = zlib.crc32(label.encode("utf-8"))
        when = when + timedelta(minutes=(jitter >> 8) % 4, seconds=jitter % 60)
        self.events.append(Event(when, self._seq, label, run, expect_block))

    def run_all(self) -> int:
        """Run every event in time order, each in its own transaction. A blocked stage move
        is expected in the stories: its evaluation rows and audit entry are kept."""
        done = 0
        for ev in sorted(self.events):
            self.clock.set(ev.when)
            uow = SqlUnitOfWork(self.s)
            try:
                with uow.transaction():
                    ev.run()
            except GuardBlocked as exc:
                if not ev.expect_block:
                    raise RuntimeError(f"{ev.label}: unexpectedly blocked ({exc})") from exc
                self.log(f"  {ev.when:%Y-%m-%d %H:%M} {ev.label}: blocked as planned ({exc})")
            done += 1
        return done


def at(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(h, m), IST).astimezone(timezone.utc)
