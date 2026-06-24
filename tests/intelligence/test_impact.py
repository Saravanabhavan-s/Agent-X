from __future__ import annotations

from agentx.intelligence.impact import ImpactAnalyzer
from agentx.intelligence.models import DepEdge, DepGraph, Symbol, SymbolIndex


def _sym(name: str, file_path: str) -> Symbol:
    return Symbol(
        name=name, kind="function", file_path=file_path,
        line_start=1, line_end=5, signature=f"def {name}()", docstring=None, is_exported=True,
    )


def _index(repo: str, syms: list[Symbol]) -> SymbolIndex:
    return SymbolIndex(repo_path=repo, symbols=syms, imports=[])


def test_low_risk_no_dependents(tmp_path) -> None:
    changed = str(tmp_path / "a.py")
    graph = DepGraph(edges=[])
    idx = _index(str(tmp_path), [_sym("func_a", changed)])
    report = ImpactAnalyzer().analyze(changed, graph, idx)
    assert report.risk_level == "low"
    assert report.directly_affected == []
    assert report.transitively_affected == []


def test_medium_risk(tmp_path) -> None:
    changed = str(tmp_path / "core.py")
    b = str(tmp_path / "b.py")
    c = str(tmp_path / "c.py")
    edges = [
        DepEdge(from_file=b, to_file=changed, to_module="core", is_external=False),
        DepEdge(from_file=c, to_file=changed, to_module="core", is_external=False),
    ]
    graph = DepGraph(edges=edges)
    idx = _index(str(tmp_path), [_sym("core_func", changed), _sym("b_func", b)])
    report = ImpactAnalyzer().analyze(changed, graph, idx)
    assert report.risk_level == "medium"
    assert changed not in report.directly_affected
    assert b in report.directly_affected or c in report.directly_affected


def test_high_risk_many_direct(tmp_path) -> None:
    changed = str(tmp_path / "shared.py")
    files = [str(tmp_path / f"f{i}.py") for i in range(7)]
    edges = [DepEdge(from_file=f, to_file=changed, to_module="shared", is_external=False) for f in files]
    graph = DepGraph(edges=edges)
    idx = _index(str(tmp_path), [_sym("shared_fn", changed)])
    report = ImpactAnalyzer().analyze(changed, graph, idx)
    assert report.risk_level == "high"
    assert len(report.directly_affected) == 7


def test_transitive_bfs_depth_3(tmp_path) -> None:
    a = str(tmp_path / "a.py")
    b = str(tmp_path / "b.py")
    c = str(tmp_path / "c.py")
    d = str(tmp_path / "d.py")
    e = str(tmp_path / "e.py")
    edges = [
        DepEdge(from_file=b, to_file=a, to_module="a", is_external=False),
        DepEdge(from_file=c, to_file=b, to_module="b", is_external=False),
        DepEdge(from_file=d, to_file=c, to_module="c", is_external=False),
        DepEdge(from_file=e, to_file=d, to_module="d", is_external=False),
    ]
    graph = DepGraph(edges=edges)
    idx = _index(str(tmp_path), [])
    report = ImpactAnalyzer().analyze(a, graph, idx)
    # direct: b; depth1→c, depth2→d, depth3: stop (e should NOT be included)
    assert b in report.directly_affected
    all_affected = set(report.directly_affected) | set(report.transitively_affected)
    assert e not in all_affected  # depth 4, beyond cap


def test_affected_symbols_in_direct_files(tmp_path) -> None:
    changed = str(tmp_path / "lib.py")
    consumer = str(tmp_path / "consumer.py")
    edges = [DepEdge(from_file=consumer, to_file=changed, to_module="lib", is_external=False)]
    graph = DepGraph(edges=edges)
    syms = [_sym("lib_fn", changed), _sym("consumer_fn", consumer)]
    idx = _index(str(tmp_path), syms)
    report = ImpactAnalyzer().analyze(changed, graph, idx)
    affected_names = {s.name for s in report.affected_symbols}
    assert "consumer_fn" in affected_names
