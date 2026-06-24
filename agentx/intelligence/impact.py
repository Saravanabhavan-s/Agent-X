from __future__ import annotations

from collections import deque

from agentx.intelligence.models import DepGraph, ImpactReport, Symbol, SymbolIndex


class ImpactAnalyzer:
    def analyze(
        self,
        changed_file: str,
        dep_graph: DepGraph,
        symbol_index: SymbolIndex,
        changed_symbols: list[str] | None = None,
    ) -> ImpactReport:
        directly_affected = dep_graph.dependents_of(changed_file)

        # BFS up to depth 3 for transitive
        transitive: list[str] = []
        visited: set[str] = {changed_file} | set(directly_affected)
        queue: deque[tuple[str, int]] = deque((f, 1) for f in directly_affected)
        while queue:
            file, depth = queue.popleft()
            if depth >= 3:
                continue
            for dep in dep_graph.dependents_of(file):
                if dep not in visited:
                    visited.add(dep)
                    transitive.append(dep)
                    queue.append((dep, depth + 1))

        # Symbols in directly_affected that import from changed_file
        affected_syms: list[Symbol] = []
        for afile in directly_affected:
            affected_syms.extend(symbol_index.in_file(afile))

        # Risk level
        n_direct = len(directly_affected)
        n_trans = len(transitive)
        if n_direct == 0:
            risk_level = "low"
            risk_reason = "no direct dependents"
        elif n_direct <= 5 and n_trans <= 20:
            risk_level = "medium"
            risk_reason = f"{n_direct} direct dependent(s)"
        else:
            risk_level = "high"
            if n_direct > 5:
                risk_reason = f"{n_direct} direct dependents (high fan-out)"
            else:
                risk_reason = f"{n_trans} transitive dependents"

        return ImpactReport(
            changed_file=changed_file,
            directly_affected=directly_affected,
            transitively_affected=transitive,
            affected_symbols=affected_syms,
            risk_level=risk_level,
            risk_reason=risk_reason,
        )
