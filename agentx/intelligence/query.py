from __future__ import annotations

from pathlib import Path

from agentx.intelligence.impact import ImpactAnalyzer
from agentx.intelligence.models import DepGraph, ImpactReport, Symbol, SymbolIndex

_MAX_CONTEXT_TOKENS = 800


class IntelligenceQuery:
    def __init__(self, symbol_index: SymbolIndex, dep_graph: DepGraph) -> None:
        self._index = symbol_index
        self._graph = dep_graph
        self._analyzer = ImpactAnalyzer()

    def find_symbol(self, name: str) -> list[Symbol]:
        return self._index.find(name)

    def find_in_file(self, file_path: str) -> list[Symbol]:
        abs_path = self._abs(file_path)
        return self._index.in_file(abs_path)

    def what_imports(self, file_path: str) -> list[str]:
        """Files that import the given file (dependents)."""
        abs_path = self._abs(file_path)
        return self._graph.dependents_of(abs_path)

    def what_does_it_import(self, file_path: str) -> list[str]:
        """Files that the given file imports (dependencies)."""
        abs_path = self._abs(file_path)
        return self._graph.dependencies_of(abs_path)

    def impact_of_change(self, file_path: str) -> ImpactReport:
        abs_path = self._abs(file_path)
        return self._analyzer.analyze(abs_path, self._graph, self._index)

    def missing_deps(self) -> list[str]:
        """External packages imported but not declared in any manifest."""
        externals = self._graph.external_packages()
        # Simple heuristic: return all external package roots
        roots: set[str] = set()
        for pkg in externals:
            root = pkg.split("/")[0].split("::")[0]
            roots.add(root)
        return sorted(roots)

    def dead_files(self) -> list[str]:
        """Files not imported by anything and not listed as entry points."""
        entry_points: set[str] = set()
        # Try to get entry_points from classification stored on index
        # (passed through if available)
        if hasattr(self._index, "_classification") and self._index._classification:  # type: ignore[union-attr]
            for ep in getattr(self._index._classification, "entry_points", []):
                entry_points.add(ep)

        # All files that appear as source in imports
        all_files_with_symbols: set[str] = {s.file_path for s in self._index.symbols}
        # Files that are imported by something
        imported: set[str] = set()
        for e in self._graph.edges:
            if not e.is_external:
                imported.add(e.to_file)

        dead = []
        for f in all_files_with_symbols:
            fname = Path(f).name
            is_entry = any(ep in f or fname == ep for ep in entry_points)
            if f not in imported and not is_entry:
                dead.append(f)
        return sorted(dead)

    def format_for_context(self, file_path: str | None = None) -> str:
        """Compact text summary for the context window. Max 800 tokens."""
        from agentx.context.budget import estimate_tokens

        if file_path is not None:
            return self._format_file(file_path)
        else:
            return self._format_repo_summary()

    def _format_file(self, file_path: str) -> str:
        from agentx.context.budget import estimate_tokens

        abs_path = self._abs(file_path)
        rel = self._rel(abs_path)
        symbols = self._index.in_file(abs_path)
        dependents = self._graph.dependents_of(abs_path)
        deps = self._graph.dependencies_of(abs_path)

        lines: list[str] = [f"### {rel}"]
        if symbols:
            lines.append(f"Symbols ({len(symbols)}):")
            for s in symbols[:30]:
                exported = "+" if s.is_exported else "-"
                lines.append(f"  {exported}{s.kind} {s.name} L{s.line_start}")
        if deps:
            lines.append(f"Imports: {', '.join(self._rel(d) for d in deps[:10])}")
        if dependents:
            lines.append(f"Imported by: {', '.join(self._rel(d) for d in dependents[:10])}")

        result = "\n".join(lines)
        if estimate_tokens(result) > _MAX_CONTEXT_TOKENS:
            # Truncate symbols list
            lines2: list[str] = [f"### {rel}"]
            lines2.append(f"Symbols: {len(symbols)} total")
            if deps:
                lines2.append(f"Imports: {len(deps)} files")
            if dependents:
                lines2.append(f"Imported by: {len(dependents)} files")
            result = "\n".join(lines2)
        return result

    def _format_repo_summary(self) -> str:
        from agentx.context.budget import estimate_tokens

        total_symbols = len(self._index.symbols)
        total_edges = len(self._graph.edges)
        external = self._graph.external_packages()
        files: set[str] = {s.file_path for s in self._index.symbols}

        lines = [
            "### Repo Intelligence Summary",
            f"Files: {len(files)}  Symbols: {total_symbols}  Dep edges: {total_edges}",
        ]
        if external:
            lines.append(f"External packages: {', '.join(sorted(external)[:15])}")

        # Top files by dependents
        dep_counts: dict[str, int] = {}
        for e in self._graph.edges:
            if not e.is_external:
                dep_counts[e.to_file] = dep_counts.get(e.to_file, 0) + 1
        if dep_counts:
            top = sorted(dep_counts.items(), key=lambda x: -x[1])[:5]
            lines.append("Most imported:")
            for f, cnt in top:
                lines.append(f"  {self._rel(f)} ({cnt} importers)")

        result = "\n".join(lines)
        if estimate_tokens(result) > _MAX_CONTEXT_TOKENS:
            result = "\n".join(lines[:4])
        return result

    def _abs(self, file_path: str) -> str:
        p = Path(file_path)
        if not p.is_absolute():
            return str(Path(self._index.repo_path) / file_path)
        return str(p)

    def _rel(self, file_path: str) -> str:
        try:
            return str(Path(file_path).relative_to(self._index.repo_path)).replace("\\", "/")
        except ValueError:
            return file_path
