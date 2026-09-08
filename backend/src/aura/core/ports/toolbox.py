from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict = field(default_factory=dict)


@runtime_checkable
class Toolbox(Protocol):
    def list_tools(self) -> list[ToolSpec]: ...
    def call(self, name: str, arguments: dict) -> str: ...
