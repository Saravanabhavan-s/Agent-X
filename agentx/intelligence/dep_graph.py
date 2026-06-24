from __future__ import annotations

from pathlib import Path

from agentx.intelligence.models import DepEdge, DepGraph, SymbolIndex

_TS_EXTS = (".ts", ".tsx", ".js", ".jsx")


def _resolve_python_import(imported_from: str, source_file: str, repo_path: str) -> str | None:
    """Try to resolve a Python import string to an absolute file path."""
    repo = Path(repo_path)

    mod_as_path = imported_from.replace(".", "/")
    candidates = [
        repo / f"{mod_as_path}.py",
        repo / mod_as_path / "__init__.py",
    ]
    for c in candidates:
        if c.exists():
            return str(c.resolve())

    # relative import: was resolved to a path string already by python_parser
    if "/" in imported_from or imported_from.startswith("."):
        stripped = imported_from.lstrip("./")
        candidates2 = [
            repo / f"{stripped}.py",
            repo / stripped / "__init__.py",
        ]
        for c in candidates2:
            if c.exists():
                return str(c.resolve())
    return None


def _resolve_ts_import(imported_from: str, source_file: str, repo_path: str) -> str | None:
    """Try to resolve a TS/JS import string to an absolute file path."""
    if not (imported_from.startswith(".") or imported_from.startswith("/")):
        return None

    source = Path(source_file)
    repo = Path(repo_path)
    base = source.parent if imported_from.startswith(".") else repo

    target = (base / imported_from).resolve()
    # Try with various extensions
    for ext in (".ts", ".tsx", ".js", ".jsx"):
        p = target.with_suffix(ext)
        if p.exists():
            return str(p.resolve())
    # Try index files
    for ext in (".ts", ".tsx", ".js", ".jsx"):
        p = target / f"index{ext}"
        if p.exists():
            return str(p.resolve())
    return None


def _resolve_go_import(imported_from: str, repo_path: str, module_name: str | None) -> str | None:
    if not module_name:
        return None
    if not imported_from.startswith(module_name):
        return None
    rel = imported_from[len(module_name):].lstrip("/")
    pkg_dir = Path(repo_path) / rel
    if pkg_dir.is_dir():
        return str(pkg_dir.resolve())
    return None


def _resolve_rust_import(imported_from: str, repo_path: str, source_file: str) -> str | None:
    if not imported_from.startswith("crate::"):
        return None
    rel = imported_from[len("crate::"):].replace("::", "/")
    repo = Path(repo_path)
    for candidate in [
        repo / "src" / f"{rel}.rs",
        repo / "src" / rel / "mod.rs",
    ]:
        if candidate.exists():
            return str(candidate.resolve())
    return None


def _read_go_module_name(repo_path: str) -> str | None:
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


class DependencyGraphBuilder:
    def build(self, symbol_index: SymbolIndex) -> DepGraph:
        repo_path = symbol_index.repo_path
        go_module = _read_go_module_name(repo_path)
        edges: list[DepEdge] = []

        for imp in symbol_index.imports:
            src = imp.source_file
            raw = imp.imported_from
            ext = Path(src).suffix.lower()
            resolved: str | None = None
            is_external = False

            if ext == ".py":
                resolved = _resolve_python_import(raw, src, repo_path)
                is_external = resolved is None and not imp.is_relative
            elif ext in _TS_EXTS:
                resolved = _resolve_ts_import(raw, src, repo_path)
                is_external = resolved is None and not (raw.startswith(".") or raw.startswith("/"))
            elif ext == ".go":
                resolved = _resolve_go_import(raw, repo_path, go_module)
                is_external = resolved is None
            elif ext == ".rs":
                resolved = _resolve_rust_import(raw, repo_path, src)
                is_external = resolved is None and not imp.is_relative
            else:
                # Generic: mark as external unless relative
                is_external = not imp.is_relative

            to_file = resolved if resolved else raw
            edges.append(DepEdge(
                from_file=src,
                to_file=to_file,
                to_module=raw,
                is_external=is_external,
            ))

        return DepGraph(edges=edges)
