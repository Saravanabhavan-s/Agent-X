from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from agentx.llm.types import Message, StreamEvent, ToolCall, ToolSpec


@runtime_checkable
class ModelClient(Protocol):
    async def reason(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str = "",
        turn: int = 0,
    ) -> ToolCall: ...

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str = "",
        turn: int = 0,
    ) -> AsyncIterator[StreamEvent]: ...


class NoToolCallError(Exception):
    """Raised when model returns pure text with no tool call on turn 0."""

    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__(f"No tool call on turn 0. Model returned: {text[:200]}")


class LLMTimeoutError(Exception):
    """Raised when LLM call exceeds configured timeout."""
    pass


class SessionError(Exception):
    """Raised when the session cannot continue (e.g. repeated tool-call refusals)."""
    pass


SYSTEM_PREFIX = (
    "You are an autonomous coding agent. "
    "You NEVER answer questions directly with text alone. "
    "You ALWAYS verify state by calling tools before responding. "
    "If the goal involves running, fixing, or testing code, "
    "you MUST call run_tests or bash and observe real output "
    "before declaring done."
)


def build_system(system: str = "") -> str:
    """Prepend the autonomous-agent instruction prefix to any caller-supplied system prompt."""
    if system:
        return SYSTEM_PREFIX + "\n\n" + system
    return SYSTEM_PREFIX
