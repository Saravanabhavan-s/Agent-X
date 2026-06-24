from __future__ import annotations

from pathlib import Path

import pytest

from agentx.tools.bash import BashArgs, BashTool
from agentx.tools.base import ToolContext
from agentx.runtime.sandbox import LocalSandbox


@pytest.fixture()
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace=str(tmp_path), session_id="test", sandbox=LocalSandbox())


@pytest.mark.asyncio
async def test_success_command(ctx):
    tool = BashTool()
    result = await tool.run(BashArgs(command='python -c "print(42)"'), ctx)
    assert result.ok
    assert "42" in result.observation


@pytest.mark.asyncio
async def test_nonzero_exit_captured_not_raised(ctx):
    tool = BashTool()
    result = await tool.run(BashArgs(command="python -c \"import sys; sys.exit(2)\""), ctx)
    assert not result.ok
    assert result.data["returncode"] == 2
    # No exception raised


@pytest.mark.asyncio
async def test_stderr_captured(ctx):
    tool = BashTool()
    result = await tool.run(BashArgs(command='python -c "import sys; sys.stderr.write(\'err\\n\')"'), ctx)
    assert "err" in result.observation


@pytest.mark.asyncio
async def test_timeout_raises_tool_error(ctx):
    tool = BashTool()
    result = await tool.run(BashArgs(command='python -c "import time; time.sleep(60)"', timeout=2.0), ctx)
    assert not result.ok
    assert "timed out" in result.observation.lower()


@pytest.mark.asyncio
async def test_blocked_rm_rf_root(ctx):
    tool = BashTool()
    result = await tool.run(BashArgs(command="rm -rf /"), ctx)
    assert not result.ok
    assert "blocked" in result.observation.lower()


@pytest.mark.asyncio
async def test_blocked_fork_bomb(ctx):
    tool = BashTool()
    result = await tool.run(BashArgs(command=":(){ :|:& };:"), ctx)
    assert not result.ok
    assert "blocked" in result.observation.lower()


@pytest.mark.asyncio
async def test_blocked_mkfs(ctx):
    tool = BashTool()
    result = await tool.run(BashArgs(command="mkfs /dev/sda1"), ctx)
    assert not result.ok
    assert "blocked" in result.observation.lower()


@pytest.mark.asyncio
async def test_no_sandbox_returns_error():
    ctx_no_sandbox = ToolContext(workspace="/tmp", session_id="test", sandbox=None)
    tool = BashTool()
    result = await tool.run(BashArgs(command="echo hi"), ctx_no_sandbox)
    assert not result.ok
    assert "sandbox" in result.observation.lower()
