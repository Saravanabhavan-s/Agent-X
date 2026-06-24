from __future__ import annotations

from pathlib import Path

import pytest

from agentx.runtime.patch import PatchBlock, apply_patch, rollback_patch


@pytest.fixture()
def ws(tmp_path: Path) -> str:
    (tmp_path / "foo.py").write_text("def hello():\n    return 'world'\n")
    return str(tmp_path)


def test_apply_basic(ws: str) -> None:
    blocks = [PatchBlock(path="foo.py", old="    return 'world'\n", new="    return 'earth'\n")]
    result = apply_patch(blocks, ws)
    assert result.ok
    assert "earth" in result.diff
    assert (Path(ws) / "foo.py").read_text() == "def hello():\n    return 'earth'\n"


def test_apply_old_not_found(ws: str) -> None:
    blocks = [PatchBlock(path="foo.py", old="DOES_NOT_EXIST", new="new")]
    result = apply_patch(blocks, ws)
    assert not result.ok
    assert "not found" in result.error.lower()


def test_apply_file_not_found(ws: str) -> None:
    blocks = [PatchBlock(path="missing.py", old="x", new="y")]
    result = apply_patch(blocks, ws)
    assert not result.ok
    assert "not found" in result.error.lower()


def test_apply_multiple_blocks(ws: str) -> None:
    (Path(ws) / "bar.py").write_text("X = 1\nY = 2\n")
    blocks = [
        PatchBlock(path="foo.py", old="return 'world'", new="return 'mars'"),
        PatchBlock(path="bar.py", old="X = 1", new="X = 99"),
    ]
    result = apply_patch(blocks, ws)
    assert result.ok
    assert "mars" in (Path(ws) / "foo.py").read_text()
    assert "X = 99" in (Path(ws) / "bar.py").read_text()


def test_rollback(ws: str) -> None:
    # Manually create a .bak file (as apply_patch would have done)
    orig = Path(ws) / "foo.py"
    bak = orig.with_suffix(".py.bak")
    bak.write_text("ORIGINAL CONTENT\n")
    orig.write_text("MODIFIED CONTENT\n")

    result = rollback_patch(ws, ["foo.py"])
    assert result.ok
    assert "ORIGINAL CONTENT" in orig.read_text()
    assert not bak.exists()


def test_rollback_no_bak(ws: str) -> None:
    result = rollback_patch(ws, ["foo.py"])
    assert not result.ok


def test_diff_format(ws: str) -> None:
    blocks = [PatchBlock(path="foo.py", old="return 'world'", new="return 'diff'")]
    result = apply_patch(blocks, ws)
    assert result.ok
    assert "--- a/foo.py" in result.diff
    assert "+++ b/foo.py" in result.diff
