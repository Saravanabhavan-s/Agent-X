from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agentx.tools.base import Risk, ToolContext, ToolResult, register


class GitOpsArgs(BaseModel):
    action: str  # branch | commit | diff | status | pr_prep_summary
    branch_name: str | None = None
    message: str | None = None
    files: list[str] | None = None  # for commit — None means stage all tracked changes
    base_branch: str = "main"


class GitOpsTool:
    name = "git_ops"
    description = (
        "Git operations: branch, commit, diff, status, pr_prep_summary. "
        "action='branch': create/switch branch (requires branch_name). "
        "action='commit': stage files and commit (requires message; files=None stages all). "
        "action='diff': show git diff vs base_branch. "
        "action='status': show working-tree status. "
        "action='pr_prep_summary': return structured PR summary dict (no LLM call)."
    )
    risk = Risk.WRITE
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["branch", "commit", "diff", "status", "pr_prep_summary"],
            },
            "branch_name": {"type": "string"},
            "message": {"type": "string"},
            "files": {"type": "array", "items": {"type": "string"}},
            "base_branch": {"type": "string", "default": "main"},
        },
        "required": ["action"],
    }

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, GitOpsArgs)
        cwd = ctx.workspace
        action = args.action

        try:
            if action == "branch":
                return await _branch(cwd, args.branch_name)
            elif action == "commit":
                return await _commit(cwd, args.message, args.files)
            elif action == "diff":
                return await _diff(cwd, args.base_branch)
            elif action == "status":
                return await _status(cwd)
            elif action == "pr_prep_summary":
                return await _pr_prep_summary(cwd, args.base_branch)
            else:
                return ToolResult(ok=False, observation=f"Unknown git action: {action!r}")
        except subprocess.CalledProcessError as exc:
            return ToolResult(ok=False, observation=f"git error: {exc.stderr or exc.stdout or str(exc)}")
        except OSError as exc:
            return ToolResult(ok=False, observation=f"OS error: {exc}")


def _run(cmd: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, check=True, timeout=30
    )


def _run_safe(cmd: list[str], cwd: str) -> subprocess.CompletedProcess:
    """Run without check=True; caller inspects returncode."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)


async def _branch(cwd: str, name: str | None) -> ToolResult:
    if not name:
        return ToolResult(ok=False, observation="branch_name required for action='branch'")
    # Create and switch; if already exists just switch
    result = _run_safe(["git", "checkout", "-b", name], cwd)
    if result.returncode != 0:
        # branch may already exist
        result = _run(["git", "checkout", name], cwd)
    return ToolResult(ok=True, observation=f"Switched to branch: {name}")


async def _commit(cwd: str, message: str | None, files: list[str] | None) -> ToolResult:
    if not message:
        return ToolResult(ok=False, observation="message required for action='commit'")
    if files:
        _run(["git", "add", "--"] + files, cwd)
    else:
        _run(["git", "add", "-u"], cwd)
    result = _run(["git", "commit", "-m", message], cwd)
    return ToolResult(ok=True, observation=result.stdout or f"Committed: {message}")


async def _diff(cwd: str, base_branch: str) -> ToolResult:
    result = _run_safe(["git", "diff", base_branch, "HEAD"], cwd)
    if result.returncode != 0:
        # base_branch might not exist yet; fall back to unstaged diff
        result = _run_safe(["git", "diff"], cwd)
    diff_text = result.stdout or "(no diff)"
    return ToolResult(ok=True, observation=diff_text, data={"diff": diff_text})


async def _status(cwd: str) -> ToolResult:
    result = _run(["git", "status", "--short"], cwd)
    obs = result.stdout.strip() or "(clean)"
    return ToolResult(ok=True, observation=obs, data={"status": obs})


async def _pr_prep_summary(cwd: str, base_branch: str) -> ToolResult:
    stat = _run_safe(["git", "diff", "--stat", f"{base_branch}...HEAD"], cwd)
    diff_stat = stat.stdout.strip() if stat.returncode == 0 else "(unavailable)"

    log = _run_safe(["git", "log", "--oneline", f"{base_branch}...HEAD"], cwd)
    commits = log.stdout.strip().splitlines() if log.returncode == 0 else []

    files_result = _run_safe(["git", "diff", "--name-only", f"{base_branch}...HEAD"], cwd)
    changed_files = files_result.stdout.strip().splitlines() if files_result.returncode == 0 else []

    # Cheap risk hint: any migration or config file change elevates risk
    _HIGH_RISK_SUFFIXES = (".sql", "migration", "alembic", "settings", ".env", "docker")
    risk_hint = "low"
    for f in changed_files:
        if any(s in f.lower() for s in _HIGH_RISK_SUFFIXES):
            risk_hint = "high"
            break

    title_hint = commits[0].split(" ", 1)[-1] if commits else "Update"

    summary = {
        "title": title_hint,
        "changed_files": changed_files,
        "diff_stat": diff_stat,
        "commit_count": len(commits),
        "risk_hint": risk_hint,
    }
    return ToolResult(
        ok=True,
        observation=f"PR summary: {len(changed_files)} file(s) changed, risk={risk_hint}\n{diff_stat}",
        data=summary,
    )


git_ops = GitOpsTool()
register(git_ops)
