from __future__ import annotations

from typing import Protocol, runtime_checkable

from agentx.llm.types import ToolCall
from agentx.tools.base import Risk


@runtime_checkable
class GovernanceGate(Protocol):
    async def check(self, tool_call: ToolCall, risk: Risk) -> bool:
        """Return True to allow, False to block (triggers AWAITING_APPROVAL)."""
        ...


class NullGate:
    """Allow everything — used in tests and non-interactive runs."""

    async def check(self, tool_call: ToolCall, risk: Risk) -> bool:
        return True


class CliApprovalGate:
    """Prompt the user for WRITE/DESTRUCTIVE actions on stdin."""

    def __init__(self, auto_approve_safe: bool = True) -> None:
        self._auto = auto_approve_safe

    async def check(self, tool_call: ToolCall, risk: Risk) -> bool:
        if self._auto and risk == Risk.SAFE:
            return True
        print(
            f"\n[APPROVAL REQUIRED] Tool: {tool_call.tool_name!r}  Risk: {risk.value}\n"
            f"  Input: {tool_call.tool_input}\n"
            "Allow? [y/N] ",
            end="",
            flush=True,
        )
        try:
            answer = input().strip().lower()
        except EOFError:
            answer = "n"
        return answer in ("y", "yes")
