from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentx.repo.acquisition import AcquisitionError, RepositoryAcquisition
from agentx.repo.models import AuthMethod, RepoAuth


def _make_success(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _make_failure(stderr: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr=stderr)


@pytest.fixture
def acq():
    return RepositoryAcquisition()


# ── Public URL cloned with correct args ──────────────────────────────────────

@pytest.mark.asyncio
async def test_public_clone_calls_git(tmp_path, acq):
    target = str(tmp_path / "repo")
    with patch("agentx.repo.acquisition._run_git", return_value=_make_success()) as mock_git:
        result = await acq.acquire("https://github.com/org/repo.git", target)
    calls = mock_git.call_args_list
    clone_call = calls[0]
    cmd = clone_call[0][0]
    assert cmd[0] == "git"
    assert cmd[1] == "clone"
    assert "https://github.com/org/repo.git" in cmd
    assert target in cmd
    assert result == str(Path(target).resolve())


# ── GitHub token injected into URL ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_github_token_injected_in_url(tmp_path, acq):
    target = str(tmp_path / "repo")
    auth = RepoAuth(method=AuthMethod.GITHUB_TOKEN, token="ghp_abc123")
    captured = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        return _make_success()

    with patch("agentx.repo.acquisition._run_git", side_effect=fake_run):
        await acq.acquire("https://github.com/org/repo.git", target, auth=auth)

    clone_cmd = captured[0]
    url_in_cmd = next(a for a in clone_cmd if "github.com" in a)
    assert "ghp_abc123@github.com" in url_in_cmd


# ── Token NOT persisted to .git/config ───────────────────────────────────────

@pytest.mark.asyncio
async def test_token_not_in_git_config(tmp_path, acq):
    target = str(tmp_path / "repo")
    auth = RepoAuth(method=AuthMethod.GITHUB_TOKEN, token="ghp_secret")
    set_url_calls = []

    def fake_run(cmd, **kwargs):
        if "set-url" in cmd:
            set_url_calls.append(cmd)
        return _make_success()

    with patch("agentx.repo.acquisition._run_git", side_effect=fake_run):
        await acq.acquire("https://github.com/org/repo.git", target, auth=auth)

    assert set_url_calls, "remote set-url was not called"
    clean_url = set_url_calls[0][-1]
    assert "ghp_secret" not in clean_url


# ── SSH key sets GIT_SSH_COMMAND ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ssh_key_sets_git_ssh_command(tmp_path, acq):
    target = str(tmp_path / "repo")
    auth = RepoAuth(method=AuthMethod.SSH_KEY, ssh_key_path="/home/user/.ssh/id_ed25519")
    captured_kwargs = []

    def fake_run(cmd, **kwargs):
        captured_kwargs.append(kwargs)
        return _make_success()

    with patch("agentx.repo.acquisition._run_git", side_effect=fake_run):
        await acq.acquire("git@github.com:org/repo.git", target, auth=auth)

    clone_kwargs = captured_kwargs[0]
    env = clone_kwargs.get("env") or {}
    assert "GIT_SSH_COMMAND" in env
    assert "/home/user/.ssh/id_ed25519" in env["GIT_SSH_COMMAND"]


# ── AcquisitionError raised on clone failure ──────────────────────────────────

@pytest.mark.asyncio
async def test_acquisition_error_on_clone_failure(tmp_path, acq):
    target = str(tmp_path / "repo")
    with patch(
        "agentx.repo.acquisition._run_git",
        return_value=_make_failure("ERROR: Repository not found."),
    ):
        with pytest.raises(AcquisitionError) as exc_info:
            await acq.acquire("https://github.com/org/missing.git", target)

    err = exc_info.value
    assert err.fix_hint
    assert err.cause


# ── AcquisitionError always has fix_hint ─────────────────────────────────────

@pytest.mark.asyncio
async def test_acquisition_error_has_fix_hint(tmp_path, acq):
    target = str(tmp_path / "repo")
    with patch(
        "agentx.repo.acquisition._run_git",
        return_value=_make_failure("Authentication failed"),
    ):
        with pytest.raises(AcquisitionError) as exc_info:
            await acq.acquire("https://github.com/org/private.git", target)
    assert exc_info.value.fix_hint


# ── Local path returned as-is ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_local_path_returned_without_clone(tmp_path, acq):
    with patch("agentx.repo.acquisition._run_git") as mock_git:
        result = await acq.acquire(str(tmp_path), str(tmp_path / "dest"))
    mock_git.assert_not_called()
    assert result == str(tmp_path.resolve())


# ── owner/repo shorthand expands to GitHub URL ───────────────────────────────

@pytest.mark.asyncio
async def test_owner_repo_shorthand_expands_to_github(tmp_path, acq):
    target = str(tmp_path / "repo")
    captured = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        return _make_success()

    with patch("agentx.repo.acquisition._run_git", side_effect=fake_run):
        await acq.acquire("owner/repo", target)

    clone_cmd = captured[0]
    assert any("github.com" in a and "owner/repo" in a for a in clone_cmd)


# ── Timeout raises AcquisitionError ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_timeout_raises_acquisition_error(tmp_path, acq):
    target = str(tmp_path / "repo")
    with patch(
        "agentx.repo.acquisition._run_git",
        side_effect=subprocess.TimeoutExpired(cmd="git", timeout=120),
    ):
        with pytest.raises(AcquisitionError) as exc_info:
            await acq.acquire("https://github.com/org/repo.git", target)
    assert "timeout" in exc_info.value.cause.lower() or "120" in exc_info.value.cause


# ── Branch flag forwarded to git ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_branch_forwarded_to_git(tmp_path, acq):
    target = str(tmp_path / "repo")
    captured = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        return _make_success()

    with patch("agentx.repo.acquisition._run_git", side_effect=fake_run):
        await acq.acquire("https://github.com/org/repo.git", target, branch="develop")

    clone_cmd = captured[0]
    assert "--branch" in clone_cmd
    assert "develop" in clone_cmd
