"""Model run lineage (PRD F8, SOSPE C6): one agent_run row per inference.

RunRecorder is the single place a row is built. Both orchestrators go through it, so there
is no inference path that skips the record. If the row cannot be written, AgentRunLogError is
raised and the output never reaches the caller.
"""
import time
from datetime import datetime

from typing import Any, Callable

from aura.core.clock import utcnow
from aura.agents.llm.repair import extract_json
from aura.core.domain.agent_run import AgentRun
from aura.core.policy.lineage_policy import canonical, prompt_hash  # noqa: F401
from aura.core.ports.orchestrator import AgentRunLogError, RunContext


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
    def __init__(self, context: RunContext, model_id: str, model_version: str):
        self.context, self.model_id, self.model_version = context, model_id, model_version
        self.last_run_id: int | None = None

    def record(self, *, archetype: str, template_id: str, messages: list[dict],
               output_text: str, started_at: datetime, completed_at: datetime,
               latency_ms: int, tokens_in: int = 0, tokens_out: int = 0,
               confidence: float | None = None, tool_calls: list | None = None,
               error: str | None = None) -> AgentRun:
        parsed = extract_json(output_text) if output_text and not error else None
        output = {"error": error} if error else {"text": output_text}
        run = AgentRun(
            id=None, job_id=self.context.job_id, deal_id=self.context.deal_id,
            task_id=self.context.task_id, archetype=archetype, model_id=self.model_id,
            model_version=self.model_version, prompt_template_id=template_id,
            prompt_hash=prompt_hash(messages),
            input_digest={"message_count": len(messages), "messages": messages},
            output=output,
            confidence=confidence if confidence is not None else _confidence(parsed),
            tokens_in=tokens_in, tokens_out=tokens_out, cost_inr=0.0, latency_ms=latency_ms,
            started_at=started_at, completed_at=completed_at,
            tool_calls=tool_calls if tool_calls is not None else _tool_calls(parsed))
        try:
            saved = self.context.runs.record(run)
            self.last_run_id = saved.id
            return saved
        except AgentRunLogError:
            raise
        except Exception as exc:
            raise AgentRunLogError(f"could not record agent run: {exc}") from exc

    def traced(self, call: Callable[[], Any], *, archetype: str, template_id: str,
               messages: list[dict], usage: Callable[[], tuple[int, int]] = lambda: (0, 0)):
        """Run `call`, record it, and only then hand back its result."""
        started = utcnow()
        clock = time.perf_counter()
        in_before, out_before = usage()
        try:
            result = call()
        except Exception as exc:
            try:  # a failed call is still a call; but the original error is what matters
                self.record(archetype=archetype, template_id=template_id, messages=messages,
                            output_text="", started_at=started,
                            completed_at=utcnow(),
                            latency_ms=int((time.perf_counter() - clock) * 1000),
                            error=f"{type(exc).__name__}: {exc}")
            except AgentRunLogError:
                pass
            raise
        in_after, out_after = usage()
        text = result if isinstance(result, str) else str(result)
        self.record(archetype=archetype, template_id=template_id, messages=messages,
                    output_text=text, started_at=started,
                    completed_at=utcnow(),
                    latency_ms=int((time.perf_counter() - clock) * 1000),
                    tokens_in=max(0, in_after - in_before),
                    tokens_out=max(0, out_after - out_before))
        return result
