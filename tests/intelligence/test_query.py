from __future__ import annotations

from pathlib import Path

from agentx.intelligence.models import DepEdge, DepGraph, Import, Symbol, SymbolIndex
from agentx.intelligence.query import IntelligenceQuery
from agentx.context.budget import estimate_tokens


def _sym(name: str, file_path: str, is_exported: bool = True) -> Symbol:
    return Symbol(
        name=name, kind="function", file_path=file_path,
        line_start=1, line_end=5, signature=f"def {name}()", docstring=None, is_exported=is_exported,
    )


def _build_query(tmp_path: Path) -> tuple[IntelligenceQuery, str, str, str]:
    repo = str(tmp_path)
    core = str(tmp_path / "core.py")
    consumer = str(tmp_path / "consumer.py")
    orphan = str(tmp_path / "orphan.py")

    symbols = [_sym("core_fn", core), _sym("consumer_fn", consumer), _sym("orphan_fn", orphan)]
    imports = [Import(source_file=consumer, imported_from=core, imported_names=[], is_relative=False)]
    idx = SymbolIndex(repo_path=repo, symbols=symbols, imports=imports)

    edges = [DepEdge(from_file=consumer, to_file=core, to_module="core", is_external=False)]
    graph = DepGraph(edges=edges)

    return IntelligenceQuery(idx, graph), core, consumer, orphan


def test_find_symbol(tmp_path: Path) -> None:
    q, core, consumer, _ = _build_query(tmp_path)
    results = q.find_symbol("core_fn")
    assert len(results) == 1
    assert results[0].name == "core_fn"


def test_find_in_file(tmp_path: Path) -> None:
    q, core, consumer, _ = _build_query(tmp_path)
    syms = q.find_in_file(core)
    assert any(s.name == "core_fn" for s in syms)


def test_what_imports(tmp_path: Path) -> None:
    q, core, consumer, _ = _build_query(tmp_path)
    importers = q.what_imports(core)
    assert consumer in importers


def test_what_does_it_import(tmp_path: Path) -> None:
    q, core, consumer, _ = _build_query(tmp_path)
    deps = q.what_does_it_import(consumer)
    assert core in deps


def test_impact_of_change(tmp_path: Path) -> None:
    q, core, consumer, _ = _build_query(tmp_path)
    report = q.impact_of_change(core)
    assert consumer in report.directly_affected
    assert report.risk_level in ("low", "medium", "high")


def test_dead_files(tmp_path: Path) -> None:
    q, core, consumer, orphan = _build_query(tmp_path)
    dead = q.dead_files()
    # orphan is not imported by anything
    assert orphan in dead
    # core is imported by consumer — not dead
    assert core not in dead


def test_format_for_context_per_file_within_budget(tmp_path: Path) -> None:
    q, core, _, _ = _build_query(tmp_path)
    result = q.format_for_context(core)
    assert isinstance(result, str)
    assert estimate_tokens(result) <= 800


def test_format_for_context_repo_summary_within_budget(tmp_path: Path) -> None:
    q, _, _, _ = _build_query(tmp_path)
    result = q.format_for_context()
    assert isinstance(result, str)
    assert estimate_tokens(result) <= 800


def test_missing_deps(tmp_path: Path) -> None:
    repo = str(tmp_path)
    imports = [
        Import(source_file=str(tmp_path / "a.py"), imported_from="requests", imported_names=[], is_relative=False),
    ]
    idx = SymbolIndex(repo_path=repo, symbols=[], imports=imports)
    edges = [DepEdge(from_file=str(tmp_path / "a.py"), to_file="requests", to_module="requests", is_external=True)]
    graph = DepGraph(edges=edges)
    q = IntelligenceQuery(idx, graph)
    missing = q.missing_deps()
    assert "requests" in missing
