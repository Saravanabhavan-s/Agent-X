from __future__ import annotations

from pathlib import Path
from typing import Any

from agentx.intelligence.models import Import, Symbol

_GO_LANG: Any | None = None


def _load_go_language() -> Any | None:
    try:
        from tree_sitter import Language
        import tree_sitter_go as tsgo
        return Language(tsgo.language())
    except Exception:
        return None


def _get_go_lang() -> Any | None:
    global _GO_LANG
    if _GO_LANG is None:
        _GO_LANG = _load_go_language()
    return _GO_LANG


def _node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _read_go_module(repo_path: str) -> str | None:
    """Read module name from go.mod in repo root."""
    go_mod = Path(repo_path) / "go.mod"
    if not go_mod.exists():
        return None
    try:
        for line in go_mod.read_text(encoding="utf-8").splitlines():
            if line.startswith("module "):
                return line[len("module "):].strip()
    except Exception:
        pass
    return None


def _extract_symbols(root: Any, source: bytes, file_path: str) -> list[Symbol]:
    results: list[Symbol] = []

    def _sig_first_line(node: Any) -> str:
        return _node_text(node, source).split("\n")[0].strip()

    def _visit(node: Any) -> None:
        ntype = node.type

        if ntype == "function_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                is_exported = name[0].isupper() if name else False
                results.append(Symbol(
                    name=name,
                    kind="function",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    signature=_sig_first_line(node),
                    docstring=None,
                    is_exported=is_exported,
                ))

        elif ntype == "method_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                is_exported = name[0].isupper() if name else False
                results.append(Symbol(
                    name=name,
                    kind="method",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    signature=_sig_first_line(node),
                    docstring=None,
                    is_exported=is_exported,
                ))

        elif ntype == "type_declaration":
            for spec in node.children:
                if spec.type == "type_spec":
                    name_node = spec.child_by_field_name("name")
                    type_node = spec.child_by_field_name("type")
                    if name_node and type_node:
                        name = _node_text(name_node, source)
                        kind = "struct" if type_node.type == "struct_type" else (
                            "interface" if type_node.type == "interface_type" else "variable"
                        )
                        is_exported = name[0].isupper() if name else False
                        results.append(Symbol(
                            name=name,
                            kind=kind,
                            file_path=file_path,
                            line_start=spec.start_point[0] + 1,
                            line_end=spec.end_point[0] + 1,
                            signature=_sig_first_line(spec),
                            docstring=None,
                            is_exported=is_exported,
                        ))

        elif ntype in ("const_declaration", "var_declaration"):
            kind = "const" if ntype == "const_declaration" else "variable"
            for spec in node.children:
                if spec.type in ("const_spec", "var_spec"):
                    for child in spec.children:
                        if child.type == "identifier":
                            name = _node_text(child, source)
                            is_exported = name[0].isupper() if name else False
                            results.append(Symbol(
                                name=name,
                                kind=kind,
                                file_path=file_path,
                                line_start=child.start_point[0] + 1,
                                line_end=child.end_point[0] + 1,
                                signature=name,
                                docstring=None,
                                is_exported=is_exported,
                            ))
                            break  # only first identifier = name

        for child in node.children:
            _visit(child)

    _visit(root)
    return results


def _classify_import(path: str, module_name: str | None) -> bool:
    """Return True if path is an external import (not stdlib, not local)."""
    STDLIB_PREFIXES = (
        "fmt", "os", "io", "net", "http", "math", "sort", "sync",
        "strings", "strconv", "bytes", "errors", "time", "context",
        "encoding", "crypto", "path", "regexp", "runtime", "testing",
        "log", "bufio", "flag", "reflect", "unicode", "archive",
        "compress", "container", "database", "debug", "embed",
        "expvar", "go", "hash", "html", "image", "index", "mime",
        "plugin", "syscall", "text", "unsafe",
    )
    first_seg = path.split("/")[0]
    if first_seg in STDLIB_PREFIXES:
        return False  # stdlib
    if module_name and path.startswith(module_name):
        return False  # local
    return True  # external


def _extract_imports(root: Any, source: bytes, file_path: str, repo_path: str) -> list[Import]:
    results: list[Import] = []
    module_name = _read_go_module(repo_path)

    def _add_import(path_text: str, alias: str | None = None) -> None:
        is_ext = _classify_import(path_text, module_name)
        names = [alias] if alias else []
        results.append(Import(
            source_file=file_path,
            imported_from=path_text,
            imported_names=names,
            is_relative=False,
        ))

    def _visit(node: Any) -> None:
        if node.type == "import_declaration":
            for child in node.children:
                if child.type == "import_spec":
                    path_node = child.child_by_field_name("path")
                    alias_node = child.child_by_field_name("name")
                    if path_node:
                        path_text = _node_text(path_node, source).strip('"')
                        alias = _node_text(alias_node, source) if alias_node else None
                        _add_import(path_text, alias)
                elif child.type == "import_spec_list":
                    for spec in child.children:
                        if spec.type == "import_spec":
                            path_node = spec.child_by_field_name("path")
                            alias_node = spec.child_by_field_name("name")
                            if path_node:
                                path_text = _node_text(path_node, source).strip('"')
                                alias = _node_text(alias_node, source) if alias_node else None
                                _add_import(path_text, alias)
        for child in node.children:
            _visit(child)

    _visit(root)
    return results


def parse(file_path: str, repo_path: str) -> tuple[list[Symbol], list[Import]]:
    try:
        lang = _get_go_lang()
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
