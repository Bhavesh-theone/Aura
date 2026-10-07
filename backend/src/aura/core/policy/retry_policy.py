"""What the worker does when a segment fails, and how long it waits before trying again.

Transient failures (the model or the network is temporarily unavailable) are retried with
exponential backoff until max_attempts, then dead-lettered. Everything else is permanent and
fails at once: retrying a validation error, a lineage failure or a used-up budget would give
the same answer and spend the same budget again.

Core may not import the model or HTTP libraries, so their errors are recognised by class
name (anywhere in the exception's cause chain) as well as by the built-in types.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from aura.core.domain.errors import DomainError
from aura.core.ports.orchestrator import (AgentRunLogError, BudgetExceeded,
                                          TransientModelError)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_BACKOFF_SECONDS = 10.0
DEFAULT_LEASE_SECONDS = 900

# litellm, httpx, openai and requests errors that mean "try again later".
_TRANSIENT_NAMES = frozenset({
    "APIConnectionError", "ServiceUnavailableError", "InternalServerError", "RateLimitError",
    "Timeout", "APITimeoutError", "ConnectError", "ConnectTimeout", "ReadTimeout",
    "WriteTimeout", "PoolTimeout", "ReadError", "RemoteProtocolError", "NetworkError",
    "TimeoutException", "ConnectionError",
})
_TRANSIENT_TEXT = ("connection refused", "connecterror", "timed out", "timeout",
                   "temporarily unavailable", "service unavailable", "connection reset",
                   "failed to establish a new connection", "max retries exceeded",
                   "actively refused", "urlopen error")
_PERMANENT = (AgentRunLogError, BudgetExceeded, DomainError, ValueError, TypeError, KeyError)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_backoff_seconds: float = DEFAULT_BASE_BACKOFF_SECONDS
    lease_seconds: int = DEFAULT_LEASE_SECONDS

    def backoff(self, attempts: int) -> timedelta:
        """Wait before attempt `attempts + 1`: base, 2x base, 4x base, ..."""
        return timedelta(seconds=self.base_backoff_seconds * 2 ** max(0, attempts - 1))

    def next_run_at(self, now: datetime, attempts: int) -> datetime:
        return now + self.backoff(attempts)

    def can_retry(self, attempts: int) -> bool:
        return attempts < self.max_attempts


def _chain(exc: BaseException):
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def is_transient(exc: BaseException) -> bool:
    """True when the failure is worth retrying. A permanent error anywhere at the top wins."""
    if isinstance(exc, _PERMANENT):
        return False
    for link in _chain(exc):
        if isinstance(link, (TransientModelError, ConnectionError, TimeoutError)):
            return True
        if any(cls.__name__ in _TRANSIENT_NAMES for cls in type(link).__mro__):
            return True
        text = str(link).lower()
        if any(marker in text for marker in _TRANSIENT_TEXT):
            return True
    return False


def error_text(exc: BaseException, limit: int = 2000) -> str:
    return f"{type(exc).__name__}: {exc}"[:limit]
