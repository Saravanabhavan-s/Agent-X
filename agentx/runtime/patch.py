from __future__ import annotations

import difflib
import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PatchBlock:
    """One search/replace unit as emitted by the model."""

    path: str
    old: str
    new: str


@dataclass
class PatchResult:
    ok: bool
    diff: str = ""
    error: str = ""
    applied: list[str] = field(default_factory=list)


def _make_diff(path: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def apply_patch(blocks: list[PatchBlock], workspace: str) -> PatchResult:
    """Apply search/replace blocks atomically within workspace.

    Strategy:
    1. Verify every block's old text exists in its file.
    2. Write .bak backups.
    3. Apply all blocks.
    4. Return unified diff of all changes.
    On any error, restore backups and report.
    """
    root = Path(workspace)
    backups: dict[Path, Path] = {}
    applied: list[str] = []
    all_diffs: list[str] = []

    # --- verify phase ---
    file_contents: dict[Path, str] = {}
    for block in blocks:
        p = root / block.path
        if not p.exists():
            return PatchResult(ok=False, error=f"File not found: {block.path}")
        if p not in file_contents:
            file_contents[p] = p.read_text(encoding="utf-8")
        if block.old not in file_contents[p]:
            # show context around where we expected the text
            snippet = file_contents[p][:200].replace("\n", "↵")
            return PatchResult(
                ok=False,
                error=(
                    f"old text not found in {block.path}.\n"
                    f"Expected: {block.old[:120]!r}\n"
                    f"File starts: {snippet}"
                ),
            )

    # --- backup phase ---
    try:
        for p in file_contents:
            bak = p.with_suffix(p.suffix + ".bak")
            shutil.copy2(p, bak)
            backups[p] = bak
    except OSError as exc:
        _restore(backups)
        return PatchResult(ok=False, error=f"Backup failed: {exc}")

    # --- apply phase ---
    try:
        # Work on a mutable copy of contents so multiple blocks on same file compose
        new_contents = dict(file_contents)
        for block in blocks:
            p = root / block.path
            before = new_contents[p]
            after = before.replace(block.old, block.new, 1)
            new_contents[p] = after
            all_diffs.append(_make_diff(block.path, before, after))
            applied.append(block.path)

        for p, text in new_contents.items():
            p.write_text(text, encoding="utf-8")

        # Remove backups on success
        for bak in backups.values():
            bak.unlink(missing_ok=True)

    except OSError as exc:
        _restore(backups)
        return PatchResult(ok=False, error=f"Write failed: {exc}")

    return PatchResult(ok=True, diff="".join(all_diffs), applied=list(set(applied)))


def rollback_patch(workspace: str, paths: list[str]) -> PatchResult:
    """Restore .bak files for the given paths."""
    root = Path(workspace)
    restored: list[str] = []
    for rel in paths:
        p = root / rel
        bak = p.with_suffix(p.suffix + ".bak")
        if bak.exists():
            shutil.copy2(bak, p)
            bak.unlink(missing_ok=True)
            restored.append(rel)
    if not restored:
        return PatchResult(ok=False, error="No backup files found to restore.")
    return PatchResult(ok=True, applied=restored)


def _restore(backups: dict[Path, Path]) -> None:
    for original, bak in backups.items():
        if bak.exists():
            shutil.copy2(bak, original)
            bak.unlink(missing_ok=True)
