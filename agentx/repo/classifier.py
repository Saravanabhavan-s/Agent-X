from __future__ import annotations

import re
import subprocess
import time
from collections import Counter
from pathlib import Path

from agentx.repo.models import RepoClassification, RepoType

_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", "target", "vendor", ".tox", ".mypy_cache",
}

_LANG_EXTS: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".kt": "kotlin",
    ".swift": "swift",
}

_ENTRY_CANDIDATES = {
    "main.py", "app.py", "server.py", "run.py",
    "index.ts", "index.js", "main.ts", "main.js",
    "main.go", "main.rs",
    "src/main.py", "src/app.py", "src/main.ts", "src/index.ts",
    "src/main.go", "src/main.rs",
}

_TODO_PATTERN = re.compile(r"\b(TODO|FIXME|HACK|BUG|XXX)\b[:\s]*(.*)", re.IGNORECASE)


class RepositoryClassifier:

    def classify(self, repo_path: str) -> RepoClassification:
        root = Path(repo_path)
        all_files = list(self._walk(root))

        lang_counts: Counter[str] = Counter()
        for f in all_files:
            lang = _LANG_EXTS.get(f.suffix.lower())
            if lang:
                lang_counts[lang] += 1

        languages = [lang for lang, _ in lang_counts.most_common()]
        primary_language = languages[0] if languages else "unknown"
        secondary_languages = languages[1:5]

        has_ci = self._has_ci(root)
        has_docker = (root / "Dockerfile").exists() or (root / "docker-compose.yml").exists()
        has_docs = any(
            (root / name).exists()
            for name in ("README.md", "README.rst", "README.txt", "docs")
        )

        frameworks, has_tests, package_manager, test_runner = self._detect_ecosystem(root, primary_language)

        # go test check
        if primary_language == "go":
            if any(f.name.endswith("_test.go") for f in all_files):
                has_tests = True
                test_runner = "go test"

        # rust test check
        if primary_language == "rust":
            has_tests = has_tests or any(
                "#[test]" in f.read_text(encoding="utf-8", errors="replace")
                for f in all_files if f.suffix == ".rs"
            )
            if has_tests:
                test_runner = test_runner or "cargo test"

        entry_points = self._find_entry_points(root, all_files)
        open_issues_hint = self._find_todos(all_files)

        file_count = len(all_files)
        if file_count < 20:
            complexity = "small"
        elif file_count < 200:
            complexity = "medium"
        else:
            complexity = "large"

        last_commit_days = self._last_commit_days(repo_path)
        repo_type = self._classify_type(file_count, last_commit_days)

        return RepoClassification(
            repo_type=repo_type,
            primary_language=primary_language,
            secondary_languages=secondary_languages,
            frameworks=frameworks,
            has_tests=has_tests,
            has_ci=has_ci,
            has_docs=has_docs,
            has_docker=has_docker,
            entry_points=entry_points,
            package_manager=package_manager,
            test_runner=test_runner,
            last_commit_days_ago=last_commit_days,
            open_issues_hint=open_issues_hint,
            confidence=0.8 if primary_language != "unknown" else 0.3,
        )

    # ── private helpers ──────────────────────────────────────────────────────

    def _walk(self, root: Path):
        for item in root.rglob("*"):
            if any(skip in item.parts for skip in _SKIP_DIRS):
                continue
            if item.is_file():
                yield item

    def _has_ci(self, root: Path) -> bool:
        return (
            (root / ".github" / "workflows").is_dir()
            or (root / ".gitlab-ci.yml").exists()
            or (root / ".circleci").is_dir()
            or (root / "Jenkinsfile").exists()
        )

    def _read_text_safe(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def _detect_ecosystem(
        self, root: Path, primary_language: str
    ) -> tuple[list[str], bool, str | None, str | None]:
        frameworks: list[str] = []
        has_tests = False
        package_manager: str | None = None
        test_runner: str | None = None

        # Python
        pyproject = root / "pyproject.toml"
        requirements = root / "requirements.txt"
        setup_py = root / "setup.py"
        if pyproject.exists() or setup_py.exists() or requirements.exists():
            package_manager = "pip"
        if pyproject.exists():
            content = self._read_text_safe(pyproject).lower()
            if "uv" in content:
                package_manager = "uv"
            if "fastapi" in content:
                frameworks.append("FastAPI")
            if "django" in content:
                frameworks.append("Django")
            if "flask" in content:
                frameworks.append("Flask")
            if "streamlit" in content:
                frameworks.append("Streamlit")
            if "pytest" in content:
                has_tests = True
                test_runner = "pytest"
        if requirements.exists():
            content = self._read_text_safe(requirements).lower()
            if "fastapi" in content:
                frameworks.append("FastAPI")
            if "django" in content:
                frameworks.append("Django")
            if "flask" in content:
                frameworks.append("Flask")
            if "streamlit" in content:
                frameworks.append("Streamlit")
            if "pytest" in content:
                has_tests = True
                test_runner = "pytest"
        if (root / "pytest.ini").exists() or (root / "setup.cfg").exists():
            has_tests = True
            test_runner = test_runner or "pytest"

        # Node / TypeScript
        package_json = root / "package.json"
        if package_json.exists():
            content = self._read_text_safe(package_json).lower()
            if (root / "yarn.lock").exists():
                package_manager = "yarn"
            else:
                package_manager = package_manager or "npm"
            if '"next"' in content or "'next'" in content or '"next":' in content:
                frameworks.append("Next.js")
            if '"react"' in content:
                frameworks.append("React")
            if '"express"' in content:
                frameworks.append("Express")
            if '"jest"' in content:
                has_tests = True
                test_runner = "jest"
            if '"vitest"' in content:
                has_tests = True
                test_runner = "vitest"

        # Go
        go_mod = root / "go.mod"
        if go_mod.exists():
            package_manager = "go mod"
            content = self._read_text_safe(go_mod).lower()
            if "gin-gonic/gin" in content:
                frameworks.append("Gin")
            if "labstack/echo" in content:
                frameworks.append("Echo")

        # Rust
        cargo_toml = root / "Cargo.toml"
        if cargo_toml.exists():
            package_manager = "cargo"

        # Java
        if (root / "pom.xml").exists():
            frameworks.append("Maven")
            package_manager = package_manager or "maven"
        if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
            frameworks.append("Gradle")
            package_manager = package_manager or "gradle"

        # Ruby
        if (root / "Gemfile").exists():
            package_manager = package_manager or "bundler"

        return frameworks, has_tests, package_manager, test_runner

    def _find_entry_points(self, root: Path, all_files: list[Path]) -> list[str]:
        found: list[str] = []
        file_names = {f.name for f in all_files}
        rel_paths = {str(f.relative_to(root)).replace("\\", "/") for f in all_files}

        for candidate in _ENTRY_CANDIDATES:
            name = candidate.split("/")[-1]
            if candidate in rel_paths or name in file_names:
                # find the actual path
                for f in all_files:
                    rel = str(f.relative_to(root)).replace("\\", "/")
                    if rel == candidate or f.name == name:
                        found.append(rel)
                        break

        # cmd/*/main.go for Go monorepos
        for f in all_files:
            rel = str(f.relative_to(root)).replace("\\", "/")
            if re.match(r"cmd/[^/]+/main\.go", rel) and rel not in found:
                found.append(rel)

        return list(dict.fromkeys(found))  # dedupe, preserve order

    def _find_todos(self, all_files: list[Path]) -> list[str]:
        results: list[str] = []
        for f in all_files:
            if f.suffix in (".pyc", ".png", ".jpg", ".gif", ".ico", ".woff", ".ttf"):
                continue
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    m = _TODO_PATTERN.search(line)
                    if m:
                        results.append(f"{f}:{i}: {m.group(0).strip()}")
                        if len(results) >= 20:
                            return results
            except Exception:
                continue
        return results

    def _last_commit_days(self, repo_path: str) -> int | None:
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ct"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                ts = int(result.stdout.strip())
                return int((time.time() - ts) / 86400)
        except Exception:
            pass
        return None

    def _classify_type(self, file_count: int, last_commit_days: int | None) -> RepoType:
        if file_count < 5:
            return RepoType.GREENFIELD
        if last_commit_days is not None and last_commit_days > 180:
            return RepoType.ABANDONED
        return RepoType.ACTIVE
