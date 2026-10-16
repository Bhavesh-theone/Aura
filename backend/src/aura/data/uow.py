"""Unit of work over one SQLAlchemy session.

Repositories flush but never commit. Whoever owns the boundary (the API dependency, the
worker) calls commit() once the whole service call has succeeded, so a failure midway leaves
no partial writes.
"""
from contextlib import contextmanager

from sqlalchemy.orm import Session

from aura.core.ports.events import EventPublisher


class DeferredEvents:
    """Holds events until the transaction that produced them has committed."""

    def __init__(self, inner: EventPublisher):
        self._inner = inner
        self.pending: list[tuple[str, dict]] = []

    def publish(self, event_type: str, payload: dict) -> None:
        self.pending.append((event_type, payload))

    def flush(self) -> None:
        pending, self.pending = self.pending, []
        for event_type, payload in pending:
            self._inner.publish(event_type, payload)


class SqlUnitOfWork:
    def __init__(self, session: Session):
        self.session = session
        self._deferred: list[DeferredEvents] = []

    def defer(self, inner: EventPublisher) -> DeferredEvents:
        deferred = DeferredEvents(inner)
        self._deferred.append(deferred)
        return deferred

    def commit(self) -> None:
        self.session.commit()
        for deferred in self._deferred:
            deferred.flush()
        from aura.data.spans import flush_spans
        flush_spans(self.session)  # finished spans, in their own small transaction

    def rollback(self) -> None:
        self.session.rollback()
        for deferred in self._deferred:
            deferred.pending.clear()

    @contextmanager
    def transaction(self):
        """Commit on success; roll back on any error, unless the error says its writes are
        the point (domain errors with persist_writes, such as a blocked guard)."""
        try:
            yield self
        except BaseException as exc:
            if getattr(exc, "persist_writes", False):
                self.commit()
            else:
                self.rollback()
            raise
        else:
            self.commit()
