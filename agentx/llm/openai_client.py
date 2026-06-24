from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, AsyncIterator

import httpx

from agentx.llm.base import LLMTimeoutError, NoToolCallError, build_system
from agentx.llm.types import LLMConfig, Message, Role, StreamEvent, ToolCall, ToolSpec

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.openai.com/v1"


def _to_openai_messages(messages: list[Message], system: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": build_system(system)}]
    for m in messages:
        if m.role == Role.TOOL_RESULT:
            out.append({
                "role": "tool",
                "content": m.content,
                "tool_call_id": m.tool_call_id or "",
            })
        else:
            out.append({"role": m.role.value, "content": m.content})
    return out


def _to_openai_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
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


def _parse_tool_call_from_response(
    choice: dict[str, Any], content: str, turn: int
) -> ToolCall:
    """Apply 5-step intelligence layer to an OpenAI-compatible response choice."""

    # Step 1: structured tool_calls
    tool_calls = (choice.get("message") or choice.get("delta") or {}).get("tool_calls")
    if tool_calls:
        tc = tool_calls[0]
        fn = tc.get("function", {})
        raw_args = fn.get("arguments", "{}")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            args = {}
        return ToolCall(
            tool_name=fn.get("name", ""),
            tool_input=args,
            call_id=tc.get("id") or str(uuid.uuid4()),
        )

    if content:
        # Step 2: raw JSON in content
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)
            stripped = stripped.strip()
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict) and "name" in parsed:
                args = parsed.get("arguments") or parsed.get("parameters") or {}
                return ToolCall(
                    tool_name=parsed["name"],
                    tool_input=dict(args) if args else {},
                    call_id=str(uuid.uuid4()),
                )
        except (json.JSONDecodeError, ValueError):
            pass

        # Step 3: partial JSON via regex
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, dict) and "name" in parsed:
                    args = parsed.get("arguments") or parsed.get("parameters") or {}
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

    # Step 5: task_done on turn >= 1
    return ToolCall(
        tool_name="task_done",
        tool_input={"summary": content[:500] or "Model did not call a tool."},
        call_id=str(uuid.uuid4()),
    )


class OpenAIClient:
    """ModelClient using httpx against an OpenAI-compatible /v1/chat/completions endpoint."""

    def __init__(self, config: LLMConfig) -> None:
        if not config.api_key:
            raise ValueError(
                "OpenAIClient requires api_key. "
                "Set OPENAI_API_KEY or pass --api-key."
            )
        self._config = config
        self._base_url = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")

    def _make_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "tool_choice": "auto",
        }
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream"] = True
        return payload

    async def reason(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str = "",
        turn: int = 0,
    ) -> ToolCall:
        oai_messages = _to_openai_messages(messages, system)
        oai_tools = _to_openai_tools(tools)
        payload = self._build_payload(oai_messages, oai_tools)

        try:
            async with httpx.AsyncClient(timeout=self._config.timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers=self._make_headers(),
                    json=payload,
                )
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"LLM timeout after {self._config.timeout}s") from exc

        choice = data["choices"][0]
        content = (choice.get("message") or {}).get("content") or ""
        return _parse_tool_call_from_response(choice, content, turn)

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str = "",
        turn: int = 0,
    ) -> AsyncIterator[StreamEvent]:
        from httpx_sse import aconnect_sse  # type: ignore[import]

        oai_messages = _to_openai_messages(messages, system)
        oai_tools = _to_openai_tools(tools)
        payload = self._build_payload(oai_messages, oai_tools, stream=True)

        text_chunks: list[str] = []
        accumulated_tool_calls: dict[int, dict[str, Any]] = {}

        async def _gen() -> AsyncIterator[StreamEvent]:
            try:
                async with httpx.AsyncClient(timeout=self._config.timeout) as client:
                    async with aconnect_sse(
                        client,
                        "POST",
                        f"{self._base_url}/chat/completions",
                        headers=self._make_headers(),
                        json=payload,
                    ) as event_source:
                        async for event in event_source.aiter_sse():
                            if event.data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(event.data)
                            except json.JSONDecodeError:
                                continue
                            choice = chunk.get("choices", [{}])[0]
                            delta = choice.get("delta", {})

                            # accumulate text
                            delta_content = delta.get("content") or ""
                            if delta_content:
                                text_chunks.append(delta_content)
                                yield StreamEvent(event_type="text_delta", data=delta_content)

                            # accumulate tool call deltas
                            for tc_delta in delta.get("tool_calls") or []:
                                idx = tc_delta.get("index", 0)
                                if idx not in accumulated_tool_calls:
                                    accumulated_tool_calls[idx] = {
                                        "id": tc_delta.get("id", ""),
                                        "function": {"name": "", "arguments": ""},
                                    }
                                fn = tc_delta.get("function", {})
                                accumulated_tool_calls[idx]["function"]["name"] += fn.get("name", "")
                                accumulated_tool_calls[idx]["function"]["arguments"] += fn.get("arguments", "")
            except httpx.TimeoutException as exc:
                raise LLMTimeoutError(f"LLM timeout after {self._config.timeout}s") from exc

            # emit final tool call event
            if accumulated_tool_calls:
                tc = accumulated_tool_calls[0]
                raw_args = tc["function"]["arguments"]
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {}
                call = ToolCall(
                    tool_name=tc["function"]["name"],
                    tool_input=args,
                    call_id=tc["id"] or str(uuid.uuid4()),
                )
            else:
                content = "".join(text_chunks)
                synthetic_choice: dict[str, Any] = {"message": {"tool_calls": None, "content": content}}
                call = _parse_tool_call_from_response(synthetic_choice, content, turn)

            yield StreamEvent(event_type="tool_call", data=call)
            yield StreamEvent(event_type="done")

        return _gen()
