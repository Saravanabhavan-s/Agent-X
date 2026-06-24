from __future__ import annotations

from pathlib import Path
from typing import Any

from agentx.intelligence.models import Import, Symbol

# Shared between .ts and .tsx
_TS_LANG: Any | None = None
_TSX_LANG: Any | None = None


def _load_ts_languages() -> tuple[Any | None, Any | None]:
    try:
        from tree_sitter import Language
        import tree_sitter_typescript as tsts
        return Language(tsts.language_typescript()), Language(tsts.language_tsx())
    except Exception:
        return None, None


def _get_ts_lang(ext: str) -> Any | None:
    global _TS_LANG, _TSX_LANG
    if _TS_LANG is None:
        _TS_LANG, _TSX_LANG = _load_ts_languages()
    return _TSX_LANG if ext == ".tsx" else _TS_LANG


def _node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _has_export(node: Any, source: bytes) -> bool:
    """True if the node or its preceding sibling has 'export' keyword."""
    text = _node_text(node, source)
    return text.startswith("export ")


def _signature_first_line(node: Any, source: bytes) -> str:
    text = _node_text(node, source)
    return text.split("\n")[0].strip()


def _extract_symbols(root: Any, source: bytes, file_path: str) -> list[Symbol]:
    results: list[Symbol] = []

    FUNC_TYPES = {
        "function_declaration", "function_expression", "generator_function_declaration",
    }
    CLASS_TYPES = {"class_declaration", "class_expression"}
    METHOD_TYPES = {"method_definition", "public_field_definition"}
    INTERFACE_TYPES = {"interface_declaration"}
    TYPE_ALIAS_TYPES = {"type_alias_declaration"}
    VAR_TYPES = {"variable_declarator"}

    def _exported(node: Any) -> bool:
        parent = getattr(node, "parent", None)
        if parent is None:
            return False
        ptext = _node_text(parent, source)
        return ptext.startswith("export ")

    def _visit(node: Any, parent_kind: str | None = None) -> None:
        ntype = node.type
        kind: str | None = None
        name: str | None = None
        is_exported = False

        if ntype in FUNC_TYPES:
            kind = "method" if parent_kind == "class" else "function"
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
            is_exported = _exported(node)

        elif ntype == "arrow_function":
            # Only capture if assigned to a const: parent is variable_declarator
            parent = getattr(node, "parent", None)
            if parent and parent.type == "variable_declarator":
                kind = "function"
                nm = parent.child_by_field_name("name")
                if nm:
                    name = _node_text(nm, source)
                grandparent = getattr(parent, "parent", None)
                if grandparent:
                    is_exported = _exported(grandparent)

        elif ntype in CLASS_TYPES:
            kind = "class"
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
            is_exported = _exported(node)

        elif ntype in METHOD_TYPES:
            kind = "method"
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
            is_exported = True  # methods in exported classes

        elif ntype in INTERFACE_TYPES:
            kind = "interface"
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
            is_exported = _exported(node)

        elif ntype in TYPE_ALIAS_TYPES:
            kind = "interface"  # treat type aliases same as interfaces
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
            is_exported = _exported(node)

        elif ntype == "variable_declaration":
            # exported const X = ... at module level
            parent = getattr(node, "parent", None)
            is_mod_level = parent is not None and parent.type in ("program", "module", "export_statement")
            if is_mod_level:
                is_exported = _exported(node)
                for child in node.children:
                    if child.type == "variable_declarator":
                        nm_node = child.child_by_field_name("name")
                        val_node = child.child_by_field_name("value")
                        if nm_node and val_node and val_node.type != "arrow_function":
                            vname = _node_text(nm_node, source)
                            results.append(Symbol(
                                name=vname,
                                kind="variable",
                                file_path=file_path,
                                line_start=child.start_point[0] + 1,
                                line_end=child.end_point[0] + 1,
                                signature=_signature_first_line(child, source),
                                docstring=None,
                                is_exported=is_exported,
                            ))

        if kind and name:
            results.append(Symbol(
                name=name,
                kind=kind,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=_signature_first_line(node, source),
                docstring=None,
                is_exported=is_exported,
            ))
            for child in node.children:
                _visit(child, parent_kind=kind)
            return

        for child in node.children:
            _visit(child, parent_kind=parent_kind)

    _visit(root)
    return results


def _extract_imports(root: Any, source: bytes, file_path: str) -> list[Import]:
    results: list[Import] = []

    def _is_relative(mod: str) -> bool:
        return mod.startswith(".") or mod.startswith("/")

    def _visit(node: Any) -> None:
        ntype = node.type

        if ntype == "import_statement":
            # import { X, Y } from "mod" / import X from "mod" / import * as X from "mod"
            mod_node = node.child_by_field_name("source")
            if mod_node:
                mod = _node_text(mod_node, source).strip("\"'")
                names: list[str] = []
                for child in node.children:
                    if child.type == "import_clause":
                        for inner in child.children:
                            if inner.type == "named_imports":
                                for nm in inner.children:
                                    if nm.type == "import_specifier":
                                        nm_node = nm.child_by_field_name("name")
                                        if nm_node:
                                            names.append(_node_text(nm_node, source))
                            elif inner.type == "identifier":
                                names.append(_node_text(inner, source))
                            elif inner.type == "namespace_import":
                                pass  # import * as X
                results.append(Import(
                    source_file=file_path,
                    imported_from=mod,
                    imported_names=names,
                    is_relative=_is_relative(mod),
                ))

        elif ntype == "call_expression":
            # require("module")
            fn_node = node.child_by_field_name("function")
            args_node = node.child_by_field_name("arguments")
            if fn_node and _node_text(fn_node, source) == "require" and args_node:
                for arg in args_node.children:
                    if arg.type == "string":
                        mod = _node_text(arg, source).strip("\"'")
                        results.append(Import(
                            source_file=file_path,
                            imported_from=mod,
                            imported_names=[],
                            is_relative=_is_relative(mod),
                        ))

        for child in node.children:
            _visit(child)

    _visit(root)
    return results


def parse(file_path: str, repo_path: str, ext: str | None = None) -> tuple[list[Symbol], list[Import]]:
    try:
        p = Path(file_path)
        file_ext = ext or p.suffix.lower()
        lang = _get_ts_lang(file_ext)
        if lang is None:
            return [], []
        from tree_sitter import Parser
        source = p.read_bytes()
        parser = Parser(lang)
        tree = parser.parse(source)
        symbols = _extract_symbols(tree.root_node, source, file_path)
        imports = _extract_imports(tree.root_node, source, file_path)
        return symbols, imports
    except Exception:
        return [], []
