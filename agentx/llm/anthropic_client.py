from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

import anthropic

from agentx.llm.base import LLMTimeoutError, NoToolCallError, build_system
from agentx.llm.types import LLMConfig, Message, Role, StreamEvent, ToolCall, ToolSpec

logger = logging.getLogger(__name__)


def _to_anthropic_messages(messages: list[Message]) -> list[dict]:
    out = []
    for m in messages:
        if m.role == Role.TOOL_RESULT:
            out.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": m.tool_call_id or "",
                        "content": m.content,
                    }
                ],
            })
        elif m.role == Role.SYSTEM:
            # system messages are passed via the system= param, skip here
            continue
        else:
            out.append({"role": m.role.value, "content": m.content})
    return out


def _to_anthropic_tools(specs: list[ToolSpec]) -> list[dict]:
    return [
        {
            "name": s.name,
            "description": s.description,
            "input_schema": s.input_schema,
        }
        for s in specs
    ]


class AnthropicClient:
    """ModelClient backed by the Anthropic SDK."""

    def __init__(self, config: LLMConfig) -> None:
        if not config.api_key:
            raise ValueError(
                "AnthropicClient requires api_key. "
                "Set ANTHROPIC_API_KEY env var or pass --api-key."
            )
        self._client = anthropic.AsyncAnthropic(api_key=config.api_key)
        self._config = config

    async def reason(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str = "",
        turn: int = 0,
    ) -> ToolCall:
        ant_messages = _to_anthropic_messages(messages)
        ant_tools = _to_anthropic_tools(tools)

        try:
            resp = await asyncio.wait_for(
                self._client.messages.create(
                    model=self._config.model,
                    max_tokens=self._config.max_tokens,
                    system=build_system(system),
                    messages=ant_messages,
                    tools=ant_tools,  # type: ignore[arg-type]
                    tool_choice={"type": "auto"},
                    temperature=self._config.temperature,
                ),
                timeout=self._config.timeout,
            )
        except asyncio.TimeoutError as exc:
            raise LLMTimeoutError(f"LLM timeout after {self._config.timeout}s") from exc

        # Step 1: tool_use content blocks
        for block in resp.content:
            if block.type == "tool_use":
                return ToolCall(
                    tool_name=block.name,
                    tool_input=dict(block.input),
                    call_id=block.id,
                )

        # Collect any text content
        text = " ".join(
            block.text for block in resp.content if block.type == "text"
        )

        # Step 4: NoToolCallError on turn 0
        if turn == 0:
            raise NoToolCallError(text)

        # Step 5: task_done on turn >= 1
        return ToolCall(
            tool_name="task_done",
            tool_input={"summary": text[:500] or "Model did not call a tool."},
            call_id="",
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str = "",
        turn: int = 0,
    ) -> AsyncIterator[StreamEvent]:
        ant_messages = _to_anthropic_messages(messages)
        ant_tools = _to_anthropic_tools(tools)

        text_parts: list[str] = []
        tool_call: ToolCall | None = None

        async def _gen() -> AsyncIterator[StreamEvent]:
            nonlocal tool_call
            try:
                async with self._client.messages.stream(
                    model=self._config.model,
                    max_tokens=self._config.max_tokens,
                    system=build_system(system),
                    messages=ant_messages,
                    tools=ant_tools,  # type: ignore[arg-type]
                    tool_choice={"type": "auto"},
                    temperature=self._config.temperature,
                ) as stream:
                    async for event in stream:
                        if hasattr(event, "type"):
                            if event.type == "content_block_delta":
                                delta = getattr(event, "delta", None)
                                if delta and getattr(delta, "type", None) == "text_delta":
                                    text_parts.append(delta.text)
                                    yield StreamEvent(event_type="text_delta", data=delta.text)
                    # After streaming, get the final message for tool calls
                    final = await stream.get_final_message()
                    for block in final.content:
                        if block.type == "tool_use":
                            tool_call = ToolCall(
                                tool_name=block.name,
                                tool_input=dict(block.input),
                                call_id=block.id,
                            )
                            break
            except asyncio.TimeoutError as exc:
                raise LLMTimeoutError(f"LLM timeout after {self._config.timeout}s") from exc

            if tool_call is None:
                text = "".join(text_parts)
                if turn == 0:
                    raise NoToolCallError(text)
                tool_call = ToolCall(
                    tool_name="task_done",
                    tool_input={"summary": text[:500] or "Model did not call a tool."},
                    call_id="",
                )

            yield StreamEvent(event_type="tool_call", data=tool_call)
            yield StreamEvent(event_type="done")

        return _gen()
