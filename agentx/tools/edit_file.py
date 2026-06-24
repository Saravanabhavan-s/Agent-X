from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from agentx.runtime.patch import PatchBlock, apply_patch
from agentx.tools.base import Risk, ToolContext, ToolResult, register


class EditFileArgs(BaseModel):
    path: str
    old: str
    new: str


class EditFileTool:
    name = "edit_file"
    description = (
        "Apply a search-and-replace edit to a file in the workspace. "
        "The exact text in `old` must appear in the file; it is replaced with `new`. "
        "Use read_file first to verify the exact text before editing."
    )
    risk = Risk.WRITE
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path"},
            "old": {"type": "string", "description": "Exact text to find (must be unique enough to locate)"},
            "new": {"type": "string", "description": "Replacement text"},
        },
        "required": ["path", "old", "new"],
    }

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, EditFileArgs)
        block = PatchBlock(path=args.path, old=args.old, new=args.new)
        result = apply_patch([block], ctx.workspace)
        if not result.ok:
            return ToolResult(ok=False, observation=result.error)
        return ToolResult(
            ok=True,
            observation=f"Applied edit to {args.path}.\n\n{result.diff}",
            data={"diff": result.diff, "applied": result.applied},
            artifacts=result.applied,
        )


edit_file = EditFileTool()
register(edit_file)
