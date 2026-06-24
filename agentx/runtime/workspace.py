from __future__ import annotations

import tempfile
from pathlib import Path


class Workspace:
    """Manages the directory the agent operates on.

    For production use, root points at the real project checkout.
    For tests, create an ephemeral workspace with from_temp().
    """

    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        if not self._root.exists():
            raise FileNotFoundError(f"Workspace root does not exist: {self._root}")

    @classmethod
    def from_temp(cls) -> "Workspace":
        """Create a fresh tmpdir workspace. Caller owns cleanup."""
        tmp = tempfile.mkdtemp(prefix="agentx_ws_")
        return cls(tmp)

    @property
    def root(self) -> str:
        return str(self._root)

    def path(self, *parts: str) -> Path:
        """Resolve a workspace-relative path, ensuring it stays inside root."""
        resolved = (self._root / Path(*parts)).resolve()
        if not str(resolved).startswith(str(self._root)):
            raise ValueError(f"Path escapes workspace: {parts!r}")
        return resolved

    def relative(self, abs_path: str) -> str:
        """Return workspace-relative string for an absolute path."""
        return str(Path(abs_path).resolve().relative_to(self._root))

    def write_file(self, rel: str, content: str) -> None:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def read_file(self, rel: str) -> str:
        return self.path(rel).read_text(encoding="utf-8")

    def exists(self, rel: str) -> bool:
        return (self._root / rel).exists()
