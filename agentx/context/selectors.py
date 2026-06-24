from __future__ import annotations

from pathlib import Path

from agentx.context.budget import TokenBudget, estimate_tokens


def select_files(
    workspace: str,
    budget: TokenBudget,
    *,
    include_globs: list[str] | None = None,
    max_files: int = 20,
    intelligence=None,  # agentx.intelligence.query.IntelligenceQuery | None
) -> list[tuple[str, str]]:
    """Return (rel_path, content) pairs for workspace files that fit the budget.

    Walks workspace, skips hidden dirs and common noise (.git, __pycache__, *.pyc).
    Prioritises smaller files. Returns as many as fit within the budget.
    When intelligence is provided, expands candidates with one level of dep-graph
    neighbours so the model sees the right neighbourhood.
    """
    root = Path(workspace)
    globs = include_globs or ["**/*.py", "**/*.md", "**/*.toml", "**/*.txt"]

    seen_rels: set[str] = set()
    candidates: list[tuple[int, str, str]] = []

    def _add_path(p: Path) -> None:
        if any(part.startswith(".") or part == "__pycache__" for part in p.parts):
            return
        try:
            rel = str(p.relative_to(root))
        except ValueError:
            return
        if rel in seen_rels:
            return
        seen_rels.add(rel)
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        tokens = estimate_tokens(content)
        candidates.append((tokens, rel, content))

    for pattern in globs:
        for p in root.glob(pattern):
            _add_path(p)

    # Expand with intelligence neighbours (one level in + one level out)
    if intelligence is not None:
        try:
            neighbour_paths: set[str] = set()
            for _, rel, _ in candidates:
                for nb in intelligence.what_does_it_import(rel):
                    neighbour_paths.add(nb)
                for nb in intelligence.what_imports(rel):
                    neighbour_paths.add(nb)
            for nb_path in neighbour_paths:
                p = Path(nb_path)
                if not p.is_absolute():
                    p = root / nb_path
                if p.exists() and p.is_file():
                    _add_path(p)
        except Exception:
            pass

    # smallest first so we fit as many files as possible
    candidates.sort()
    selected: list[tuple[str, str]] = []
    for tokens, rel, content in candidates[:max_files]:
        if budget.fits(tokens):
            budget.consume(tokens)
            selected.append((rel, content))
    return selected


def select_history(
    history: list[str],
    budget: TokenBudget,
    *,
    keep_last: int = 6,
) -> list[str]:
    """Return the most-recent turns that fit within budget."""
    recent = history[-keep_last:]
    selected: list[str] = []
    for turn in reversed(recent):
        tokens = estimate_tokens(turn)
        if budget.fits(tokens):
            budget.consume(tokens)
            selected.insert(0, turn)
    return selected
