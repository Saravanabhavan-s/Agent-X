from __future__ import annotations

from pathlib import Path
from typing import Any

from agentx.intelligence.models import Import, Symbol


def _load_python_language() -> Any | None:
    try:
        from tree_sitter import Language
        import tree_sitter_python as tspy
        return Language(tspy.language())
    except Exception:
        return None


_PY_LANG: Any | None = None


def _get_py_lang() -> Any | None:
    global _PY_LANG
    if _PY_LANG is None:
        _PY_LANG = _load_python_language()
    return _PY_LANG


def _node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _first_string_in_body(node: Any, source: bytes) -> str | None:
    """Return the first string literal in a function/class body as docstring."""
    for child in node.children:
        if child.type == "block":
            for stmt in child.children:
                if stmt.type == "expression_statement":
                    for inner in stmt.children:
                        if inner.type in ("string", "concatenated_string"):
                            return _node_text(inner, source).strip("\"' \n")
            break
    return None


def _extract_symbols(root: Any, source: bytes, file_path: str) -> list[Symbol]:
    results: list[Symbol] = []
    lines = source.decode("utf-8", errors="replace").splitlines()

    def _signature_line(node: Any) -> str:
        start = node.start_point[0]
        # collect until first colon on the same or next line
        sig_lines = []
        for i in range(start, min(start + 5, len(lines))):
            sig_lines.append(lines[i])
            if ":" in lines[i]:
                break
        return " ".join(l.strip() for l in sig_lines)

    def _visit(node: Any, parent_kind: str | None = None) -> None:
        kind: str | None = None
        if node.type in ("function_definition", "async_function_definition"):
            kind = "method" if parent_kind == "class" else "function"
        elif node.type == "class_definition":
            kind = "class"

        if kind:
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                sig = _signature_line(node)
                doc = _first_string_in_body(node, source)
                is_exported = not name.startswith("_")
                results.append(Symbol(
                    name=name,
                    kind=kind,
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    signature=sig,
                    docstring=doc,
                    is_exported=is_exported,
                ))
                for child in node.children:
                    _visit(child, parent_kind=kind)
                return

        # Module-level assignments for variables/constants
        if node.type == "module":
            for child in node.children:
                if child.type == "expression_statement":
                    for inner in child.children:
                        if inner.type == "assignment":
                            lhs = inner.child_by_field_name("left")
                            if lhs and lhs.type == "identifier":
                                vname = _node_text(lhs, source)
                                vkind = "const" if vname.isupper() else "variable"
                                results.append(Symbol(
                                    name=vname,
                                    kind=vkind,
                                    file_path=file_path,
                                    line_start=inner.start_point[0] + 1,
                                    line_end=inner.end_point[0] + 1,
                                    signature=_node_text(inner, source).split("\n")[0],
                                    docstring=None,
                                    is_exported=not vname.startswith("_"),
                                ))

        for child in node.children:
            _visit(child, parent_kind=parent_kind)

    _visit(root)
    return results


def _extract_imports(root: Any, source: bytes, file_path: str, repo_path: str) -> list[Import]:
    results: list[Import] = []

    def _resolve_relative(module: str, is_relative: bool) -> str:
        if not is_relative:
            return module
        # count leading dots
        dots = len(module) - len(module.lstrip("."))
        rel_module = module.lstrip(".")
        base = Path(file_path).parent
        for _ in range(dots - 1):
            base = base.parent
        if rel_module:
            resolved = base / rel_module.replace(".", "/")
        else:
            resolved = base
        try:
            return str(resolved.relative_to(repo_path)).replace("\\", "/")
        except ValueError:
            return module

    def _visit(node: Any) -> None:
        if node.type == "import_statement":
            # import X, import X as Y
            for child in node.children:
                if child.type == "dotted_name":
                    name = _node_text(child, source)
                    results.append(Import(
                        source_file=file_path,
                        imported_from=name,
                        imported_names=[],
                        is_relative=False,
                    ))
                elif child.type == "aliased_import":
                    mod_node = child.child_by_field_name("name")
                    alias_node = child.child_by_field_name("alias")
                    if mod_node:
                        mod = _node_text(mod_node, source)
                        alias = _node_text(alias_node, source) if alias_node else mod
                        results.append(Import(
                            source_file=file_path,
                            imported_from=mod,
                            imported_names=[alias],
                            is_relative=False,
                        ))

        elif node.type == "import_from_statement":
            # from X import Y, Z  /  from . import X
            mod_parts: list[str] = []
            dot_count = 0
            names: list[str] = []
            for child in node.children:
                if child.type == "relative_import":
                    dots = _node_text(child, source)
                    dot_count = len(dots)
                    mod_parts.append("." * dot_count)
                elif child.type in ("dotted_name", "identifier") and child.type != "import":
                    if _node_text(child, source) != "import":
                        mod_parts.append(_node_text(child, source))
                elif child.type == "import_from_as_names":
                    for n in child.children:
                        if n.type in ("dotted_name", "identifier") and _node_text(n, source) != ",":
                            names.append(_node_text(n, source).split(" as ")[0].strip())
                elif child.type == "aliased_import":
                    nm = child.child_by_field_name("name")
                    if nm:
                        names.append(_node_text(nm, source))
                elif child.type == "wildcard_import":
                    names = []  # wildcard

            raw_mod = "".join(mod_parts)
            is_rel = dot_count > 0 or raw_mod.startswith(".")
            resolved = _resolve_relative(raw_mod, is_rel)
            if raw_mod:
                results.append(Import(
                    source_file=file_path,
                    imported_from=resolved,
                    imported_names=names,
                    is_relative=is_rel,
                ))

        for child in node.children:
            _visit(child)

    _visit(root)
    return results


def parse(file_path: str, repo_path: str) -> tuple[list[Symbol], list[Import]]:
    try:
        lang = _get_py_lang()
        if lang is None:
            return [], []
        from tree_sitter import Parser
        source = Path(file_path).read_bytes()
        parser = Parser(lang)
        tree = parser.parse(source)
        symbols = _extract_symbols(tree.root_node, source, file_path)
        imports = _extract_imports(tree.root_node, source, file_path, repo_path)
        return symbols, imports
    except Exception:
        return [], []
