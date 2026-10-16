"""The clock seam: services stamp records from aura.core.clock, which is the system clock
unless a caller swaps it for the current context only."""
import threading
from datetime import datetime, timedelta, timezone

from aura.core.clock import SYSTEM_CLOCK, use_clock, utcnow
from aura.core.domain.enums import Role, TransactionClass
from aura.core.ports.clock import Clock
from aura.core.services.create_deal import create_deal
from tests.unit.fakes import FakeAuditRepo, FakeDealRepo, FakeHistoryRepo, FakeWallRepo

PAST = datetime(2026, 4, 13, 4, 30, tzinfo=timezone.utc)


class FixedClock:
    def __init__(self, when: datetime):
        self.when = when

    def now(self) -> datetime:
        return self.when


def test_default_is_the_system_clock():
    before = datetime.now(timezone.utc)
    now = utcnow()
    assert before <= now <= datetime.now(timezone.utc)
    assert now.tzinfo is not None
    assert isinstance(SYSTEM_CLOCK, Clock)


def test_use_clock_applies_inside_the_block_only():
    with use_clock(FixedClock(PAST)):
        assert utcnow() == PAST
    assert utcnow() - datetime.now(timezone.utc) < timedelta(seconds=5)


def test_other_threads_keep_the_system_clock():
    seen = []
    with use_clock(FixedClock(PAST)):
        t = threading.Thread(target=lambda: seen.append(utcnow()))
        t.start()
        t.join()
    assert seen[0] != PAST


def test_services_stamp_with_the_clock_in_effect():
    deals, history, audit = FakeDealRepo(), FakeHistoryRepo(), FakeAuditRepo()
    with use_clock(FixedClock(PAST)):
        deal = create_deal("X-1", "Clocked", TransactionClass.DEBT, "bhavesh", Role.DEALMAKER,
                           deals, history, audit, FakeWallRepo())
    assert deal.opened_at == PAST
    assert history.entries[0].entered_at == PAST
    assert audit.entries[0].created_at == PAST
