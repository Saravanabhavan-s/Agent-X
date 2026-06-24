from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agentx.tools.base import Risk, ToolContext, ToolResult, register


class GlobArgs(BaseModel):
    pattern: str
    path: str = "."
    max_results: int = 500


class GlobTool:
    name = "glob"
    description = (
        "Return all file paths matching a glob pattern inside the workspace. "
        "Results are workspace-relative paths. "
        "`path` scopes the search to a subdirectory (default: entire workspace)."
    )
    risk = Risk.SAFE
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py' or 'src/*.ts'"},
            "path": {"type": "string", "default": ".", "description": "Subdirectory to scope search"},
            "max_results": {"type": "integer", "default": 500},
        },
        "required": ["pattern"],
    }

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, GlobArgs)
        root = Path(ctx.workspace).resolve()
        search_root = (root / args.path).resolve()

        if not str(search_root).startswith(str(root)):
            return ToolResult(ok=False, observation=f"Path escapes workspace: {args.path}")
        if not search_root.exists():
            return ToolResult(ok=False, observation=f"Path not found: {args.path}")

        _SKIP = {".git", "__pycache__", ".mypy_cache", ".ruff_cache", "node_modules"}

        results: list[str] = []
        for p in search_root.glob(args.pattern):
            if any(part in _SKIP for part in p.parts):
                continue
            # Ensure path stays inside workspace (no symlink escape)
            try:
                rel = str(p.resolve().relative_to(root))
            except ValueError:
                continue  # escapes workspace
            results.append(rel)
            if len(results) >= args.max_results:
                break

        results.sort()

        if not results:
            return ToolResult(ok=True, observation="No files matched.", data={"paths": []})

        obs = f"{len(results)} file(s) matched:\n" + "\n".join(results)
        return ToolResult(ok=True, observation=obs, data={"paths": results})


glob_tool = GlobTool()
register(glob_tool)
