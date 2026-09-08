"""Classify MCP tools into gate categories. Default-deny."""
from aura.core.domain.enums import ActionCategory
from aura.core.policy.gate_policy import classify, requires_approval
from aura.core.ports.toolbox import ToolSpec


def classify_tools(specs: list[ToolSpec]) -> dict[str, ActionCategory]:
    return {spec.name: classify(spec.name) for spec in specs}


def is_gated(tool_name: str) -> bool:
    return requires_approval(classify(tool_name))
