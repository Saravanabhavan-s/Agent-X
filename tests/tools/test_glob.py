from __future__ import annotations

from pathlib import Path

import pytest

from agentx.tools.glob_tool import GlobArgs, GlobTool
from agentx.tools.base import ToolContext


@pytest.fixture()
def ws(tmp_path: Path) -> tuple[Path, ToolContext]:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# main\n")
    (tmp_path / "src" / "util.py").write_text("# util\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("# test\n")
    (tmp_path / "README.md").write_text("# readme\n")
    ctx = ToolContext(workspace=str(tmp_path), session_id="test")
    return tmp_path, ctx


@pytest.mark.asyncio
async def test_glob_pattern_match(ws):
    _, ctx = ws
    tool = GlobTool()
    result = await tool.run(GlobArgs(pattern="**/*.py"), ctx)
    assert result.ok
    assert len(result.data["paths"]) == 3
    assert all(p.endswith(".py") for p in result.data["paths"])


@pytest.mark.asyncio
async def test_glob_empty_result(ws):
    _, ctx = ws
    tool = GlobTool()
    result = await tool.run(GlobArgs(pattern="**/*.rs"), ctx)
    assert result.ok
    assert result.data["paths"] == []
    assert "No files matched" in result.observation


@pytest.mark.asyncio
async def test_glob_scoped_to_subdir(ws):
    _, ctx = ws
    tool = GlobTool()
    result = await tool.run(GlobArgs(pattern="*.py", path="src"), ctx)
    assert result.ok
    assert all("src" in p for p in result.data["paths"])


@pytest.mark.asyncio
async def test_glob_path_traversal_rejected(ws):
    _, ctx = ws
    tool = GlobTool()
    result = await tool.run(GlobArgs(pattern="*.py", path="../../etc"), ctx)
    assert not result.ok


@pytest.mark.asyncio
async def test_glob_max_results_respected(ws):
    tmp_path, ctx = ws
    # Create 10 extra files
    for i in range(10):
        (tmp_path / f"f{i}.py").write_text(f"# {i}\n")
    tool = GlobTool()
    result = await tool.run(GlobArgs(pattern="**/*.py", max_results=5), ctx)
    assert result.ok
    assert len(result.data["paths"]) <= 5
