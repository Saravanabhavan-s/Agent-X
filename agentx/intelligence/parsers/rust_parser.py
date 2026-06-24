from __future__ import annotations

from pathlib import Path
from typing import Any

from agentx.intelligence.models import Import, Symbol

_RUST_LANG: Any | None = None


def _load_rust_language() -> Any | None:
    try:
        from tree_sitter import Language
        import tree_sitter_rust as tsrust
        return Language(tsrust.language())
    except Exception:
        return None


def _get_rust_lang() -> Any | None:
    global _RUST_LANG
    if _RUST_LANG is None:
        _RUST_LANG = _load_rust_language()
    return _RUST_LANG


def _node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _has_pub(node: Any, source: bytes) -> bool:
    for child in node.children:
        if child.type == "visibility_modifier":
            return True
    return False


def _sig_first_line(node: Any, source: bytes) -> str:
    return _node_text(node, source).split("\n")[0].strip()


def _extract_symbols(root: Any, source: bytes, file_path: str) -> list[Symbol]:
    results: list[Symbol] = []

    def _visit(node: Any, in_impl: bool = False) -> None:
        ntype = node.type

        if ntype == "function_item":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                kind = "method" if in_impl else "function"
                results.append(Symbol(
                    name=name,
                    kind=kind,
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    signature=_sig_first_line(node, source),
                    docstring=None,
                    is_exported=_has_pub(node, source),
                ))

        elif ntype in ("struct_item", "enum_item", "trait_item"):
            kind_map = {"struct_item": "struct", "enum_item": "variable", "trait_item": "interface"}
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                results.append(Symbol(
                    name=name,
                    kind=kind_map[ntype],
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    signature=_sig_first_line(node, source),
                    docstring=None,
                    is_exported=_has_pub(node, source),
                ))

        elif ntype == "impl_item":
            # Visit children as methods
            for child in node.children:
                _visit(child, in_impl=True)
            return

        elif ntype in ("const_item", "static_item"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                results.append(Symbol(
                    name=name,
                    kind="const",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    signature=_sig_first_line(node, source),
                    docstring=None,
                    is_exported=_has_pub(node, source),
                ))

        for child in node.children:
            _visit(child, in_impl=in_impl)

    _visit(root)
    return results


def _classify_use_path(path: str) -> str:
    """Return 'stdlib', 'local', or 'external'."""
    if path.startswith("std::") or path.startswith("core::") or path.startswith("alloc::"):
        return "stdlib"
    if path.startswith("crate::") or path.startswith("super::") or path.startswith("self::"):
        return "local"
    return "external"


def _extract_imports(root: Any, source: bytes, file_path: str) -> list[Import]:
    results: list[Import] = []

    def _visit(node: Any) -> None:
        if node.type == "use_declaration":
            path_text = _node_text(node, source).strip().removeprefix("use ").removesuffix(";").strip()
            kind = _classify_use_path(path_text)
            is_relative = kind == "local"
            results.append(Import(
                source_file=file_path,
                imported_from=path_text,
                imported_names=[],
                is_relative=is_relative,
            ))
        for child in node.children:
            _visit(child)

    _visit(root)
    return results


def parse(file_path: str, repo_path: str) -> tuple[list[Symbol], list[Import]]:
    try:
        lang = _get_rust_lang()
        if lang is None:
            return [], []
        from tree_sitter import Parser
        source = Path(file_path).read_bytes()
        parser = Parser(lang)
        tree = parser.parse(source)
        symbols = _extract_symbols(tree.root_node, source, file_path)
        imports = _extract_imports(tree.root_node, source, file_path)
        return symbols, imports
    except Exception:
        return [], []
