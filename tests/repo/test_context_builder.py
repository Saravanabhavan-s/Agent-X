from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agentx.repo.context_builder import RepoContextBuilder
from agentx.repo.models import RepoClassification, RepoType


def _cls(entry_points: list[str] | None = None) -> RepoClassification:
    return RepoClassification(
        repo_type=RepoType.ACTIVE,
        primary_language="python",
        secondary_languages=[],
        frameworks=["FastAPI"],
        has_tests=True,
        has_ci=False,
        has_docs=True,
        has_docker=False,
        entry_points=entry_points or [],
        package_manager="pip",
        test_runner="pytest",
        last_commit_days_ago=3,
        open_issues_hint=[],
        confidence=0.9,
    )


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def builder():
    return RepoContextBuilder()


# ── File tree respects depth limit ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_file_tree_depth_limit(tmp_path, builder):
    # Create depth-5 structure
    deep = tmp_path / "a" / "b" / "c" / "d" / "e"
    deep.mkdir(parents=True)
    (deep / "deep_file.py").write_text("x", encoding="utf-8")
    _write(tmp_path / "main.py", "x")

    with patch.object(builder, "_git_log", return_value=""):
        ctx = await builder.build(str(tmp_path), _cls(), {})

    # depth-5 file should not appear in tree
    assert "deep_file.py" not in ctx.file_tree
    assert "main.py" in ctx.file_tree


# ── node_modules skipped in tree ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_node_modules_not_in_tree(tmp_path, builder):
    _write(tmp_path / "src/index.js", "")
    _write(tmp_path / "node_modules/react/index.js", "")

    with patch.object(builder, "_git_log", return_value=""):
        ctx = await builder.build(str(tmp_path), _cls(), {})

    # node_modules dir should not appear as an entry in the tree
    # (the tmp_path folder name may contain the string, so check for the dir entry)
    tree_lines = ctx.file_tree.splitlines()
    assert not any(line.strip() == "node_modules/" for line in tree_lines)


# ── Key files truncated at 200 lines ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_key_files_truncated_200_lines(tmp_path, builder):
    content_300 = "\n".join(f"line {i}" for i in range(300))
    _write(tmp_path / "README.md", content_300)

    with patch.object(builder, "_git_log", return_value=""):
        ctx = await builder.build(str(tmp_path), _cls(), {})

    readme = ctx.key_files.get("README.md", "")
    assert readme.count("\n") <= 200


# ── Total key_files budget ~4000 tokens ──────────────────────────────────────

@pytest.mark.asyncio
async def test_key_files_budget_enforced(tmp_path, builder):
    # Write files that together exceed 4000 tokens (~16000 chars)
    for i in range(5):
        big_content = "x" * 4000
        _write(tmp_path / f"file_{i}.txt", big_content)
    # Make them candidates by writing a pyproject
    _write(tmp_path / "pyproject.toml", "[project]\n")

    with patch.object(builder, "_git_log", return_value=""):
        ctx = await builder.build(str(tmp_path), _cls(), {})

    total_chars = sum(len(v) for v in ctx.key_files.values())
    assert total_chars <= 16000 + 100  # small tolerance for last file edge


# ── RepoContext is JSON-serializable ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_repo_context_json_serializable(tmp_path, builder):
    _write(tmp_path / "README.md", "# Test\n")
    _write(tmp_path / "pyproject.toml", '[project]\ndependencies = ["pytest"]\n')

    with patch.object(builder, "_git_log", return_value="abc1234 initial commit"):
        ctx = await builder.build(str(tmp_path), _cls(), {"build_errors": [], "test_results": None})

    d = ctx.to_dict()
    json_str = json.dumps(d)  # must not raise
    assert '"python"' in json_str
    assert "active" in json_str


# ── Git log summary included ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_git_log_summary(tmp_path, builder):
    with patch.object(builder, "_git_log", return_value="abc1234 add feature\ndef5678 init"):
        ctx = await builder.build(str(tmp_path), _cls(), {})

    assert "abc1234" in ctx.git_log_summary


# ── Entry points from classification included in key_files ───────────────────

@pytest.mark.asyncio
async def test_entry_points_in_key_files(tmp_path, builder):
    _write(tmp_path / "app/main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    cls = _cls(entry_points=["app/main.py"])

    with patch.object(builder, "_git_log", return_value=""):
        ctx = await builder.build(str(tmp_path), cls, {})

    assert "app/main.py" in ctx.key_files


# ── build_errors threaded from health ────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_errors_from_health(tmp_path, builder):
    health = {"build_errors": ["ImportError: no module named foo"], "test_results": None}

    with patch.object(builder, "_git_log", return_value=""):
        ctx = await builder.build(str(tmp_path), _cls(), health)

    assert "ImportError: no module named foo" in ctx.build_errors
