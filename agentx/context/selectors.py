from __future__ import annotations

from pathlib import Path

from agentx.context.budget import TokenBudget, estimate_tokens


def select_files(
    workspace: str,
    budget: TokenBudget,
    *,
    include_globs: list[str] | None = None,
    max_files: int = 20,
) -> list[tuple[str, str]]:
    """Return (rel_path, content) pairs for workspace files that fit the budget.

    Walks workspace, skips hidden dirs and common noise (.git, __pycache__, *.pyc).
    Prioritises smaller files. Returns as many as fit within the budget.
    """
    root = Path(workspace)
    globs = include_globs or ["**/*.py", "**/*.md", "**/*.toml", "**/*.txt"]

    candidates: list[tuple[int, str, str]] = []
    for pattern in globs:
        for p in root.glob(pattern):
            if any(part.startswith(".") or part == "__pycache__" for part in p.parts):
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = str(p.relative_to(root))
            tokens = estimate_tokens(content)
            candidates.append((tokens, rel, content))

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
