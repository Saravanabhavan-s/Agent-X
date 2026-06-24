from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agentx.tools.git_ops import GitOpsArgs, GitOpsTool
from agentx.tools.base import ToolContext


@pytest.fixture()
def git_ws(tmp_path: Path) -> ToolContext:
    """Create a real git repo with one initial commit."""
    subprocess.run(["git", "init", "--initial-branch=main", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    (tmp_path / "README.md").write_text("# test\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "initial"], check=True, capture_output=True)
    return ToolContext(workspace=str(tmp_path), session_id="test")


@pytest.mark.asyncio
async def test_status_clean(git_ws):
    tool = GitOpsTool()
    result = await tool.run(GitOpsArgs(action="status"), git_ws)
    assert result.ok
    assert "(clean)" in result.observation or result.observation.strip() == ""


@pytest.mark.asyncio
async def test_status_modified(git_ws, tmp_path):
    (Path(git_ws.workspace) / "README.md").write_text("changed\n")
    tool = GitOpsTool()
    result = await tool.run(GitOpsArgs(action="status"), git_ws)
    assert result.ok
    assert "README.md" in result.observation


@pytest.mark.asyncio
async def test_diff_shows_changes(git_ws):
    (Path(git_ws.workspace) / "new.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", git_ws.workspace, "add", "."], check=True)
    subprocess.run(["git", "-C", git_ws.workspace, "commit", "-m", "add file"], check=True, capture_output=True)
    tool = GitOpsTool()
    result = await tool.run(GitOpsArgs(action="diff", base_branch="main"), git_ws)
    assert result.ok


@pytest.mark.asyncio
async def test_branch_create_and_switch(git_ws):
    tool = GitOpsTool()
    result = await tool.run(GitOpsArgs(action="branch", branch_name="feature-x"), git_ws)
    assert result.ok
    assert "feature-x" in result.observation
    # Verify we're on the new branch
    br = subprocess.run(["git", "-C", git_ws.workspace, "branch", "--show-current"],
                        capture_output=True, text=True)
    assert "feature-x" in br.stdout


@pytest.mark.asyncio
async def test_branch_requires_name(git_ws):
    tool = GitOpsTool()
    result = await tool.run(GitOpsArgs(action="branch"), git_ws)
    assert not result.ok
    assert "branch_name" in result.observation


@pytest.mark.asyncio
async def test_commit_action(git_ws):
    (Path(git_ws.workspace) / "f.py").write_text("y = 2\n")
    subprocess.run(["git", "-C", git_ws.workspace, "add", "f.py"], check=True)
    tool = GitOpsTool()
    result = await tool.run(GitOpsArgs(action="commit", message="add f.py", files=["f.py"]), git_ws)
    assert result.ok


@pytest.mark.asyncio
async def test_commit_requires_message(git_ws):
    tool = GitOpsTool()
    result = await tool.run(GitOpsArgs(action="commit"), git_ws)
    assert not result.ok
    assert "message" in result.observation


@pytest.mark.asyncio
async def test_pr_prep_summary(git_ws):
    (Path(git_ws.workspace) / "feat.py").write_text("z = 3\n")
    subprocess.run(["git", "-C", git_ws.workspace, "add", "."], check=True)
    subprocess.run(["git", "-C", git_ws.workspace, "commit", "-m", "add feat"], check=True, capture_output=True)
    tool = GitOpsTool()
    result = await tool.run(GitOpsArgs(action="pr_prep_summary", base_branch="main"), git_ws)
    assert result.ok
    data = result.data
    assert "title" in data
    assert "changed_files" in data
    assert "diff_stat" in data
    assert "risk_hint" in data


@pytest.mark.asyncio
async def test_pr_prep_summary_high_risk_migration(git_ws):
    # Must be on a feature branch so main...HEAD diff is non-empty
    subprocess.run(["git", "-C", git_ws.workspace, "checkout", "-b", "feat-migration"],
                   check=True, capture_output=True)
    (Path(git_ws.workspace) / "0002_add_table.sql").write_text("CREATE TABLE x (id int);\n")
    subprocess.run(["git", "-C", git_ws.workspace, "add", "."], check=True)
    subprocess.run(["git", "-C", git_ws.workspace, "commit", "-m", "add migration"],
                   check=True, capture_output=True)
    tool = GitOpsTool()
    result = await tool.run(GitOpsArgs(action="pr_prep_summary", base_branch="main"), git_ws)
    assert result.ok
    assert result.data["risk_hint"] == "high"
