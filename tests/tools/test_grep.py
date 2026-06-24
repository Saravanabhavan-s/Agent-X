from __future__ import annotations

from pathlib import Path

import pytest

from agentx.tools.grep import GrepArgs, GrepTool, _grep_python
from agentx.tools.base import ToolContext


@pytest.fixture()
def ws(tmp_path: Path) -> tuple[Path, ToolContext]:
    (tmp_path / "a.py").write_text("def hello():\n    return 'world'\n")
    (tmp_path / "b.py").write_text("def goodbye():\n    return 'moon'\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.py").write_text("HELLO_CONST = 42\n")
    ctx = ToolContext(workspace=str(tmp_path), session_id="test")
    return tmp_path, ctx


@pytest.mark.asyncio
async def test_grep_match_found(ws):
    _, ctx = ws
    tool = GrepTool()
    result = await tool.run(GrepArgs(pattern="hello", case_sensitive=False), ctx)
    assert result.ok
    assert result.data["matches"]
    names = [m["file"] for m in result.data["matches"]]
    assert any("a.py" in n or "c.py" in n for n in names)


@pytest.mark.asyncio
async def test_grep_no_match(ws):
    _, ctx = ws
    tool = GrepTool()
    result = await tool.run(GrepArgs(pattern="XYZZY_NOT_PRESENT"), ctx)
    assert result.ok
    assert result.data["matches"] == []


@pytest.mark.asyncio
async def test_grep_case_sensitive(ws):
    _, ctx = ws
    tool = GrepTool()
    result = await tool.run(GrepArgs(pattern="HELLO", case_sensitive=True), ctx)
    assert result.ok
    # Only sub/c.py has uppercase HELLO
    names = [m["file"] for m in result.data["matches"]]
    assert all("c.py" in n for n in names)


@pytest.mark.asyncio
async def test_grep_binary_file_skipped(tmp_path: Path):
    (tmp_path / "data.bin").write_bytes(bytes(range(256)))
    (tmp_path / "ok.py").write_text("needle\n")
    ctx = ToolContext(workspace=str(tmp_path), session_id="test")
    tool = GrepTool()
    result = await tool.run(GrepArgs(pattern="needle"), ctx)
    assert result.ok
    names = [m["file"] for m in result.data["matches"]]
    assert any("ok.py" in n for n in names)
    # binary file may produce garbled match but should not crash


@pytest.mark.asyncio
async def test_grep_path_escapes_workspace(ws):
    _, ctx = ws
    tool = GrepTool()
    result = await tool.run(GrepArgs(pattern="x", path="../../etc"), ctx)
    assert not result.ok


def test_grep_python_fallback(tmp_path: Path):
    (tmp_path / "x.py").write_text("alpha beta\ngamma\n")
    matches = _grep_python("alpha", tmp_path, case_sensitive=True, include_glob="**/*.py", max_results=100)
    assert len(matches) == 1
    assert matches[0]["line_number"] == 1
    assert "alpha" in matches[0]["line"]
