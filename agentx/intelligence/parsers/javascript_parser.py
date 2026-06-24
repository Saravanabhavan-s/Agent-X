from __future__ import annotations

from pathlib import Path
from typing import Any

from agentx.intelligence.models import Import, Symbol

_JS_LANG: Any | None = None


def _load_js_language() -> Any | None:
    try:
        from tree_sitter import Language
        import tree_sitter_javascript as tsjs
        return Language(tsjs.language())
    except Exception:
        return None


def _get_js_lang() -> Any | None:
    global _JS_LANG
    if _JS_LANG is None:
        _JS_LANG = _load_js_language()
    return _JS_LANG


def _node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _extract_commonjs_exports(root: Any, source: bytes, file_path: str) -> list[Symbol]:
    """Extract CommonJS: module.exports = {X, Y} and exports.X = ..."""
    results: list[Symbol] = []

    def _visit(node: Any) -> None:
        if node.type == "assignment_expression":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left and right:
                left_text = _node_text(left, source)
                # exports.X = ...
                if left_text.startswith("exports."):
                    name = left_text[len("exports."):]
                    results.append(Symbol(
                        name=name,
                        kind="variable",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        signature=_node_text(node, source).split("\n")[0].strip(),
                        docstring=None,
                        is_exported=True,
                    ))
                # module.exports = { X, Y }
                elif left_text == "module.exports" and right.type == "object":
                    for prop in right.children:
                        if prop.type in ("pair", "shorthand_property_identifier"):
                            key = prop.child_by_field_name("key") or prop
                            if key:
                                name = _node_text(key, source)
                                results.append(Symbol(
                                    name=name,
                                    kind="variable",
                                    file_path=file_path,
                                    line_start=prop.start_point[0] + 1,
                                    line_end=prop.end_point[0] + 1,
                                    signature=name,
                                    docstring=None,
                                    is_exported=True,
                                ))
        for child in node.children:
            _visit(child)

    _visit(root)
    return results


def parse(file_path: str, repo_path: str) -> tuple[list[Symbol], list[Import]]:
    try:
        lang = _get_js_lang()
        if lang is None:
            return [], []
        from tree_sitter import Parser

        # Reuse TS parser logic but with JS grammar
        from agentx.intelligence.parsers.typescript_parser import (
            _extract_imports,
            _extract_symbols,
        )

        source = Path(file_path).read_bytes()
        parser = Parser(lang)
        tree = parser.parse(source)

        symbols = _extract_symbols(tree.root_node, source, file_path)
        # Add CommonJS exports
        symbols += _extract_commonjs_exports(tree.root_node, source, file_path)

        imports = _extract_imports(tree.root_node, source, file_path)
        return symbols, imports
    except Exception:
        return [], []
