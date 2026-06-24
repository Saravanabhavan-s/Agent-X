from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from agentx.intelligence.models import Import, Symbol, SymbolIndex

_SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", "vendor", ".tox", ".mypy_cache", "target",
    ".pytest_cache", ".ruff_cache",
})

_EXT_TO_LANG = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
}


def _parser_for_ext(ext: str):  # type: ignore[return]
    """Return the parse(file_path, repo_path) callable for a given extension."""
    lang = _EXT_TO_LANG.get(ext)
    if lang == "python":
        from agentx.intelligence.parsers.python_parser import parse
        return parse
    if lang == "typescript":
        from agentx.intelligence.parsers.typescript_parser import parse
        return parse
    if lang == "javascript":
        from agentx.intelligence.parsers.javascript_parser import parse
        return parse
    if lang == "go":
        from agentx.intelligence.parsers.go_parser import parse
        return parse
    if lang == "rust":
        from agentx.intelligence.parsers.rust_parser import parse
        return parse
    from agentx.intelligence.parsers.generic_parser import parse
    return parse


def _should_skip(path: Path) -> bool:
    for part in path.parts:
        if part in _SKIP_DIRS:
            return True
    return False


class SymbolIndexer:
    def __init__(self, repo_path: str, classification: Any) -> None:
        self.repo_path = repo_path
        self.classification = classification

    def build(self) -> SymbolIndex:
        root = Path(self.repo_path)
        all_symbols: list[Symbol] = []
        all_imports: list[Import] = []

        source_exts = frozenset(_EXT_TO_LANG) | {".rb", ".java", ".php", ".cs", ".cpp", ".c", ".kt", ".swift"}

        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if _should_skip(p.relative_to(root)):
                continue
            ext = p.suffix.lower()
            if ext not in source_exts:
                continue
            try:
                parser = _parser_for_ext(ext)
                syms, imps = parser(str(p), self.repo_path)
                all_symbols.extend(syms)
                all_imports.extend(imps)
            except Exception:
                pass

        return SymbolIndex(
            repo_path=self.repo_path,
            symbols=all_symbols,
            imports=all_imports,
            built_at=time.time(),
        )

    def build_for_file(self, file_path: str) -> tuple[list[Symbol], list[Import]]:
        """Parse a single file. Used for incremental updates after edits."""
        p = Path(file_path)
        if not p.exists():
            return [], []
        ext = p.suffix.lower()
        try:
            parser = _parser_for_ext(ext)
            return parser(file_path, self.repo_path)
        except Exception:
            return [], []

    def update_file(self, index: SymbolIndex, rel_path: str) -> None:
        """In-place incremental update: re-parse one file, replace its entries."""
        abs_path = str(Path(self.repo_path) / rel_path)
        # Remove old entries for this file
        index.symbols = [s for s in index.symbols if s.file_path != abs_path]
        index.imports = [i for i in index.imports if i.source_file != abs_path]
        # Add new
        syms, imps = self.build_for_file(abs_path)
        index.symbols.extend(syms)
        index.imports.extend(imps)
