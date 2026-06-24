from __future__ import annotations

# LSP process management is deferred to V2.
# V1: tree-sitter parse-only for Python, JavaScript, TypeScript.

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agentx.tools.base import Risk, ToolContext, ToolResult, register
from agentx.tools.grep import _grep_python  # reuse internal grep for find_references


# ---------------------------------------------------------------------------
# Language loader — lazy so missing grammars don't crash unrelated imports
# ---------------------------------------------------------------------------

def _load_languages() -> dict[str, Any]:
    """Return {ext: Language} dict. Missing grammars are skipped."""
    from tree_sitter import Language
    langs: dict[str, Any] = {}
    try:
        import tree_sitter_python as tspython
        langs[".py"] = Language(tspython.language())
    except ImportError:
        pass
    try:
        import tree_sitter_javascript as tsjs
        langs[".js"] = Language(tsjs.language())
        langs[".jsx"] = langs[".js"]
    except ImportError:
        pass
    try:
        import tree_sitter_typescript as tsts
        langs[".ts"] = Language(tsts.language_typescript())
        langs[".tsx"] = Language(tsts.language_tsx())
    except ImportError:
        pass
    return langs


_LANGUAGES: dict[str, Any] | None = None


def _get_languages() -> dict[str, Any]:
    global _LANGUAGES
    if _LANGUAGES is None:
        _LANGUAGES = _load_languages()
    return _LANGUAGES


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------

# Map (language_extension, node_type) → symbol kind
_KIND_MAP: dict[tuple[str, str], str] = {
    # Python
    (".py", "function_definition"): "function",
    (".py", "async_function_definition"): "function",
    (".py", "class_definition"): "class",
    # JavaScript / TypeScript share most types
    (".js", "function_declaration"): "function",
    (".js", "function_expression"): "function",
    (".js", "arrow_function"): "function",
    (".js", "class_declaration"): "class",
    (".js", "method_definition"): "method",
    (".js", "variable_declarator"): "variable",
    (".ts", "function_declaration"): "function",
    (".ts", "function_expression"): "function",
    (".ts", "arrow_function"): "function",
    (".ts", "class_declaration"): "class",
    (".ts", "method_definition"): "method",
    (".ts", "variable_declarator"): "variable",
    (".tsx", "function_declaration"): "function",
    (".tsx", "class_declaration"): "class",
    (".tsx", "method_definition"): "method",
    # jsx uses js grammar
    (".jsx", "function_declaration"): "function",
    (".jsx", "class_declaration"): "class",
    (".jsx", "method_definition"): "method",
}

_SYMBOL_NODES = frozenset(
    nt for _, nt in _KIND_MAP
)


def _extract_name(node: Any, ext: str) -> str | None:
    """Return the symbol name from a declaration node."""
    name_node = node.child_by_field_name("name")
    if name_node:
        return name_node.text.decode("utf-8", errors="replace")
    # variable_declarator: the first child is often the name
    if node.type == "variable_declarator" and node.child_count > 0:
        first = node.children[0]
        if first.type in ("identifier",):
            return first.text.decode("utf-8", errors="replace")
    return None


def _walk_symbols(root_node: Any, ext: str, source_lines: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    def _visit(node: Any, parent_kind: str | None = None) -> None:
        ntype = node.type
        key = (ext, ntype)
        kind = _KIND_MAP.get(key)
        if kind:
            name = _extract_name(node, ext)
            if name:
                # For Python class methods: kind = method if inside class_definition
                if kind == "function" and parent_kind == "class":
                    kind = "method"
                start_line = node.start_point[0] + 1  # 1-indexed
                end_line = node.end_point[0] + 1
                results.append({
                    "name": name,
                    "kind": kind,
                    "line": start_line,
                    "end_line": end_line,
                })
            for child in node.children:
                _visit(child, parent_kind=kind or parent_kind)
        else:
            for child in node.children:
                _visit(child, parent_kind=parent_kind)

    _visit(root_node)
    return results


def extract_symbols(file_path: str) -> list[dict[str, Any]]:
    """Parse file with tree-sitter and return list of {name, kind, line, end_line}."""
    p = Path(file_path)
    ext = p.suffix.lower()
    langs = _get_languages()
    lang = langs.get(ext)
    if lang is None:
        return []

    from tree_sitter import Parser
    try:
        source = p.read_bytes()
        source_lines = source.decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []

    parser = Parser(lang)
    tree = parser.parse(source)
    return _walk_symbols(tree.root_node, ext, source_lines)


def find_references(symbol_name: str, workspace_root: str) -> list[dict[str, Any]]:
    """Find all occurrences of symbol_name in workspace via grep.

    Returns same format as grep.py: [{file, line_number, line}].
    """
    root = Path(workspace_root)
    # Use word-boundary pattern to avoid partial matches
    pattern = rf"\b{symbol_name}\b"
    return _grep_python(pattern, root, case_sensitive=True, include_glob="**/*", max_results=500)


# ---------------------------------------------------------------------------
# Tool wrapper
# ---------------------------------------------------------------------------

class SymbolsArgs(BaseModel):
    action: str  # extract | find_references
    path: str | None = None          # for extract: workspace-relative file path
    symbol_name: str | None = None   # for find_references


class SymbolsTool:
    name = "symbols"
    description = (
        "Tree-sitter symbol extraction and reference finding. "
        "action='extract': parse a file and return all symbols (functions, classes, methods, variables). "
        "action='find_references': grep workspace for all uses of a symbol name. "
        "Supports Python, JavaScript, TypeScript. LSP integration is V2."
    )
    risk = Risk.SAFE
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["extract", "find_references"],
            },
            "path": {"type": "string", "description": "Workspace-relative file path (for extract)"},
            "symbol_name": {"type": "string", "description": "Symbol name to search for (for find_references)"},
        },
        "required": ["action"],
    }

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, SymbolsArgs)

        if args.action == "extract":
            if not args.path:
                return ToolResult(ok=False, observation="path required for action='extract'")
            root = Path(ctx.workspace).resolve()
            target = (root / args.path).resolve()
            if not str(target).startswith(str(root)):
                return ToolResult(ok=False, observation=f"Path escapes workspace: {args.path}")
            if not target.exists():
                return ToolResult(ok=False, observation=f"File not found: {args.path}")
            symbols = extract_symbols(str(target))
            if not symbols:
                return ToolResult(
                    ok=True,
                    observation="No symbols extracted (unsupported file type or empty file).",
                    data={"symbols": []},
                )
            lines = [f"  {s['kind']:10} {s['name']:30} line {s['line']}-{s['end_line']}" for s in symbols]
            obs = f"{len(symbols)} symbol(s) in {args.path}:\n" + "\n".join(lines)
            return ToolResult(ok=True, observation=obs, data={"symbols": symbols})

        elif args.action == "find_references":
            if not args.symbol_name:
                return ToolResult(ok=False, observation="symbol_name required for action='find_references'")
            refs = find_references(args.symbol_name, ctx.workspace)
            if not refs:
                return ToolResult(
                    ok=True,
                    observation=f"No references found for {args.symbol_name!r}.",
                    data={"matches": []},
                )
            lines = [f"{m['file']}:{m['line_number']}: {m['line']}" for m in refs]
            obs = f"{len(refs)} reference(s) to {args.symbol_name!r}:\n" + "\n".join(lines)
            return ToolResult(ok=True, observation=obs, data={"matches": refs})

        return ToolResult(ok=False, observation=f"Unknown action: {args.action!r}")


symbols = SymbolsTool()
register(symbols)
