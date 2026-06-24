from __future__ import annotations

from pathlib import Path

from agentx.intelligence.dep_graph import DependencyGraphBuilder
from agentx.intelligence.models import Import, Symbol, SymbolIndex


def _make_index(repo_path: str, imports: list[Import]) -> SymbolIndex:
    return SymbolIndex(repo_path=repo_path, symbols=[], imports=imports)


def test_external_packages(tmp_path: Path) -> None:
    imports = [
        Import(source_file=str(tmp_path / "a.py"), imported_from="requests", imported_names=[], is_relative=False),
        Import(source_file=str(tmp_path / "a.py"), imported_from="os", imported_names=[], is_relative=False),
    ]
    idx = _make_index(str(tmp_path), imports)
    graph = DependencyGraphBuilder().build(idx)
    assert graph.external_packages()  # at least one external


def test_local_python_resolution(tmp_path: Path) -> None:
    # Create actual files so resolution can find them
    (tmp_path / "utils.py").write_text("def h(): pass\n")
    imports = [
        Import(
            source_file=str(tmp_path / "main.py"),
            imported_from="utils",
            imported_names=[],
            is_relative=False,
        ),
    ]
    idx = _make_index(str(tmp_path), imports)
    graph = DependencyGraphBuilder().build(idx)
    # utils.py should be resolved as local (not external)
    local_edges = [e for e in graph.edges if not e.is_external]
    assert len(local_edges) >= 1


def test_dependents_of(tmp_path: Path) -> None:
    (tmp_path / "utils.py").write_text("def h(): pass\n")
    utils_abs = str((tmp_path / "utils.py").resolve())
    main_abs = str((tmp_path / "main.py").resolve())
    imports = [
        Import(source_file=main_abs, imported_from="utils", imported_names=[], is_relative=False),
    ]
    idx = _make_index(str(tmp_path), imports)
    graph = DependencyGraphBuilder().build(idx)
    deps = graph.dependents_of(utils_abs)
    assert main_abs in deps or any("main" in d for d in deps)


def test_dependencies_of(tmp_path: Path) -> None:
    (tmp_path / "utils.py").write_text("def h(): pass\n")
    utils_abs = str((tmp_path / "utils.py").resolve())
    main_abs = str((tmp_path / "main.py").resolve())
    imports = [
        Import(source_file=main_abs, imported_from="utils", imported_names=[], is_relative=False),
    ]
    idx = _make_index(str(tmp_path), imports)
    graph = DependencyGraphBuilder().build(idx)
    deps = graph.dependencies_of(main_abs)
    assert utils_abs in deps or any("utils" in d for d in deps)


def test_has_cycle(tmp_path: Path) -> None:
    from agentx.intelligence.models import DepEdge, DepGraph
    a = str(tmp_path / "a.py")
    b = str(tmp_path / "b.py")
    edges = [
        DepEdge(from_file=a, to_file=b, to_module="b", is_external=False),
        DepEdge(from_file=b, to_file=a, to_module="a", is_external=False),
    ]
    graph = DepGraph(edges=edges)
    assert graph.has_cycle() is True


def test_no_cycle(tmp_path: Path) -> None:
    from agentx.intelligence.models import DepEdge, DepGraph
    a = str(tmp_path / "a.py")
    b = str(tmp_path / "b.py")
    edges = [
        DepEdge(from_file=a, to_file=b, to_module="b", is_external=False),
    ]
    graph = DepGraph(edges=edges)
    assert graph.has_cycle() is False


def test_ts_relative_resolution(tmp_path: Path) -> None:
    (tmp_path / "utils.ts").write_text("export function h() {}\n")
    imports = [
        Import(
            source_file=str(tmp_path / "main.ts"),
            imported_from="./utils",
            imported_names=[],
            is_relative=True,
        ),
    ]
    idx = _make_index(str(tmp_path), imports)
    graph = DependencyGraphBuilder().build(idx)
    local = [e for e in graph.edges if not e.is_external]
    assert len(local) >= 1
