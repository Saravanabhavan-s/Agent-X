from __future__ import annotations

import time
from pathlib import Path

import pytest

from agentx.intelligence.symbol_index import SymbolIndexer


class _FakeClassification:
    primary_language = "python"
    entry_points: list[str] = []


def _make_repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "def main():\n    pass\n\nclass App:\n    pass\n"
    )
    (tmp_path / "src" / "utils.py").write_text(
        "def helper(x):\n    return x\n"
    )
    (tmp_path / "README.md").write_text("# Hello\n")
    return tmp_path


def test_build_finds_symbols(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    indexer = SymbolIndexer(str(tmp_path), _FakeClassification())
    idx = indexer.build()
    names = {s.name for s in idx.symbols}
    assert "main" in names
    assert "App" in names
    assert "helper" in names


def test_build_completes_quickly(tmp_path: Path) -> None:
    # Create 50 small Python files — well under 200-file limit
    for i in range(50):
        (tmp_path / f"mod_{i}.py").write_text(f"def func_{i}(): pass\n")
    indexer = SymbolIndexer(str(tmp_path), _FakeClassification())
    start = time.time()
    idx = indexer.build()
    elapsed = time.time() - start
    assert elapsed < 30.0
    assert len(idx.symbols) >= 50


def test_skips_git_and_pycache(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "hooks.py").write_text("def git_hook(): pass\n")
    pycache = tmp_path / "src" / "__pycache__"
    pycache.mkdir()
    (pycache / "main.cpython-311.py").write_text("def cached(): pass\n")

    indexer = SymbolIndexer(str(tmp_path), _FakeClassification())
    idx = indexer.build()
    paths = {s.file_path for s in idx.symbols}
    assert not any(".git" in p for p in paths)
    assert not any("__pycache__" in p for p in paths)


def test_build_for_file(tmp_path: Path) -> None:
    f = tmp_path / "single.py"
    f.write_text("def only_func():\n    pass\n")
    indexer = SymbolIndexer(str(tmp_path), _FakeClassification())
    syms, imps = indexer.build_for_file(str(f))
    assert any(s.name == "only_func" for s in syms)


def test_incremental_update_fast(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    indexer = SymbolIndexer(str(tmp_path), _FakeClassification())
    idx = indexer.build()

    # Edit a file
    target = str(tmp_path / "src" / "utils.py")
    Path(target).write_text("def new_helper(x):\n    return x * 2\n")

    start = time.time()
    indexer.update_file(idx, "src/utils.py")
    elapsed = time.time() - start
    assert elapsed < 1.0

    names = {s.name for s in idx.symbols}
    assert "new_helper" in names
    assert "helper" not in names


def test_update_file_removes_old_symbols(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    indexer = SymbolIndexer(str(tmp_path), _FakeClassification())
    idx = indexer.build()
    assert any(s.name == "helper" for s in idx.symbols)

    Path(tmp_path / "src" / "utils.py").write_text("# empty now\n")
    indexer.update_file(idx, "src/utils.py")
    assert not any(s.name == "helper" for s in idx.symbols)
