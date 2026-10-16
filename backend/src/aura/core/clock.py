"""The clock seam. Services stamp records with utcnow(), which reads the Clock in effect.

The default is the system clock, so normal runtime behaviour is unchanged. A caller that
needs another notion of time (the demo builder replaying a past timeline, tests) swaps the
clock for the current context only with `use_clock`; other threads (the API, the worker)
keep the system clock.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Iterator

from aura.core.ports.clock import Clock


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


SYSTEM_CLOCK = SystemClock()
_current: ContextVar[Clock] = ContextVar("aura_clock", default=SYSTEM_CLOCK)


def utcnow() -> datetime:
    return _current.get().now()


@contextmanager
def use_clock(clock: Clock) -> Iterator[Clock]:
    token = _current.set(clock)
    try:
        yield clock
    finally:
        _current.reset(token)
