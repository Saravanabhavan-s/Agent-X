from __future__ import annotations

import shlex
from typing import Any

from pydantic import BaseModel

from agentx.tools.base import Risk, ToolContext, ToolResult, register

# Commands that must never execute regardless of context
_BLOCKLIST = [
    "rm -rf /",
    ":(){ :|:& };:",
    "mkfs",
    "dd if=/dev/zero",
    "chmod -R 777 /",
    "> /dev/sda",
]

_DEFAULT_TIMEOUT = 30.0


class BashArgs(BaseModel):
    command: str
    timeout: float = _DEFAULT_TIMEOUT
    cwd: str | None = None


class BashTool:
    name = "bash"
    description = (
        "Execute a shell command in the workspace sandbox. "
        "Returns stdout, stderr and exit code. "
        "Non-zero exit codes are captured — they do NOT raise an error. "
        "Hard timeout default: 30s. Blocked commands (rm -rf /, fork bombs, mkfs) "
        "are rejected immediately."
    )
    risk = Risk.WRITE
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "number", "default": _DEFAULT_TIMEOUT, "description": "Timeout in seconds"},
            "cwd": {"type": "string", "description": "Working directory (workspace-relative); default: workspace root"},
        },
        "required": ["command"],
    }

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, BashArgs)

        # Block list check
        cmd_lower = args.command.lower().strip()
        for blocked in _BLOCKLIST:
            if blocked in cmd_lower:
                return ToolResult(
                    ok=False,
                    observation=f"Command blocked by safety policy: {blocked!r} matched in command.",
                )

        if ctx.sandbox is None:
            return ToolResult(ok=False, observation="No sandbox available — cannot execute bash commands.")

        cwd = ctx.workspace
        if args.cwd:
            from pathlib import Path
            resolved = (Path(ctx.workspace) / args.cwd).resolve()
            if not str(resolved).startswith(str(Path(ctx.workspace).resolve())):
                return ToolResult(ok=False, observation=f"cwd escapes workspace: {args.cwd}")
            cwd = str(resolved)

        cmd_list = _split_command(args.command)
        result = await ctx.sandbox.run(cmd_list, cwd=cwd, timeout=args.timeout)

        if result.returncode == -1 and "timed out" in result.stderr.lower():
            return ToolResult(
                ok=False,
                observation=f"Command timed out after {args.timeout}s.\nstderr: {result.stderr}",
                data={"returncode": -1, "stdout": result.stdout, "stderr": result.stderr},
            )

        obs_parts = []
        if result.stdout:
            obs_parts.append(f"stdout:\n{result.stdout}")
        if result.stderr:
            obs_parts.append(f"stderr:\n{result.stderr}")
        obs_parts.append(f"exit_code: {result.returncode}")
        obs = "\n".join(obs_parts) or "(no output)"

        return ToolResult(
            ok=result.ok,
            observation=obs,
            data={"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr},
        )


def _split_command(cmd: str) -> list[str]:
    """Split shell command string for subprocess; handles quoted strings."""
    try:
        return shlex.split(cmd)
    except ValueError:
        # Malformed quoting — pass as shell=True equivalent via sh -c
        return ["sh", "-c", cmd]


bash = BashTool()
register(bash)
