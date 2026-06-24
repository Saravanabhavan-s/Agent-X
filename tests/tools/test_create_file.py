from __future__ import annotations

from pathlib import Path

import pytest

from agentx.tools.create_file import CreateFileArgs, CreateFileTool
from agentx.tools.base import ToolContext


@pytest.fixture()
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace=str(tmp_path), session_id="test")


@pytest.mark.asyncio
async def test_creates_file(ctx, tmp_path):
    tool = CreateFileTool()
    result = await tool.run(CreateFileArgs(path="new.py", content="print('hi')\n"), ctx)
    assert result.ok
    assert (tmp_path / "new.py").read_text() == "print('hi')\n"
    assert "new.py" in result.artifacts


@pytest.mark.asyncio
async def test_creates_nested_file(ctx, tmp_path):
    tool = CreateFileTool()
    result = await tool.run(CreateFileArgs(path="src/lib/new.py", content="x = 1\n"), ctx)
    assert result.ok
    assert (tmp_path / "src" / "lib" / "new.py").exists()


@pytest.mark.asyncio
async def test_refuses_overwrite(ctx, tmp_path):
    (tmp_path / "existing.py").write_text("original\n")
    tool = CreateFileTool()
    result = await tool.run(CreateFileArgs(path="existing.py", content="new content"), ctx)
    assert not result.ok
    assert "already exists" in result.observation
    # Original unchanged
    assert (tmp_path / "existing.py").read_text() == "original\n"


@pytest.mark.asyncio
async def test_rejects_path_outside_workspace(ctx):
    tool = CreateFileTool()
    result = await tool.run(CreateFileArgs(path="../../outside.py", content="x"), ctx)
    assert not result.ok
    assert "escapes workspace" in result.observation
