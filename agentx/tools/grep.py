from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agentx.tools.base import Risk, ToolContext, ToolResult, register


class GrepArgs(BaseModel):
    pattern: str
    path: str = "."
    case_sensitive: bool = True
    include_glob: str = "**/*"
    max_results: int = 200


class GrepTool:
    name = "grep"
    description = (
        "Search for a regex pattern in workspace files. "
        "Returns matching lines with file path and line number. "
        "`path` scopes the search to a subdirectory (default: entire workspace). "
        "`include_glob` filters file names (e.g. '*.py')."
    )
    risk = Risk.SAFE
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "path": {"type": "string", "default": ".", "description": "Subdirectory to scope search"},
            "case_sensitive": {"type": "boolean", "default": True},
            "include_glob": {"type": "string", "default": "**/*", "description": "File glob filter (e.g. '*.py')"},
            "max_results": {"type": "integer", "default": 200},
        },
        "required": ["pattern"],
    }

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, GrepArgs)
        root = Path(ctx.workspace).resolve()
        search_root = (root / args.path).resolve()

        if not str(search_root).startswith(str(root)):
            return ToolResult(ok=False, observation=f"Path escapes workspace: {args.path}")
        if not search_root.exists():
            return ToolResult(ok=False, observation=f"Path not found: {args.path}")

        matches = _run_grep(
            pattern=args.pattern,
            root=search_root,
            case_sensitive=args.case_sensitive,
            include_glob=args.include_glob,
            max_results=args.max_results,
        )

        if not matches:
            return ToolResult(ok=True, observation="No matches found.", data={"matches": []})

        lines = [f"{m['file']}:{m['line_number']}: {m['line']}" for m in matches]
        obs = f"{len(matches)} match(es):\n" + "\n".join(lines)
        return ToolResult(ok=True, observation=obs, data={"matches": matches})


def _run_grep(
    pattern: str,
    root: Path,
    *,
    case_sensitive: bool,
    include_glob: str,
    max_results: int,
) -> list[dict[str, Any]]:
    # Try subprocess grep first (fast); fall back to pure Python
    try:
        return _grep_subprocess(pattern, root, case_sensitive=case_sensitive, include_glob=include_glob, max_results=max_results)
    except (FileNotFoundError, OSError):
        return _grep_python(pattern, root, case_sensitive=case_sensitive, include_glob=include_glob, max_results=max_results)


def _grep_subprocess(
    pattern: str, root: Path, *, case_sensitive: bool, include_glob: str, max_results: int
) -> list[dict[str, Any]]:
    cmd = ["grep", "-rn", "--exclude-dir=.git", "--exclude-dir=__pycache__"]
    if not case_sensitive:
        cmd.append("-i")
    if include_glob and include_glob not in ("**/*", "*"):
        # strip leading **/ if present
        bare_glob = include_glob.lstrip("*").lstrip("/")
        if bare_glob:
            cmd += [f"--include={bare_glob}"]
    cmd += ["--", pattern, str(root)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return []

    matches: list[dict[str, Any]] = []
    for raw_line in result.stdout.splitlines()[:max_results]:
        parts = raw_line.split(":", 2)
        if len(parts) >= 3:
            try:
                rel = str(Path(parts[0]).relative_to(root))
            except ValueError:
                rel = parts[0]
            try:
                lineno = int(parts[1])
            except ValueError:
                lineno = 0
            matches.append({"file": rel, "line_number": lineno, "line": parts[2]})
    return matches


def _grep_python(
    pattern: str, root: Path, *, case_sensitive: bool, include_glob: str, max_results: int
) -> list[dict[str, Any]]:
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        rx = re.compile(pattern, flags)
    except re.error:
        return []

    bare_glob = include_glob.lstrip("*").lstrip("/") or "*"
    # Normalise to just the filename pattern for glob
    if "/" in bare_glob:
        bare_glob = bare_glob.rsplit("/", 1)[-1] or "*"

    matches: list[dict[str, Any]] = []
    _SKIP_DIRS = {".git", "__pycache__", ".mypy_cache", ".ruff_cache", "node_modules"}

    for p in root.rglob(bare_glob):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                rel = str(p.relative_to(root))
                matches.append({"file": rel, "line_number": i, "line": line})
                if len(matches) >= max_results:
                    return matches
    return matches


grep = GrepTool()
register(grep)
