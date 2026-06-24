from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class Symbol:
    name: str
    kind: str          # function|class|method|variable|interface|struct|const|unknown
    file_path: str
    line_start: int
    line_end: int
    signature: str     # full signature line
    docstring: str | None
    is_exported: bool  # public vs private


@dataclass
class Import:
    source_file: str
    imported_from: str       # module/package being imported
    imported_names: list[str]  # specific names; empty = wildcard/default
    is_relative: bool


@dataclass
class SymbolIndex:
    repo_path: str
    symbols: list[Symbol]
    imports: list[Import]
    built_at: float = field(default_factory=time.time)

    def find(self, name: str) -> list[Symbol]:
        return [s for s in self.symbols if s.name == name]

    def in_file(self, path: str) -> list[Symbol]:
        return [s for s in self.symbols if s.file_path == path]

    def exported(self) -> list[Symbol]:
        return [s for s in self.symbols if s.is_exported]


@dataclass
class DepEdge:
    from_file: str
    to_file: str         # resolved repo-relative path when possible
    to_module: str       # raw import string
    is_external: bool    # True = external package, not local file


@dataclass
class DepGraph:
    edges: list[DepEdge]

    def dependencies_of(self, file_path: str) -> list[str]:
        """Files that file_path imports (its dependencies)."""
        return list({e.to_file for e in self.edges if e.from_file == file_path and not e.is_external})

    def dependents_of(self, file_path: str) -> list[str]:
        """Files that import file_path (its consumers)."""
        return list({e.from_file for e in self.edges if e.to_file == file_path})

    def external_packages(self) -> list[str]:
        return list({e.to_module for e in self.edges if e.is_external})

    def has_cycle(self) -> bool:
        # DFS cycle detection
        graph: dict[str, list[str]] = {}
        for e in self.edges:
            if not e.is_external:
                graph.setdefault(e.from_file, []).append(e.to_file)

        visited: set[str] = set()
        in_stack: set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            in_stack.add(node)
            for nb in graph.get(node, []):
                if nb not in visited:
                    if dfs(nb):
                        return True
                elif nb in in_stack:
                    return True
            in_stack.discard(node)
            return False

        for n in list(graph):
            if n not in visited:
                if dfs(n):
                    return True
        return False


@dataclass
class ImpactReport:
    changed_file: str
    directly_affected: list[str]       # files that import changed_file
    transitively_affected: list[str]   # files that import those files (BFS depth 3)
    affected_symbols: list[Symbol]     # symbols in directly_affected that reference changed file
    risk_level: str                    # "low" | "medium" | "high"
    risk_reason: str
