from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agentx.llm.anthropic_client import AnthropicClient, _to_anthropic_messages, _to_anthropic_tools
from agentx.llm.base import LLMTimeoutError, NoToolCallError, SYSTEM_PREFIX
from agentx.llm.types import LLMConfig, Message, Role, ToolSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(**kwargs) -> LLMConfig:
    defaults = dict(provider="anthropic", model="claude-opus-4-8", api_key="sk-ant-test", timeout=30)
    defaults.update(kwargs)
    return LLMConfig(**defaults)


def _tool_spec() -> ToolSpec:
    return ToolSpec(
        name="read_file",
        description="Read a file",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    )


def _user_msg(text: str = "Fix the bug") -> Message:
    return Message(role=Role.USER, content=text)


def _make_tool_response(name: str = "read_file", input_data: dict | None = None, call_id: str = "toolu_01"):
    block = SimpleNamespace(type="tool_use", name=name, input=input_data or {"path": "calc.py"}, id=call_id)
    return SimpleNamespace(content=[block])


def _make_text_response(text: str = "The bug is on line 13."):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


class _FakeStream:
    """Minimal async context manager + async iterator for mocking messages.stream()."""

    def __init__(self, events=None, final_content=None):
        self._events = events or []
        self._final_content = final_content or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for e in self._events:
            yield e

    async def get_final_message(self):
        return SimpleNamespace(content=self._final_content)


# ---------------------------------------------------------------------------
# _to_anthropic_messages
# ---------------------------------------------------------------------------

def test_system_messages_skipped():
    msgs = [
        Message(role=Role.SYSTEM, content="sys context"),
        Message(role=Role.USER, content="user query"),
    ]
    result = _to_anthropic_messages(msgs)
    assert all(m["role"] != "system" for m in result)
    assert result[0]["content"] == "user query"


def test_tool_result_message_format():
    msg = Message(role=Role.TOOL_RESULT, content="ok", tool_call_id="tc123", tool_name="read_file")
    result = _to_anthropic_messages([msg])
    assert result[0]["role"] == "user"
    block = result[0]["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "tc123"


def test_to_anthropic_tools_shape():
    result = _to_anthropic_tools([_tool_spec()])
    assert result[0]["name"] == "read_file"
    assert "input_schema" in result[0]
    assert "description" in result[0]


# ---------------------------------------------------------------------------
# AnthropicClient.reason
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reason_returns_tool_call():
    client = AnthropicClient(_cfg())
    mock_resp = _make_tool_response("read_file", {"path": "calc.py"}, "toolu_01")
    with patch.object(client._client.messages, "create", new=AsyncMock(return_value=mock_resp)):
        result = await client.reason([_user_msg()], [_tool_spec()], turn=0)
    assert result.tool_name == "read_file"
    assert result.tool_input == {"path": "calc.py"}
    assert result.call_id == "toolu_01"


@pytest.mark.asyncio
async def test_reason_tool_choice_auto_forwarded():
    """tool_choice={"type":"auto"} must be forwarded to SDK call."""
    client = AnthropicClient(_cfg())
    create_mock = AsyncMock(return_value=_make_tool_response())
    with patch.object(client._client.messages, "create", new=create_mock):
        await client.reason([_user_msg()], [_tool_spec()], turn=0)
    kwargs = create_mock.call_args.kwargs
    assert kwargs.get("tool_choice") == {"type": "auto"}


@pytest.mark.asyncio
async def test_reason_system_prefix_injected():
    """SYSTEM_PREFIX must appear in system= kwarg sent to SDK."""
    client = AnthropicClient(_cfg())
    create_mock = AsyncMock(return_value=_make_tool_response())
    with patch.object(client._client.messages, "create", new=create_mock):
        await client.reason([_user_msg()], [_tool_spec()], system="extra ctx", turn=0)
    system_arg = create_mock.call_args.kwargs.get("system", "")
    assert SYSTEM_PREFIX in system_arg
    assert "extra ctx" in system_arg


@pytest.mark.asyncio
async def test_reason_pure_text_turn0_raises_notoolcall():
    """Turn 0 bare text → NoToolCallError."""
    client = AnthropicClient(_cfg())
    with patch.object(client._client.messages, "create", new=AsyncMock(return_value=_make_text_response("line 13"))):
        with pytest.raises(NoToolCallError) as exc_info:
            await client.reason([_user_msg()], [_tool_spec()], turn=0)
    assert "line 13" in exc_info.value.text


@pytest.mark.asyncio
async def test_reason_pure_text_turn1_returns_task_done():
    """Turn >= 1 bare text → task_done ToolCall."""
    client = AnthropicClient(_cfg())
    with patch.object(client._client.messages, "create", new=AsyncMock(return_value=_make_text_response("All done."))):
        result = await client.reason([_user_msg()], [_tool_spec()], turn=1)
    assert result.tool_name == "task_done"
    assert "All done" in result.tool_input["summary"]


@pytest.mark.asyncio
async def test_reason_timeout_raises():
    import asyncio
    client = AnthropicClient(_cfg(timeout=1))

    async def _slow(*_, **__):
        await asyncio.sleep(10)

    with patch.object(client._client.messages, "create", new=_slow):
        with pytest.raises(LLMTimeoutError):
            await client.reason([_user_msg()], [_tool_spec()], turn=0)


# ---------------------------------------------------------------------------
# AnthropicClient.stream
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_yields_tool_call_and_done():
    """stream() yields tool_call event then done event."""
    client = AnthropicClient(_cfg())
    tool_block = SimpleNamespace(type="tool_use", name="read_file", input={"path": "c.py"}, id="toolu_02")
    fake_stream = _FakeStream(final_content=[tool_block])

    with patch.object(client._client.messages, "stream", return_value=fake_stream):
        gen = await client.stream([_user_msg()], [_tool_spec()], turn=0)
        events = [e async for e in gen]

    event_types = [e.event_type for e in events]
    assert "tool_call" in event_types
    assert "done" in event_types

    tc = next(e.data for e in events if e.event_type == "tool_call")
    assert tc.tool_name == "read_file"
    assert tc.call_id == "toolu_02"


@pytest.mark.asyncio
async def test_stream_text_delta_forwarded():
    """Text delta events are forwarded as text_delta StreamEvents."""
    client = AnthropicClient(_cfg())

    class _TextDelta:
        type = "content_block_delta"
        delta = SimpleNamespace(type="text_delta", text="thinking...")

    tool_block = SimpleNamespace(type="tool_use", name="read_file", input={}, id="toolu_03")
    fake_stream = _FakeStream(events=[_TextDelta()], final_content=[tool_block])

    with patch.object(client._client.messages, "stream", return_value=fake_stream):
        gen = await client.stream([_user_msg()], [_tool_spec()], turn=0)
        events = [e async for e in gen]

    text_events = [e for e in events if e.event_type == "text_delta"]
    assert any("thinking" in (e.data or "") for e in text_events)


@pytest.mark.asyncio
async def test_stream_no_tool_turn0_raises_notoolcall():
    """Stream with no tool block on turn=0 → NoToolCallError."""
    client = AnthropicClient(_cfg())
    text_block = SimpleNamespace(type="text", text="plain answer")
    fake_stream = _FakeStream(final_content=[text_block])

    with patch.object(client._client.messages, "stream", return_value=fake_stream):
        with pytest.raises(NoToolCallError):
            gen = await client.stream([_user_msg()], [_tool_spec()], turn=0)
            async for _ in gen:
                pass


@pytest.mark.asyncio
async def test_stream_no_tool_turn1_returns_task_done():
    """Stream with no tool block on turn>=1 → task_done event."""
    client = AnthropicClient(_cfg())
    text_block = SimpleNamespace(type="text", text="All done.")
    fake_stream = _FakeStream(final_content=[text_block])

    with patch.object(client._client.messages, "stream", return_value=fake_stream):
        gen = await client.stream([_user_msg()], [_tool_spec()], turn=1)
        events = [e async for e in gen]

    tc = next((e.data for e in events if e.event_type == "tool_call"), None)
    assert tc is not None
    assert tc.tool_name == "task_done"
