"""The deals MCP tools, attached to the crew behind gate_policy.

Every tool an agent can call passes through gate_policy BEFORE it runs. Ungated tools
(internal reads and writes) execute. Gated ones (send_email and anything unmapped) are never
executed: the attempt is recorded on the run's ToolGate, the agent is told it is waiting
for a person, and the orchestrator turns the record into a task and handoff, so the
segment pauses. The tool body of a gated tool is unreachable from the crew.

Each call is a tool.call span. What an ungated tool returns is screened for prompt injection
before the agent sees it: hidden characters are stripped, and output that looks like an
injection is wrapped as untrusted data and recorded on the gate (the segment then goes to a
person, trigger 'untrusted_content').
"""
import inspect
from typing import Any, Callable

from crewai.tools import BaseTool
from pydantic import PrivateAttr, create_model

from aura.core.domain.segment import ProposedAction
from aura.core.policy.gate_policy import (DEFAULT_MATERIALITY_CAP_INR, classify,
                                          requires_approval)
from aura.core.policy.injection_policy import DEFAULT_THRESHOLD, screen, wrap
from aura.core.tracing import tracer
from aura.mcp.identity import acting_as

BLOCKED_MESSAGE = ("NOT EXECUTED: '{tool}' needs human approval, so it was not run. It has "
                   "been queued as a task for a person. Do not call it again; carry on "
                   "without it.")


def _materiality(arguments: dict) -> int | None:
    value = arguments.get("amount_inr")
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
        else None


class ToolGate:
    """Per-run record of the gated tool calls an agent attempted."""

    def __init__(self, summary: str, cap_inr: int = DEFAULT_MATERIALITY_CAP_INR,
                 injection_threshold: float = DEFAULT_THRESHOLD):
        self.summary, self.cap_inr = summary, cap_inr
        self.injection_threshold = injection_threshold
        self.proposals: list[ProposedAction] = []
        # Screening records of tool output that looked like a prompt injection.
        self.untrusted_outputs: list[dict] = []
        self.parent_span = tracer.current()

    def screen_output(self, tool: str, output: str) -> str:
        result = screen(output)
        if result.flagged(self.injection_threshold):
            self.untrusted_outputs.append(result.as_dict(f"tool:{tool}"))
            return wrap(result.text, f"output of tool {tool}")
        return result.text

    def needs_approval(self, tool: str, arguments: dict) -> bool:
        return requires_approval(classify(tool), _materiality(arguments), self.cap_inr)

    def record(self, tool: str, arguments: dict) -> ProposedAction:
        action = ProposedAction(tool=tool, category=classify(tool), arguments=arguments,
                                summary=self.summary or f"Run {tool}",
                                materiality_inr=_materiality(arguments))
        self.proposals.append(action)
        return action


class GatedTool(BaseTool):
    """One MCP function exposed to CrewAI. The gate decides whether the body may run."""
    _fn: Callable[..., Any] = PrivateAttr()
    _gate: ToolGate = PrivateAttr()
    _username: str | None = PrivateAttr(default=None)

    def _run(self, **kwargs: Any) -> str:
        parent = self._gate.parent_span if tracer.current() is None else None
        with tracer.span("tool.call", {"gen_ai.operation.name": "execute_tool",
                                       "gen_ai.tool.name": self.name},
                         trace_id=parent.trace_id if parent else None,
                         parent_span_id=parent.span_id if parent else None,
                         deal_id=parent.deal_id if parent else None) as span:
            gated = self._gate.needs_approval(self.name, kwargs)
            span.set("aura.gated", gated)
            if gated:
                self._gate.record(self.name, kwargs)
                return BLOCKED_MESSAGE.format(tool=self.name)
            with acting_as(self._username):
                return self._gate.screen_output(self.name, str(self._fn(**kwargs)))


def _args_schema(name: str, fn: Callable[..., Any]):
    fields = {}
    for param in inspect.signature(fn).parameters.values():
        annotation = param.annotation if param.annotation is not inspect.Parameter.empty \
            else str
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param.name] = (annotation, default)
    return create_model(f"{name}_args", **fields)


def deals_server_functions() -> dict[str, Callable[..., Any]]:
    """The first-party deals MCP server's tools, as plain callables."""
    from aura.mcp.servers import deals_server
    return {"get_deal_status": deals_server.get_deal_status,
            "list_deals": deals_server.list_deals,
            "add_internal_note": deals_server.add_internal_note,
            "send_email": deals_server.send_email}


def build_deal_tools(gate: ToolGate, username: str | None,
                     functions: dict[str, Callable[..., Any]] | None = None) -> list[BaseTool]:
    """CrewAI tools for the MCP functions, every call gated. `functions` lets a test swap in
    spies; the default is the real deals server."""
    tools = []
    for name, fn in (functions if functions is not None else deals_server_functions()).items():
        tool = GatedTool(name=name, description=inspect.getdoc(fn) or name,
                         args_schema=_args_schema(name, fn))
        tool._fn, tool._gate, tool._username = fn, gate, username
        tools.append(tool)
    return tools