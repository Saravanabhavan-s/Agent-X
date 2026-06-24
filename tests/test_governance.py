from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentx.governance.audit import AuditEntry, AuditWriter, InMemoryAuditWriter
from agentx.llm.fake import FakeModelClient
from agentx.llm.types import ToolCall
from agentx.loop.engine import run_loop
from agentx.loop.state import LoopStatus

import agentx.tools.edit_file  # noqa: F401
import agentx.tools.read_file  # noqa: F401
import agentx.tools.run_tests  # noqa: F401


# ---------------------------------------------------------------------------
# InMemoryAuditWriter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_in_memory_audit_writer_stores_entry():
    writer = InMemoryAuditWriter()
    entry = AuditEntry(session_id="s1", event_type="tool_execution", tool_name="read_file")
    await writer.write(entry)
    assert len(writer.entries) == 1
    assert writer.entries[0].tool_name == "read_file"


@pytest.mark.asyncio
async def test_in_memory_audit_writer_multiple_entries():
    writer = InMemoryAuditWriter()
    for i in range(5):
        await writer.write(AuditEntry(session_id="s1", event_type=f"event_{i}"))
    assert len(writer.entries) == 5


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

def test_audit_entry_truncation_enforced():
    from agentx.governance.audit import _trunc, _MAX_SUMMARY
    long_text = "x" * 1000
    result = _trunc(long_text)
    assert len(result) == _MAX_SUMMARY


def test_audit_entry_short_text_unchanged():
    from agentx.governance.audit import _trunc
    assert _trunc("hello") == "hello"


# ---------------------------------------------------------------------------
# AuditWriter failure does not raise
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_writer_failure_does_not_raise():
    """When the underlying DB write fails, write() must not propagate the exception."""

    class _BrokenFactory:
        def __call__(self):
            raise RuntimeError("DB is down")

    class _ContextFactory:
        def __call__(self):
            return _BrokenContext()

    class _BrokenContext:
        async def __aenter__(self):
            raise RuntimeError("DB is down")

        async def __aexit__(self, *_):
            pass

    writer = AuditWriter(_ContextFactory())
    entry = AuditEntry(session_id="s1", event_type="tool_execution")
    # Must not raise
    await writer.write(entry)


# ---------------------------------------------------------------------------
# Loop emits audit events (via InMemoryAuditWriter)
# ---------------------------------------------------------------------------

@pytest.fixture()
def toy_ws(tmp_path: Path) -> str:
    src = Path(__file__).parent.parent / "toy_repo"
    dst = tmp_path / "toy_repo"
    shutil.copytree(src, dst)
    return str(dst)


@pytest.mark.asyncio
async def test_loop_emits_audit_events(toy_ws):
    """Engine must emit audit events for model response and tool execution."""
    audit = InMemoryAuditWriter()
    model = FakeModelClient([
        ToolCall(tool_name="read_file", tool_input={"path": "src/calculator/__init__.py"}, call_id="r0"),
        ToolCall(tool_name="task_done", tool_input={"summary": "done"}, call_id="d0"),
    ])
    loop = await run_loop(
        goal="test",
        workspace=toy_ws,
        model=model,
        audit=audit,
        max_turns=5,
    )
    states = [s async for s in loop]
    assert states[-1].status == LoopStatus.DONE
    # At least one model_response and one tool_execution event
    types = [e.event_type for e in audit.entries]
    assert "model_response" in types
    assert "tool_execution" in types


@pytest.mark.asyncio
async def test_audit_failure_does_not_crash_loop(toy_ws):
    """Even if audit.write raises, the loop must continue normally."""

    class _FailingAudit:
        async def write(self, entry):
            raise RuntimeError("audit exploded")

    model = FakeModelClient([
        ToolCall(tool_name="task_done", tool_input={"summary": "done"}, call_id="d0"),
    ])
    loop = await run_loop(
        goal="test",
        workspace=toy_ws,
        model=model,
        audit=_FailingAudit(),
        max_turns=5,
    )
    states = [s async for s in loop]
    # Loop completes despite audit failures
    assert states[-1].status == LoopStatus.DONE


@pytest.mark.asyncio
async def test_audit_tool_name_recorded(toy_ws):
    """tool_name in audit entry matches actual tool called."""
    audit = InMemoryAuditWriter()
    model = FakeModelClient([
        ToolCall(tool_name="read_file", tool_input={"path": "src/calculator/__init__.py"}, call_id="r0"),
        ToolCall(tool_name="task_done", tool_input={"summary": "ok"}, call_id="d0"),
    ])
    loop = await run_loop(goal="test", workspace=toy_ws, model=model, audit=audit, max_turns=5)
    _ = [s async for s in loop]
    tool_exec_entries = [e for e in audit.entries if e.event_type == "tool_execution"]
    assert any(e.tool_name == "read_file" for e in tool_exec_entries)
