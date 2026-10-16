"""A minimal, local-only tracer shaped like OpenTelemetry (trace and span ids, parent links,
attributes, status; GenAI semantic-convention attribute names on model calls).

Why not the OpenTelemetry SDK: Aura forces OTEL_SDK_DISABLED=true (aura.agents, so CrewAI's
telemetry stays off), and the SDK then hands out no-op tracers, so it would record nothing; its
global provider is also shared with CrewAI. This tracer has no exporter that can reach a
network: finished spans wait in an in-memory buffer until the data layer writes them to the
trace_span table (aura.data.spans.flush_spans, called after every unit-of-work commit).

Spans nest through a context variable. A span may also be started with an explicit trace id
and parent (a segment continues its job's trace), so a trace survives the hop from the API
request to the worker thread.
"""
import secrets
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator

from aura.core.clock import utcnow

MAX_BUFFERED_SPANS = 10_000


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


@dataclass
class Span:
    name: str
    trace_id: str | None
    span_id: str | None
    parent_span_id: str | None
    start: datetime
    end: datetime | None = None
    attributes: dict = field(default_factory=dict)
    status: str = "unset"  # unset | ok | error
    deal_id: int | None = None

    def set(self, key: str, value: Any) -> None:
        if self.span_id is not None and value is not None:
            self.attributes[key] = value

    def set_attributes(self, values: dict) -> None:
        for key, value in values.items():
            self.set(key, value)


def _noop(name: str) -> Span:
    return Span(name=name, trace_id=None, span_id=None, parent_span_id=None, start=utcnow())


_current: ContextVar[Span | None] = ContextVar("aura_current_span", default=None)


class Tracer:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._buffer: list[Span] = []
        self._lock = threading.Lock()

    def configure(self, enabled: bool) -> None:
        self.enabled = enabled

    @staticmethod
    def current() -> Span | None:
        return _current.get()

    def _open(self, name: str, attributes: dict | None, trace_id: str | None,
              parent_span_id: str | None, deal_id: int | None,
              start: datetime | None = None) -> Span:
        parent = _current.get()
        if trace_id is None and parent is not None and parent.trace_id is not None:
            trace_id = parent.trace_id
            parent_span_id = parent_span_id or parent.span_id
            deal_id = deal_id if deal_id is not None else parent.deal_id
        if trace_id is None:
            trace_id, parent_span_id = new_trace_id(), None
        span = Span(name=name, trace_id=trace_id, span_id=new_span_id(),
                    parent_span_id=parent_span_id, start=start or utcnow(), deal_id=deal_id)
        span.set_attributes(attributes or {})
        return span

    @contextmanager
    def span(self, name: str, attributes: dict | None = None, *, trace_id: str | None = None,
             parent_span_id: str | None = None, deal_id: int | None = None) -> Iterator[Span]:
        """Open a span for the duration of the block. With no explicit trace id it joins the
        current span's trace (or starts a new one). An exception marks it 'error'."""
        if not self.enabled:
            yield _noop(name)
            return
        span = self._open(name, attributes, trace_id, parent_span_id, deal_id)
        token = _current.set(span)
        try:
            yield span
        except BaseException as exc:
            span.status = "error"
            span.attributes["error.type"] = type(exc).__name__
            span.attributes["error.message"] = str(exc)[:500]
            raise
        finally:
            _current.reset(token)
            span.end = utcnow()
            if span.status == "unset":
                span.status = "ok"
            self._export(span)

    def record(self, name: str, start: datetime, end: datetime, attributes: dict | None = None,
               status: str = "ok", parent: Span | None = None) -> Span:
        """A span that already happened (start and end known), under the current span, or
        under `parent` when this thread has none."""
        if not self.enabled:
            return _noop(name)
        token = _current.set(parent) if _current.get() is None and parent is not None \
            else None
        try:
            span = self._open(name, attributes, None, None, None, start=start)
        finally:
            if token is not None:
                _current.reset(token)
        span.end, span.status = end, status
        self._export(span)
        return span

    def _export(self, span: Span) -> None:
        with self._lock:
            self._buffer.append(span)
            if len(self._buffer) > MAX_BUFFERED_SPANS:
                del self._buffer[:len(self._buffer) - MAX_BUFFERED_SPANS]

    def drain(self) -> list[Span]:
        with self._lock:
            spans, self._buffer = self._buffer, []
        return spans


tracer = Tracer()


def current_trace() -> tuple[str | None, str | None]:
    """(trace_id, span_id) of the span this thread is in, or (None, None)."""
    span = _current.get()
    return (span.trace_id, span.span_id) if span is not None else (None, None)
