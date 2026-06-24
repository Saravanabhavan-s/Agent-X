from __future__ import annotations

from collections import deque
from typing import AsyncIterator

from agentx.llm.types import Message, StreamEvent, ToolCall, ToolSpec


class FakeModelClient:
    """Scripted tool calls for deterministic testing. Feed a sequence of ToolCalls;
    each reason() call pops the next one."""

    def __init__(self, script: list[ToolCall]) -> None:
        self._queue: deque[ToolCall] = deque(script)
        self.calls: list[tuple[list[Message], list[ToolSpec]]] = []

    def queue(self, call: ToolCall) -> None:
        self._queue.append(call)

    async def reason(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str = "",
        turn: int = 0,
    ) -> ToolCall:
        self.calls.append((messages, tools))
        if not self._queue:
            raise RuntimeError("FakeModelClient script exhausted")
        return self._queue.popleft()

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str = "",
        turn: int = 0,
    ) -> AsyncIterator[StreamEvent]:
        call = await self.reason(messages, tools, system=system)

        async def _gen() -> AsyncIterator[StreamEvent]:
            yield StreamEvent(event_type="tool_call", data=call)
            yield StreamEvent(event_type="done")

        return _gen()
