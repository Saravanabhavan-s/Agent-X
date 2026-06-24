from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agentx.tools.base import Risk, Tool, ToolContext, ToolResult, register


class ReadFileArgs(BaseModel):
    path: str
    start_line: int = 1
    end_line: int | None = None


class ReadFileTool:
    name = "read_file"
    description = (
        "Read the contents of a file in the workspace. "
        "Optionally slice to [start_line, end_line] (1-indexed, inclusive)."
    )
    risk = Risk.SAFE
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path"},
            "start_line": {"type": "integer", "default": 1},
            "end_line": {"type": "integer", "description": "Inclusive last line; omit for full file"},
        },
        "required": ["path"],
    }

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, ReadFileArgs)
        root = Path(ctx.workspace)
        target = (root / args.path).resolve()

        if not str(target).startswith(str(root.resolve())):
            return ToolResult(ok=False, observation=f"Path escapes workspace: {args.path}")

        if not target.exists():
            return ToolResult(ok=False, observation=f"File not found: {args.path}")

        try:
            lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError as exc:
            return ToolResult(ok=False, observation=str(exc))

        start = max(0, args.start_line - 1)
        end = args.end_line if args.end_line is not None else len(lines)
        selected = lines[start:end]
        content = "".join(selected)
        numbered = "".join(
            f"{i + start + 1:>6} | {line}" for i, line in enumerate(selected)
        )
        return ToolResult(
            ok=True,
            observation=f"File: {args.path} ({len(lines)} lines total, showing {start+1}-{start+len(selected)})\n\n{numbered}",
            data={"content": content, "total_lines": len(lines)},
        )


read_file = ReadFileTool()
register(read_file)
