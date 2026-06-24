from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentx.repo.health import ProjectHealthAnalyzer
from agentx.repo.models import RepoClassification, RepoType


def _make_classification(
    repo_type: RepoType = RepoType.ACTIVE,
    package_manager: str | None = "pip",
    test_runner: str | None = "pytest",
    primary_language: str = "python",
) -> RepoClassification:
    return RepoClassification(
        repo_type=repo_type,
        primary_language=primary_language,
        secondary_languages=[],
        frameworks=[],
        has_tests=True,
        has_ci=False,
        has_docs=False,
        has_docker=False,
        entry_points=[],
        package_manager=package_manager,
        test_runner=test_runner,
        last_commit_days_ago=5,
        open_issues_hint=[],
        confidence=0.9,
    )


def _sandbox(install_ok: bool = True, test_ok: bool = True, test_output: str = "3 passed") -> MagicMock:
    sb = MagicMock()

    async def _run(cmd, **kwargs):
        r = MagicMock()
        if "install" in cmd or "download" in cmd or "fetch" in cmd or "pip" in cmd or "uv" in cmd:
            r.ok = install_ok
            r.stdout = ""
            r.stderr = "" if install_ok else "Error: No module named 'missing_pkg'"
        else:
            r.ok = test_ok
            r.stdout = test_output
            r.stderr = ""
        return r

    sb.run = _run
    return sb


@pytest.fixture
def analyzer():
    return ProjectHealthAnalyzer()


# ── Greenfield: score 1.0, no test run ───────────────────────────────────────

@pytest.mark.asyncio
async def test_greenfield_score_1_no_run(tmp_path, analyzer):
    cls = _make_classification(repo_type=RepoType.GREENFIELD)
    sb = MagicMock()
    sb.run = AsyncMock()
    result = await analyzer.analyze(str(tmp_path), cls, sb)
    assert result["health_score"] == 1.0
    assert result["inferred_intent"] != ""
    sb.run.assert_not_called()


# ── Dep install failure captured as build_errors ──────────────────────────────

@pytest.mark.asyncio
async def test_install_failure_captured(tmp_path, analyzer):
    cls = _make_classification(repo_type=RepoType.BROKEN, package_manager="pip")
    sb = _sandbox(install_ok=False, test_ok=False)
    result = await analyzer.analyze(str(tmp_path), cls, sb)
    assert result["can_install_deps"] is False
    assert result["build_errors"]


# ── Missing deps extracted ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_deps_extracted(tmp_path, analyzer):
    cls = _make_classification(repo_type=RepoType.BROKEN, package_manager="pip")
    sb = _sandbox(install_ok=False, test_ok=False)

    # Override sandbox to return specific missing-dep error
    async def _run(cmd, **kwargs):
        r = MagicMock()
        r.ok = False
        r.stdout = ""
        r.stderr = "Error: No module named 'fastapi'"
        return r

    sb.run = _run
    result = await analyzer.analyze(str(tmp_path), cls, sb)
    assert "fastapi" in result["missing_deps"]


# ── Test failures captured ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failures_captured(tmp_path, analyzer):
    cls = _make_classification(repo_type=RepoType.ACTIVE)
    sb = _sandbox(install_ok=True, test_ok=False, test_output="2 passed, 3 failed")
    result = await analyzer.analyze(str(tmp_path), cls, sb)
    assert result["can_run_tests"] is True
    tr = result["test_results"]
    assert tr is not None
    assert tr.get("failed", 0) == 3
    assert tr.get("passed", 0) == 2


# ── health_score range: broken ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_score_broken(tmp_path, analyzer):
    cls = _make_classification(repo_type=RepoType.BROKEN)
    sb = _sandbox(install_ok=False)
    result = await analyzer.analyze(str(tmp_path), cls, sb)
    assert result["health_score"] <= 0.4


# ── health_score near 1.0 for all passing ─────────────────────────────────────

@pytest.mark.asyncio
async def test_health_score_all_passing(tmp_path, analyzer):
    cls = _make_classification(repo_type=RepoType.ACTIVE)
    sb = _sandbox(install_ok=True, test_ok=True, test_output="10 passed")
    result = await analyzer.analyze(str(tmp_path), cls, sb)
    assert result["health_score"] >= 0.8


# ── Abandoned repo: inferred_intent populated ─────────────────────────────────

@pytest.mark.asyncio
async def test_abandoned_intent_populated(tmp_path, analyzer):
    (tmp_path / "README.md").write_text("# My Cool Project\nA tool for processing CSV files.", encoding="utf-8")
    cls = _make_classification(repo_type=RepoType.ABANDONED, package_manager=None, test_runner=None)

    async def _run(cmd, **kwargs):
        r = MagicMock()
        r.ok = True
        r.stdout = ""
        r.stderr = ""
        return r

    sb = MagicMock()
    sb.run = _run

    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout="abc1234 fix stuff\n", stderr="")
        result = await analyzer.analyze(str(tmp_path), cls, sb)

    assert result["inferred_intent"]


# ── Crash in sandbox never propagates ────────────────────────────────────────

@pytest.mark.asyncio
async def test_sandbox_crash_does_not_raise(tmp_path, analyzer):
    cls = _make_classification(repo_type=RepoType.ACTIVE)
    sb = MagicMock()

    async def _crash(cmd, **kwargs):
        raise RuntimeError("sandbox exploded")

    sb.run = _crash
    result = await analyzer.analyze(str(tmp_path), cls, sb)
    assert "build_errors" in result
    assert any("exploded" in e or "crash" in e.lower() or "Health" in e for e in result["build_errors"])
