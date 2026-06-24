from __future__ import annotations

import pytest

from agentx.llm.base import NoToolCallError, SessionError
from agentx.llm.fake import FakeModelClient
from agentx.llm.types import ToolCall
from agentx.loop.engine import run_loop
from agentx.loop.state import LoopStatus

import agentx.tools.edit_file   # noqa: F401 — registration
import agentx.tools.read_file   # noqa: F401
import agentx.tools.run_tests   # noqa: F401


class _NoToolClient:
    """Always raises NoToolCallError."""

    def __init__(self, text: str = "I know the answer."):
        self._text = text
        self.call_count = 0

    async def reason(self, messages, tools, *, system="", turn=0):
        self.call_count += 1
        raise NoToolCallError(self._text)

    async def stream(self, messages, tools, *, system="", turn=0):
        raise NotImplementedError


class _EventualClient:
    """Raises NoToolCallError twice, then returns a task_done ToolCall."""

    def __init__(self):
        self.call_count = 0

    async def reason(self, messages, tools, *, system="", turn=0):
        self.call_count += 1
        if self.call_count < 3:
            raise NoToolCallError("not yet")
        return ToolCall(tool_name="task_done", tool_input={"summary": "ok"}, call_id="done")

    async def stream(self, messages, tools, *, system="", turn=0):
        raise NotImplementedError


import shutil
from pathlib import Path


@pytest.fixture()
def toy_ws(tmp_path: Path) -> str:
    src = Path(__file__).parent.parent.parent / "toy_repo"
    dst = tmp_path / "toy_repo"
    shutil.copytree(src, dst)
    return str(dst)


@pytest.mark.asyncio
async def test_notoolcallerror_injects_correction(toy_ws):
    """turn-0 NoToolCallError → correction injected in state.error_log → loop continues."""
    client = _EventualClient()
    loop = await run_loop(
        goal="test goal",
        workspace=toy_ws,
        model=client,
        max_turns=10,
    )
    states = [s async for s in loop]
    final = states[-1]
    # Eventually succeeds after retries
    assert final.status == LoopStatus.DONE
    # Client was called at least 3 times (2 failures + 1 success)
    assert client.call_count >= 3


@pytest.mark.asyncio
async def test_notoolcallerror_three_times_raises_session_error(toy_ws):
    """3 consecutive NoToolCallError → SessionError raised."""
    client = _NoToolClient()
    loop = await run_loop(
        goal="test goal",
        workspace=toy_ws,
        model=client,
        max_turns=20,
    )
    with pytest.raises(SessionError, match="refused to use tools"):
        _ = [s async for s in loop]


@pytest.mark.asyncio
async def test_retry_counter_resets_after_success(toy_ws):
    """Counter resets: 2 failures, 1 success, then 2 more failures → no session error yet."""

    class _CountingClient:
        def __init__(self):
            self.call_count = 0

        async def reason(self, messages, tools, *, system="", turn=0):
            self.call_count += 1
            # Pattern: fail, fail, succeed (task_done), fail, fail, succeed (task_done)
            # Each group of 3 forms one "attempt cycle"
            cycle = (self.call_count - 1) % 3
            if cycle < 2:
                raise NoToolCallError("not yet")
            return ToolCall(tool_name="task_done", tool_input={"summary": "ok"}, call_id="d")

        async def stream(self, messages, tools, *, system="", turn=0):
            raise NotImplementedError

    client = _CountingClient()
    loop = await run_loop(
        goal="test goal",
        workspace=toy_ws,
        model=client,
        max_turns=20,
    )
    states = [s async for s in loop]
    final = states[-1]
    assert final.status == LoopStatus.DONE
