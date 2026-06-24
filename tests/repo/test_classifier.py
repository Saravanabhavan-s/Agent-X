from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from agentx.repo.classifier import RepositoryClassifier
from agentx.repo.models import RepoType


@pytest.fixture
def cls():
    return RepositoryClassifier()


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ── Greenfield: empty dir ─────────────────────────────────────────────────────

def test_greenfield_empty_dir(tmp_path, cls):
    with patch.object(cls, "_last_commit_days", return_value=None):
        result = cls.classify(str(tmp_path))
    assert result.repo_type == RepoType.GREENFIELD
    assert result.primary_language == "unknown"


# ── Python FastAPI repo ───────────────────────────────────────────────────────

def test_python_fastapi(tmp_path, cls):
    _write(tmp_path / "pyproject.toml", '[project]\ndependencies = ["fastapi", "pytest"]\n')
    for i in range(10):
        _write(tmp_path / f"src/module_{i}.py", f"# module {i}")
    _write(tmp_path / "src/main.py", "from fastapi import FastAPI\napp = FastAPI()")

    with patch.object(cls, "_last_commit_days", return_value=5):
        result = cls.classify(str(tmp_path))

    assert result.primary_language == "python"
    assert "FastAPI" in result.frameworks
    assert result.has_tests is True
    assert result.test_runner == "pytest"
    assert result.package_manager == "pip"
    assert result.repo_type == RepoType.ACTIVE


# ── Node / React repo ─────────────────────────────────────────────────────────

def test_node_react(tmp_path, cls):
    pkg = '{"dependencies": {"react": "^18", "jest": "^29"}, "devDependencies": {}}'
    _write(tmp_path / "package.json", pkg)
    for i in range(15):
        _write(tmp_path / f"src/Component{i}.tsx", "export default () => null;")
    _write(tmp_path / "src/index.ts", "import React from 'react';")

    with patch.object(cls, "_last_commit_days", return_value=10):
        result = cls.classify(str(tmp_path))

    assert result.primary_language == "typescript"
    assert "React" in result.frameworks
    assert result.has_tests is True
    assert result.test_runner == "jest"
    assert result.package_manager == "npm"


# ── Go / Gin repo ─────────────────────────────────────────────────────────────

def test_go_gin(tmp_path, cls):
    _write(tmp_path / "go.mod", "module example.com/app\nrequire github.com/gin-gonic/gin v1.9.0\n")
    for i in range(8):
        _write(tmp_path / f"internal/handler_{i}.go", "package handler")
    _write(tmp_path / "cmd/server/main.go", "package main\nfunc main() {}")
    _write(tmp_path / "internal/handler_test.go", "package handler\nimport testing\n")

    with patch.object(cls, "_last_commit_days", return_value=3):
        result = cls.classify(str(tmp_path))

    assert result.primary_language == "go"
    assert "Gin" in result.frameworks
    assert result.has_tests is True
    assert result.test_runner == "go test"
    assert result.package_manager == "go mod"


# ── Abandoned repo ────────────────────────────────────────────────────────────

def test_abandoned(tmp_path, cls):
    for i in range(10):
        _write(tmp_path / f"src/file_{i}.py", "# old code")

    with patch.object(cls, "_last_commit_days", return_value=200):
        result = cls.classify(str(tmp_path))

    assert result.repo_type == RepoType.ABANDONED
    assert result.last_commit_days_ago == 200


# ── Entry points detected ─────────────────────────────────────────────────────

def test_entry_points_detected(tmp_path, cls):
    _write(tmp_path / "main.py", "if __name__ == '__main__': pass")
    _write(tmp_path / "app.py", "app = Flask(__name__)")
    for i in range(5):
        _write(tmp_path / f"lib/module_{i}.py", "")

    with patch.object(cls, "_last_commit_days", return_value=1):
        result = cls.classify(str(tmp_path))

    assert any("main.py" in e for e in result.entry_points)
    assert any("app.py" in e for e in result.entry_points)


# ── TODO/FIXME extraction ─────────────────────────────────────────────────────

def test_todos_extracted(tmp_path, cls):
    _write(tmp_path / "src/a.py", "# TODO: fix this\nx = 1\n# FIXME: broken\n")
    _write(tmp_path / "src/b.py", "# HACK: workaround\n")
    for i in range(5):
        _write(tmp_path / f"src/other_{i}.py", "")

    with patch.object(cls, "_last_commit_days", return_value=1):
        result = cls.classify(str(tmp_path))

    comments = " ".join(result.open_issues_hint)
    assert "TODO" in comments or "FIXME" in comments or "HACK" in comments


# ── Complexity buckets ────────────────────────────────────────────────────────

def test_complexity_small(tmp_path, cls):
    for i in range(5):
        _write(tmp_path / f"file_{i}.py", "")
    with patch.object(cls, "_last_commit_days", return_value=1):
        result = cls.classify(str(tmp_path))
    assert result.repo_type in (RepoType.GREENFIELD, RepoType.ACTIVE)


def test_complexity_medium(tmp_path, cls):
    for i in range(50):
        _write(tmp_path / f"src/module_{i}.py", "")
    with patch.object(cls, "_last_commit_days", return_value=1):
        result = cls.classify(str(tmp_path))
    assert result.repo_type == RepoType.ACTIVE


def test_complexity_large(tmp_path, cls):
    for i in range(250):
        _write(tmp_path / f"src/module_{i}.py", "")
    with patch.object(cls, "_last_commit_days", return_value=1):
        result = cls.classify(str(tmp_path))
    assert result.repo_type == RepoType.ACTIVE


# ── node_modules skipped ──────────────────────────────────────────────────────

def test_node_modules_skipped(tmp_path, cls):
    _write(tmp_path / "package.json", '{"dependencies": {}}')
    for i in range(500):
        _write(tmp_path / f"node_modules/pkg/file_{i}.js", "")
    _write(tmp_path / "src/index.js", "")

    with patch.object(cls, "_last_commit_days", return_value=1):
        result = cls.classify(str(tmp_path))

    assert result.primary_language == "javascript"
