from __future__ import annotations

import json

import pytest
import respx
import httpx

from agentx.llm.openrouter_client import OpenRouterClient, _OPENROUTER_BASE_URL
from agentx.llm.types import LLMConfig, Message, Role, ToolSpec


def _make_config(**kwargs) -> LLMConfig:
    defaults = dict(
        provider="openrouter",
        model="meta-llama/llama-3-70b-instruct",
        api_key="sk-or-test",
    )
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


@pytest.mark.asyncio
async def test_openrouter_default_base_url():
    """base_url defaults to openrouter.ai endpoint when not provided."""
    cfg = _make_config()
    client = OpenRouterClient(cfg)
    assert client._base_url == _OPENROUTER_BASE_URL.rstrip("/")


@pytest.mark.asyncio
async def test_openrouter_base_url_override():
    """Custom base_url is respected."""
    cfg = _make_config(base_url="https://my-proxy.example.com/v1")
    client = OpenRouterClient(cfg)
    assert "my-proxy.example.com" in client._base_url


@pytest.mark.asyncio
async def test_openrouter_required_headers():
    """HTTP-Referer and X-Title headers present in every request."""
    cfg = _make_config()
    client = OpenRouterClient(cfg)

    captured = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.headers))
        return httpx.Response(200, json=_tool_call_response("read_file", {"path": "x.py"}))

    with respx.mock:
        respx.post(f"{_OPENROUTER_BASE_URL}/chat/completions").mock(side_effect=_capture)
        await client.reason([_user_message()], [_tool_spec()], turn=0)

    assert captured.get("http-referer") == "https://agentx.local"
    assert captured.get("x-title") == "Agent X"


@pytest.mark.asyncio
async def test_openrouter_inherits_tool_parse():
    """OpenRouterClient inherits OpenAIClient tool-call parsing."""
    cfg = _make_config()
    client = OpenRouterClient(cfg)

    with respx.mock:
        respx.post(f"{_OPENROUTER_BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(
                200, json=_tool_call_response("run_tests", {"path": "."})
            )
        )
        result = await client.reason([_user_message()], [_tool_spec()], turn=0)

    assert result.tool_name == "run_tests"
