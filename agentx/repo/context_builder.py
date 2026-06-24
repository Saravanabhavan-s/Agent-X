from __future__ import annotations

import subprocess
from pathlib import Path

from agentx.repo.models import RepoClassification, RepoContext

_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", "target", "vendor", ".tox", ".mypy_cache",
}

_KEY_FILE_CANDIDATES = [
    # Docs
    "README.md", "README.rst", "README.txt",
    # Manifests
    "pyproject.toml", "package.json", "go.mod", "Cargo.toml",
    "requirements.txt", "setup.py",
    # Config
    ".env.example", "config.py", "settings.py",
]

_CI_DIRS = [".github/workflows", ".gitlab-ci.yml", ".circleci"]

_TOKEN_CHARS = 4  # approx: 1 token ≈ 4 chars


class RepoContextBuilder:

    async def build(
        self,
        repo_path: str,
        classification: RepoClassification,
        health: dict,
        url: str | None = None,
    ) -> RepoContext:
        root = Path(repo_path)

        file_tree = self._build_file_tree(root)
        key_files = self._collect_key_files(root, classification)
        git_log = self._git_log(repo_path)
        readme = self._read_readme(root)

        if classification.primary_language == "unknown" or not classification.frameworks:
            complexity = "small" if len(list(root.rglob("*"))) < 20 else "medium"
        else:
            # Use file count from walking (already done in classifier)
            total = sum(1 for _ in self._walk(root))
            if total < 20:
                complexity = "small"
            elif total < 200:
                complexity = "medium"
            else:
                complexity = "large"

        return RepoContext(
            url=url,
            local_path=str(root.resolve()),
            classification=classification,
            file_tree=file_tree,
            key_files=key_files,
            git_log_summary=git_log,
            test_results=health.get("test_results"),
            build_errors=health.get("build_errors", []),
            readme_content=readme,
            estimated_complexity=complexity,
        )

    # ── private helpers ──────────────────────────────────────────────────────

    def _walk(self, root: Path):
        for item in root.rglob("*"):
            if any(skip in item.parts for skip in _SKIP_DIRS):
                continue
            if item.is_file():
                yield item

    def _build_file_tree(self, root: Path) -> str:
        lines: list[str] = [root.name + "/"]
        count = 0
        MAX_LINES = 200

        def _recurse(path: Path, depth: int) -> None:
            nonlocal count
            if depth > 3 or count >= MAX_LINES:
                return
            try:
                children = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
            except PermissionError:
                return
            for child in children:
                if child.name in _SKIP_DIRS:
                    continue
                if count >= MAX_LINES:
                    lines.append("  " * depth + "  ... (truncated)")
                    return
                prefix = "  " * depth + "  "
                if child.is_dir():
                    lines.append(f"{prefix}{child.name}/")
                    count += 1
                    _recurse(child, depth + 1)
                else:
                    lines.append(f"{prefix}{child.name}")
                    count += 1

        _recurse(root, 0)
        return "\n".join(lines)

    def _collect_key_files(self, root: Path, classification: RepoClassification) -> dict[str, str]:
        budget_chars = 4000 * _TOKEN_CHARS  # ~4000 tokens
        key_files: dict[str, str] = {}
        used = 0

        candidates: list[Path] = []

        # Fixed candidates
        for name in _KEY_FILE_CANDIDATES:
            p = root / name
            if p.exists() and p.is_file():
                candidates.append(p)

        # Entry points from classification
        for rel in classification.entry_points:
            p = root / rel
            if p.exists() and p not in candidates:
                candidates.append(p)

        # First CI workflow
        for ci_loc in _CI_DIRS:
            ci_path = root / ci_loc
            if ci_path.is_dir():
                ymls = sorted(ci_path.glob("*.yml"))
                if ymls:
                    candidates.append(ymls[0])
                break
            elif ci_path.is_file():
                candidates.append(ci_path)
                break

        for p in candidates:
            if used >= budget_chars:
                break
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[:200]
                content = "\n".join(lines)
                cost = len(content)
                if used + cost > budget_chars:
                    # Trim to fit
                    remaining = budget_chars - used
                    content = content[:remaining]
                rel = str(p.relative_to(root)).replace("\\", "/")
                key_files[rel] = content
                used += len(content)
            except Exception:
                continue

        return key_files

    def _git_log(self, repo_path: str) -> str:
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-20"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return ""

    def _read_readme(self, root: Path) -> str | None:
        for name in ("README.md", "README.rst", "README.txt"):
            p = root / name
            if p.exists():
                try:
                    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[:200]
                    return "\n".join(lines)
                except Exception:
                    pass
        return None
