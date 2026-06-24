from __future__ import annotations

import json

import pytest
import respx
import httpx

from agentx.llm.base import LLMTimeoutError, NoToolCallError
from agentx.llm.openai_client import OpenAIClient
from agentx.llm.types import LLMConfig, Message, Role, ToolSpec

_BASE = "https://api.openai.com/v1"


def _make_config(**kwargs) -> LLMConfig:
    defaults = dict(provider="openai", model="gpt-4o", api_key="sk-test", timeout=30)
    defaults.update(kwargs)
    return LLMConfig(**defaults)


def _tool_spec() -> ToolSpec:
    return ToolSpec(
        name="read_file",
        description="Read a file",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    )


def _user_message() -> Message:
    return Message(role=Role.USER, content="Read calculator.py")


def _tool_call_response(name: str, args: dict) -> dict:
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_abc",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }],
            },
            "finish_reason": "tool_calls",
        }]
    }


def _text_response(text: str) -> dict:
    return {
        "choices": [{
            "message": {"role": "assistant", "content": text, "tool_calls": None},
            "finish_reason": "stop",
        }]
    }


@pytest.mark.asyncio
async def test_reason_tool_call():
    """Structured tool_calls → ToolCall returned."""
    cfg = _make_config()
    client = OpenAIClient(cfg)

    with respx.mock:
        respx.post(f"{_BASE}/chat/completions").mock(
            return_value=httpx.Response(200, json=_tool_call_response("read_file", {"path": "calc.py"}))
        )
        result = await client.reason([_user_message()], [_tool_spec()], turn=0)

    assert result.tool_name == "read_file"
    assert result.tool_input == {"path": "calc.py"}
    assert result.call_id == "call_abc"


@pytest.mark.asyncio
async def test_reason_turn0_text_raises():
    """turn=0, text response → NoToolCallError."""
    cfg = _make_config()
    client = OpenAIClient(cfg)

    with respx.mock:
        respx.post(f"{_BASE}/chat/completions").mock(
            return_value=httpx.Response(200, json=_text_response("The bug is on line 13."))
        )
        with pytest.raises(NoToolCallError):
            await client.reason([_user_message()], [_tool_spec()], turn=0)


@pytest.mark.asyncio
async def test_reason_turn1_text_returns_task_done():
    """turn=1, text response → task_done ToolCall."""
    cfg = _make_config()
    client = OpenAIClient(cfg)

    with respx.mock:
        respx.post(f"{_BASE}/chat/completions").mock(
            return_value=httpx.Response(200, json=_text_response("All done."))
        )
        result = await client.reason([_user_message()], [_tool_spec()], turn=1)

    assert result.tool_name == "task_done"


@pytest.mark.asyncio
async def test_reason_base_url_override():
    """base_url override forwarded to request URL."""
    cfg = _make_config(base_url="https://custom.endpoint.com/v1")
    client = OpenAIClient(cfg)

    with respx.mock:
        route = respx.post("https://custom.endpoint.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_tool_call_response("read_file", {"path": "x.py"}))
        )
        await client.reason([_user_message()], [_tool_spec()], turn=0)
        assert route.called


@pytest.mark.asyncio
async def test_reason_authorization_header():
    """Authorization: Bearer header present in every request."""
    cfg = _make_config(api_key="sk-mykey")
    client = OpenAIClient(cfg)

    captured_headers = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        return httpx.Response(200, json=_tool_call_response("read_file", {"path": "x.py"}))

    with respx.mock:
        respx.post(f"{_BASE}/chat/completions").mock(side_effect=_capture)
        await client.reason([_user_message()], [_tool_spec()], turn=0)

    assert captured_headers.get("authorization") == "Bearer sk-mykey"


@pytest.mark.asyncio
async def test_reason_timeout():
    """Timeout → LLMTimeoutError."""
    cfg = _make_config(timeout=1)
    client = OpenAIClient(cfg)

    with respx.mock:
        respx.post(f"{_BASE}/chat/completions").mock(side_effect=httpx.TimeoutException("timeout"))
        with pytest.raises(LLMTimeoutError):
            await client.reason([_user_message()], [_tool_spec()], turn=0)
