from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any, AsyncIterator

from ollama import AsyncClient

from agentx.llm.base import LLMTimeoutError, NoToolCallError, build_system
from agentx.llm.types import LLMConfig, Message, Role, StreamEvent, ToolCall, ToolSpec

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "qwen3:8b"
_DEFAULT_HOST = "http://localhost:11434"


def _to_ollama_messages(messages: list[Message], system: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    full_system = build_system(system)
    if full_system:
        out.append({"role": "system", "content": full_system})
    for m in messages:
        if m.role == Role.TOOL_RESULT:
            out.append({
                "role": "tool",
                "content": m.content,
                "tool_call_id": m.tool_call_id or "",
                "name": m.tool_name or "",
            })
        else:
            out.append({"role": m.role.value, "content": m.content})
    return out


def _to_ollama_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": s.name,
                "description": s.description,
                "parameters": s.input_schema,
            },
        }
        for s in specs
    ]


def _parse_response(message: Any, turn: int = 0) -> ToolCall:
    """Extract tool call from Ollama response using 5-step intelligence layer."""

    # Step 1: structured tool_calls block
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        tc = tool_calls[0]
        fn = tc.function
        raw_args = fn.arguments
        if isinstance(raw_args, str):
            args = json.loads(raw_args)
        else:
            args = dict(raw_args) if raw_args else {}
        return ToolCall(
            tool_name=fn.name,
            tool_input=args,
            call_id=str(uuid.uuid4()),
        )

    content = getattr(message, "content", "") or ""

    if content:
        # Step 2: JSON in text content (Qwen raw-JSON fallback)
        stripped = content.strip()
        # remove markdown fences
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)
            stripped = stripped.strip()
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict) and "name" in parsed:
                args = parsed.get("arguments") or parsed.get("parameters") or {}
                logger.debug("Qwen raw-JSON tool call recovered from text")
                return ToolCall(
                    tool_name=parsed["name"],
                    tool_input=dict(args) if args else {},
                    call_id=str(uuid.uuid4()),
                )
        except (json.JSONDecodeError, ValueError):
            pass

        # Step 3: Partial JSON recovery via regex
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, dict) and "name" in parsed:
                    args = parsed.get("arguments") or parsed.get("parameters") or {}
                    logger.debug("Partial JSON tool call recovered via regex")
                    return ToolCall(
                        tool_name=parsed["name"],
                        tool_input=dict(args) if args else {},
                        call_id=str(uuid.uuid4()),
                    )
            except (json.JSONDecodeError, ValueError):
                pass

    # Step 4: NoToolCallError on turn 0
    if turn == 0:
        raise NoToolCallError(content)

    # Step 5: synthesize task_done on turn >= 1
    return ToolCall(
        tool_name="task_done",
        tool_input={"summary": content[:500] or "Model did not call a tool."},
        call_id=str(uuid.uuid4()),
    )


class OllamaClient:
    """ModelClient backed by a local Ollama instance.

    Accepts LLMConfig (preferred) or legacy positional (model, host) strings.
    """

    def __init__(
        self,
        config_or_model: LLMConfig | str = _DEFAULT_MODEL,
        host: str = _DEFAULT_HOST,
    ) -> None:
        if isinstance(config_or_model, LLMConfig):
            cfg = config_or_model
            self._model = cfg.model or _DEFAULT_MODEL
            self._host = cfg.base_url or _DEFAULT_HOST
            self._timeout = cfg.timeout
        else:
            self._model = config_or_model
            self._host = host
            self._timeout = 120
        self._client = AsyncClient(host=self._host)

    async def reason(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str = "",
        turn: int = 0,
    ) -> ToolCall:
        try:
            resp = await asyncio.wait_for(
                self._client.chat(
                    model=self._model,
                    messages=_to_ollama_messages(messages, system),
                    tools=_to_ollama_tools(tools),
                ),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError as exc:
            raise LLMTimeoutError(f"LLM timeout after {self._timeout}s") from exc
        return _parse_response(resp.message, turn=turn)

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str = "",
        turn: int = 0,
    ) -> AsyncIterator[StreamEvent]:
        chunks: list[str] = []
        try:
            async for chunk in await self._client.chat(
                model=self._model,
                messages=_to_ollama_messages(messages, system),
                tools=_to_ollama_tools(tools),
                stream=True,
            ):
                msg = getattr(chunk, "message", None)
                content = getattr(msg, "content", "") if msg else ""
                if content:
                    chunks.append(content)
        except asyncio.TimeoutError as exc:
            raise LLMTimeoutError(f"LLM timeout after {self._timeout}s") from exc

        call = await self.reason(messages, tools, system=system, turn=turn)

        async def _gen() -> AsyncIterator[StreamEvent]:
            if chunks:
                yield StreamEvent(event_type="text_delta", data="".join(chunks))
            yield StreamEvent(event_type="tool_call", data=call)
            yield StreamEvent(event_type="done")

        return _gen()
