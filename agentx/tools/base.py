from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel

if TYPE_CHECKING:
    from agentx.runtime.sandbox import Sandbox


class Risk(str, Enum):
    SAFE = "SAFE"
    WRITE = "WRITE"
    DESTRUCTIVE = "DESTRUCTIVE"


@dataclass
class ToolResult:
    ok: bool
    observation: str
    data: Any = None
    requires_approval: bool = False
    artifacts: list[str] = field(default_factory=list)


@dataclass
class ToolContext:
    workspace: str
    session_id: str
    sandbox: "Sandbox | None" = None


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    risk: Risk
    input_schema: dict[str, Any]

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult: ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_registry: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    _registry[tool.name] = tool
    return tool


def get(name: str) -> Tool:
    try:
        return _registry[name]
    except KeyError:
        raise KeyError(f"Unknown tool: {name!r}. Registered: {list(_registry)}")


def all_tools() -> list[Tool]:
    return list(_registry.values())


def clear_registry() -> None:
    """For tests only."""
    _registry.clear()
