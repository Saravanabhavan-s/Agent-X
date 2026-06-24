from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentx.llm.base import LLMTimeoutError, NoToolCallError
from agentx.llm.ollama_client import OllamaClient, _parse_response
from agentx.llm.types import LLMConfig, Message, Role, ToolCall, ToolSpec


def _make_config(**kwargs) -> LLMConfig:
    defaults = dict(provider="ollama", model="qwen2.5-coder:7b", timeout=30)
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


# ── _parse_response unit tests ───────────────────────────────────────────────

def _make_msg(tool_calls=None, content=""):
    msg = SimpleNamespace(tool_calls=tool_calls, content=content)
    if tool_calls:
        tc = SimpleNamespace(
            function=SimpleNamespace(name=tool_calls[0]["name"], arguments=tool_calls[0]["args"])
        )
        msg.tool_calls = [tc]
    return msg


def test_parse_structured_tool_calls():
    """Step 1: structured tool_calls block → ToolCall returned."""
    tc_raw = [{"name": "read_file", "args": {"path": "calc.py"}}]
    msg = _make_msg(tool_calls=tc_raw)
    result = _parse_response(msg, turn=0)
    assert result.tool_name == "read_file"
    assert result.tool_input == {"path": "calc.py"}


def test_parse_qwen_raw_json_fallback():
    """Step 2: finish_reason=stop + JSON content → ToolCall recovered."""
    content = '{"name": "read_file", "arguments": {"path": "x.py"}}'
    msg = SimpleNamespace(tool_calls=None, content=content)
    result = _parse_response(msg, turn=0)
    assert result.tool_name == "read_file"
    assert result.tool_input == {"path": "x.py"}


def test_parse_qwen_fenced_json_fallback():
    """Step 2: JSON wrapped in ```json fences → recovered."""
    content = '```json\n{"name": "run_tests", "arguments": {"path": "."}}\n```'
    msg = SimpleNamespace(tool_calls=None, content=content)
    result = _parse_response(msg, turn=0)
    assert result.tool_name == "run_tests"


def test_parse_partial_json_regex():
    """Step 3: partial JSON via regex → ToolCall recovered."""
    content = 'here is the call: {"name": "edit_file", "arguments": {"path": "x.py", "old": "a", "new": "b"}}'
    msg = SimpleNamespace(tool_calls=None, content=content)
    result = _parse_response(msg, turn=0)
    assert result.tool_name == "edit_file"


def test_parse_turn0_pure_text_raises():
    """Step 4: turn=0, all fallbacks fail → NoToolCallError raised."""
    msg = SimpleNamespace(tool_calls=None, content="The bug is on line 13.")
    with pytest.raises(NoToolCallError) as exc_info:
        _parse_response(msg, turn=0)
    assert "line 13" in exc_info.value.text


def test_parse_turn1_pure_text_returns_task_done():
    """Step 5: turn>=1, all fallbacks fail → task_done ToolCall."""
    msg = SimpleNamespace(tool_calls=None, content="All done now.")
    result = _parse_response(msg, turn=1)
    assert result.tool_name == "task_done"
    assert "All done" in result.tool_input["summary"]


# ── OllamaClient.reason integration tests ───────────────────────────────────

@pytest.mark.asyncio
async def test_reason_happy_path():
    """Structured tool_calls in response → ToolCall returned."""
    cfg = _make_config()
    client = OllamaClient(cfg)

    mock_resp = MagicMock()
    tc = SimpleNamespace(function=SimpleNamespace(name="read_file", arguments={"path": "calc.py"}))
    mock_resp.message = SimpleNamespace(tool_calls=[tc], content="")

    with patch.object(client._client, "chat", new=AsyncMock(return_value=mock_resp)):
        result = await client.reason([_user_message()], [_tool_spec()], turn=0)

    assert result.tool_name == "read_file"


@pytest.mark.asyncio
async def test_reason_timeout():
    """Timeout → LLMTimeoutError."""
    import asyncio
    cfg = _make_config(timeout=1)
    client = OllamaClient(cfg)

    async def _slow(*args, **kwargs):
        await asyncio.sleep(10)

    with patch.object(client._client, "chat", new=_slow):
        with pytest.raises(LLMTimeoutError):
            await client.reason([_user_message()], [_tool_spec()], turn=0)


def test_system_prefix_in_payload():
    """build_system() prefix must appear in messages sent to Ollama."""
    from agentx.llm.ollama_client import _to_ollama_messages
    from agentx.llm.base import SYSTEM_PREFIX

    msgs = _to_ollama_messages([_user_message()], system="extra context")
    assert msgs[0]["role"] == "system"
    assert SYSTEM_PREFIX in msgs[0]["content"]
    assert "extra context" in msgs[0]["content"]
