"""Model run lineage (PRD F8, SOSPE C6): one agent_run row per inference.

RunRecorder is the single place a row is built. Both orchestrators go through it, so there
is no inference path that skips the record. If the row cannot be written, AgentRunLogError is
raised and the output never reaches the caller.

It is also where the per-segment harness limits live (one recorder per segment run):
- a transient model error (connection refused, timeout, 5xx) is retried up to
  llm_max_retries times with backoff; every attempt is its own agent_run row, so lineage
  shows the failures too;
- more than max_llm_calls_per_segment calls, or a segment running past
  max_segment_seconds, raises BudgetExceeded (permanent: the segment fails);
- at most max_concurrent_llm_calls model calls run at once, process-wide (a semaphore: one
  local CPU model cannot serve two calls usefully).

Each recorded run is also an llm.call span (GenAI semantic-convention attributes), and the
row carries that span's trace_id and span_id.
"""
import threading
import time
from datetime import datetime

from typing import Any, Callable

from aura.core.clock import utcnow
from aura.agents.llm.repair import extract_json
from aura.core.domain.agent_run import AgentRun
from aura.core.policy.lineage_policy import canonical, prompt_hash  # noqa: F401
from aura.core.policy.retry_policy import is_transient
from aura.core.ports.orchestrator import (AgentRunLogError, BudgetExceeded, RunContext,
                                          TransientModelError)
from aura.core.tracing import tracer

_SLOTS_LOCK = threading.Lock()
_SLOTS: tuple[int, threading.BoundedSemaphore] | None = None
_HELD = threading.local()


class _Slot:
    """One model-call slot, re-entrant per thread (a call that triggers another call on the
    same thread must not wait for itself)."""

    def __init__(self, semaphore: threading.BoundedSemaphore | None):
        self.semaphore = semaphore

    def release(self) -> None:
        if self.semaphore is not None:
            _HELD.depth -= 1
            if _HELD.depth == 0:
                self.semaphore.release()
            self.semaphore = None


def llm_slot(timeout: float) -> _Slot:
    """Take a slot of the process-wide model-call semaphore (max_concurrent_llm_calls);
    TransientModelError if none frees up in time."""
    global _SLOTS
    from aura.config import get_settings
    size = max(1, get_settings().max_concurrent_llm_calls)
    with _SLOTS_LOCK:
        if _SLOTS is None or _SLOTS[0] != size:
            _SLOTS = (size, threading.BoundedSemaphore(size))
        semaphore = _SLOTS[1]
    depth = getattr(_HELD, "depth", 0)
    if depth == 0 and not semaphore.acquire(timeout=timeout):
        raise TransientModelError("no free model slot (max_concurrent_llm_calls)")
    _HELD.depth = depth + 1
    return _Slot(semaphore)


def normalise_messages(messages: Any) -> list[dict]:
    if isinstance(messages, str):
        return [{"role": "user", "content": messages}]
    return [{"role": str(m.get("role", "")), "content": m.get("content", "")}
            for m in messages]


def _confidence(parsed: dict | None) -> float | None:
    value = (parsed or {}).get("confidence")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1:
        return float(value)
    return None


def _tool_calls(parsed: dict | None) -> list[dict]:
    if parsed and "tool" in parsed:
        return [{"tool": str(parsed["tool"]), "arguments": parsed.get("arguments") or {}}]
    return []


class RunRecorder:
    def __init__(self, context: RunContext, model_id: str, model_version: str, *,
                 max_retries: int | None = None, retry_backoff_seconds: float | None = None,
                 max_calls: int | None = None, max_seconds: float | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        from aura.config import get_settings
        s = get_settings()
        self.context, self.model_id, self.model_version = context, model_id, model_version
        self.last_run_id: int | None = None
        self.max_retries = s.llm_max_retries if max_retries is None else max_retries
        self.retry_backoff = s.llm_retry_backoff_seconds if retry_backoff_seconds is None \
            else retry_backoff_seconds
        self.max_calls = s.max_llm_calls_per_segment if max_calls is None else max_calls
        self.max_seconds = s.max_segment_seconds if max_seconds is None else max_seconds
        self._sleep = sleep
        self._started = time.monotonic()
        self.calls = 0
        # The span this recorder was made under (segment.run), for calls CrewAI makes on
        # another thread.
        self._parent_span = tracer.current()

    def check_budget(self) -> None:
        """Raise BudgetExceeded before a call that would break the segment's limits."""
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"segment budget exceeded: more than {self.max_calls} model "
                                 "calls (max_llm_calls_per_segment)")
        elapsed = time.monotonic() - self._started
        if elapsed > self.max_seconds:
            raise BudgetExceeded(f"segment budget exceeded: ran {int(elapsed)} s, over "
                                 f"{self.max_seconds} s (max_segment_seconds)")

    def record(self, *, archetype: str, template_id: str, messages: list[dict],
               output_text: str, started_at: datetime, completed_at: datetime,
               latency_ms: int, tokens_in: int = 0, tokens_out: int = 0,
               confidence: float | None = None, tool_calls: list | None = None,
               error: str | None = None) -> AgentRun:
        parsed = extract_json(output_text) if output_text and not error else None
        output = {"error": error} if error else {"text": output_text}
        archetype = f"{getattr(self.context, 'archetype_prefix', '') or ''}{archetype}"
        digest = {"message_count": len(messages), "messages": messages}
        if getattr(self.context, "notes", None):
            digest["notes"] = self.context.notes
        span = tracer.record("llm.call", started_at, completed_at, {
            "gen_ai.operation.name": "chat", "gen_ai.system": "ollama"
            if self.model_id != "stub" else "stub",
            "gen_ai.request.model": self.model_id, "gen_ai.response.model": self.model_id,
            "gen_ai.usage.input_tokens": tokens_in, "gen_ai.usage.output_tokens": tokens_out,
            "aura.archetype": archetype, "aura.prompt_template_id": template_id,
            "aura.job_id": self.context.job_id, "aura.segment_id": self.context.segment_id,
            **({"error.type": error.split(":", 1)[0]} if error else {})},
            status="error" if error else "ok", parent=self._parent_span)
        run = AgentRun(
            id=None, job_id=self.context.job_id, deal_id=self.context.deal_id,
            task_id=self.context.task_id, archetype=archetype, model_id=self.model_id,
            model_version=self.model_version, prompt_template_id=template_id,
            prompt_hash=prompt_hash(messages), input_digest=digest, output=output,
            confidence=confidence if confidence is not None else _confidence(parsed),
            tokens_in=tokens_in, tokens_out=tokens_out, cost_inr=0.0, latency_ms=latency_ms,
            started_at=started_at, completed_at=completed_at,
            tool_calls=tool_calls if tool_calls is not None else _tool_calls(parsed),
            segment_id=self.context.segment_id, trace_id=span.trace_id, span_id=span.span_id)
        try:
            saved = self.context.runs.record(run)
            self.last_run_id = saved.id
            span.set("aura.agent_run_id", saved.id)
            return saved
        except AgentRunLogError:
            raise
        except Exception as exc:
            raise AgentRunLogError(f"could not record agent run: {exc}") from exc

    def traced(self, call: Callable[[], Any], *, archetype: str, template_id: str,
               messages: list[dict], usage: Callable[[], tuple[int, int]] = lambda: (0, 0)):
        """Run `call`, record it, and only then hand back its result. A transient failure
        is recorded and retried (with backoff) up to max_retries times."""
        attempt = 0
        while True:
            self.check_budget()
            self.calls += 1
            started = utcnow()
            clock = time.perf_counter()
            in_before, out_before = usage()
            slot = llm_slot(timeout=max(1.0, self.max_seconds))
            try:
                result = call()
                break
            except Exception as exc:
                try:  # a failed call is still a call; but the original error is what matters
                    self.record(archetype=archetype, template_id=template_id,
                                messages=messages, output_text="", started_at=started,
                                completed_at=utcnow(),
                                latency_ms=int((time.perf_counter() - clock) * 1000),
                                error=f"{type(exc).__name__}: {exc}")
                except AgentRunLogError:
                    pass
                if attempt >= self.max_retries or not is_transient(exc):
                    raise
                slot.release()
                self._sleep(self.retry_backoff * 2 ** attempt)
                attempt += 1
            finally:
                slot.release()

        in_after, out_after = usage()
        text = result if isinstance(result, str) else str(result)
        self.record(archetype=archetype, template_id=template_id, messages=messages,
                    output_text=text, started_at=started,
                    completed_at=utcnow(),
                    latency_ms=int((time.perf_counter() - clock) * 1000),
                    tokens_in=max(0, in_after - in_before),
                    tokens_out=max(0, out_after - out_before))
        return result
