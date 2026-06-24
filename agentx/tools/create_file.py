from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agentx.tools.base import Risk, ToolContext, ToolResult, register


class CreateFileArgs(BaseModel):
    path: str
    content: str


class CreateFileTool:
    name = "create_file"
    description = (
        "Create a new file in the workspace with the given content. "
        "Fails if the file already exists — use edit_file to modify existing files."
    )
    risk = Risk.WRITE
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path for the new file"},
            "content": {"type": "string", "description": "Full content of the new file"},
        },
        "required": ["path", "content"],
    }

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, CreateFileArgs)
        root = Path(ctx.workspace).resolve()
        target = (root / args.path).resolve()

        if not str(target).startswith(str(root)):
            return ToolResult(ok=False, observation=f"Path escapes workspace: {args.path}")

        if target.exists():
            return ToolResult(
                ok=False,
                observation=(
                    f"File already exists: {args.path}. "
                    "Use edit_file to modify existing files."
                ),
            )

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args.content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(ok=False, observation=f"Failed to create file: {exc}")

        return ToolResult(
            ok=True,
            observation=f"Created {args.path} ({len(args.content)} bytes).",
            artifacts=[args.path],
        )


create_file = CreateFileTool()
register(create_file)
