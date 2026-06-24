from __future__ import annotations

import re

from agentx.repo.models import RepoClassification, RepoType


class ProjectHealthAnalyzer:

    async def analyze(
        self,
        repo_path: str,
        classification: RepoClassification,
        sandbox,
    ) -> dict:
        result: dict = {
            "can_install_deps": False,
            "can_run_tests": False,
            "test_results": None,
            "build_errors": [],
            "missing_deps": [],
            "inferred_intent": "",
            "health_score": 0.0,
        }

        try:
            await self._analyze(repo_path, classification, sandbox, result)
        except Exception as exc:
            result["build_errors"].append(f"Health check crashed: {exc}")
            result["health_score"] = 0.0

        return result

    async def _analyze(
        self,
        repo_path: str,
        classification: RepoClassification,
        sandbox,
        result: dict,
    ) -> None:
        repo_type = classification.repo_type

        if repo_type == RepoType.GREENFIELD:
            result["health_score"] = 1.0
            result["can_install_deps"] = True
            result["can_run_tests"] = True
            result["inferred_intent"] = "New project — no existing code to analyze."
            return

        if repo_type == RepoType.ABANDONED:
            await self._analyze_abandoned(repo_path, classification, sandbox, result)
            return

        # ACTIVE or BROKEN — try install then tests
        await self._try_install(repo_path, classification, sandbox, result)
        if result["can_install_deps"]:
            await self._try_tests(repo_path, classification, sandbox, result)

        # Compute health_score from test results
        tr = result["test_results"]
        if tr and tr.get("total", 0) > 0:
            passed = tr.get("passed", 0)
            total = tr["total"]
            result["health_score"] = round(passed / total, 2)
        elif result["can_install_deps"] and result["can_run_tests"]:
            result["health_score"] = 0.9  # tests ran, no failures detected
        elif result["can_install_deps"]:
            result["health_score"] = 0.4
        else:
            result["health_score"] = 0.1

    async def _try_install(
        self, repo_path: str, classification: RepoClassification, sandbox, result: dict
    ) -> None:
        pm = classification.package_manager
        if pm is None:
            result["can_install_deps"] = True
            return

        if pm in ("pip", "uv"):
            cmd = self._pip_install_cmd(repo_path)
        elif pm == "npm":
            cmd = ["npm", "install", "--legacy-peer-deps"]
        elif pm == "yarn":
            cmd = ["yarn", "install", "--frozen-lockfile"]
        elif pm == "go mod":
            cmd = ["go", "mod", "download"]
        elif pm == "cargo":
            cmd = ["cargo", "fetch"]
        elif pm in ("maven",):
            cmd = ["mvn", "dependency:resolve", "-q"]
        elif pm == "gradle":
            cmd = ["./gradlew", "dependencies", "-q"]
        elif pm == "bundler":
            cmd = ["bundle", "install"]
        else:
            result["can_install_deps"] = True
            return

        cr = await sandbox.run(cmd, cwd=repo_path, timeout=120)
        if cr.ok:
            result["can_install_deps"] = True
        else:
            result["can_install_deps"] = False
            errors = self._extract_errors(cr.stdout + cr.stderr)
            result["build_errors"].extend(errors or [cr.stderr.strip()[:500]])
            result["missing_deps"] = self._extract_missing_deps(cr.stderr)

    def _pip_install_cmd(self, repo_path: str) -> list[str]:
        from pathlib import Path
        if (Path(repo_path) / "pyproject.toml").exists():
            return ["uv", "pip", "install", "-e", "."]
        return ["pip", "install", "-r", "requirements.txt"]

    async def _try_tests(
        self, repo_path: str, classification: RepoClassification, sandbox, result: dict
    ) -> None:
        runner = classification.test_runner
        if runner is None:
            return

        if runner == "pytest":
            cmd = ["pytest", "--tb=short", "-q"]
        elif runner == "jest":
            cmd = ["npx", "jest", "--passWithNoTests"]
        elif runner == "vitest":
            cmd = ["npx", "vitest", "run"]
        elif runner == "go test":
            cmd = ["go", "test", "./..."]
        elif runner == "cargo test":
            cmd = ["cargo", "test"]
        else:
            return

        cr = await sandbox.run(cmd, cwd=repo_path, timeout=120)
        result["can_run_tests"] = True

        parsed = self._parse_test_output(cr.stdout + cr.stderr, runner)
        if parsed:
            result["test_results"] = parsed
        else:
            result["test_results"] = {"raw": (cr.stdout + cr.stderr)[:1000], "ok": cr.ok}

        if not cr.ok:
            errors = self._extract_errors(cr.stdout + cr.stderr)
            result["build_errors"].extend(errors)

    async def _analyze_abandoned(
        self, repo_path: str, classification: RepoClassification, sandbox, result: dict
    ) -> None:
        # Try installing / running tests anyway
        await self._try_install(repo_path, classification, sandbox, result)
        if result["can_install_deps"]:
            await self._try_tests(repo_path, classification, sandbox, result)

        result["health_score"] = 0.2 if not result["build_errors"] else 0.1

        # Infer intent from git log + README
        intent_parts: list[str] = []
        try:
            import subprocess
            r = subprocess.run(
                ["git", "log", "--oneline", "-5"],
                cwd=repo_path, capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                intent_parts.append(f"Last commits: {r.stdout.strip()}")
        except Exception:
            pass

        from pathlib import Path
        for readme in ("README.md", "README.rst", "README.txt"):
            rp = Path(repo_path) / readme
            if rp.exists():
                lines = rp.read_text(encoding="utf-8", errors="replace").splitlines()[:10]
                intent_parts.append("README: " + " ".join(lines))
                break

        result["inferred_intent"] = "; ".join(intent_parts) if intent_parts else "Intent unknown."

    def _parse_test_output(self, output: str, runner: str) -> dict | None:
        if runner == "pytest":
            m = re.search(r"(\d+) passed", output)
            f = re.search(r"(\d+) failed", output)
            e = re.search(r"(\d+) error", output)
            passed = int(m.group(1)) if m else 0
            failed = int(f.group(1)) if f else 0
            errors = int(e.group(1)) if e else 0
            total = passed + failed + errors
            if total == 0 and not (m or f or e):
                return None
            return {"passed": passed, "failed": failed, "errors": errors, "total": total}
        if runner == "go test":
            passed = output.count("--- PASS")
            failed = output.count("--- FAIL")
            total = passed + failed
            if total == 0:
                return None
            return {"passed": passed, "failed": failed, "total": total}
        return None

    def _extract_errors(self, output: str) -> list[str]:
        lines = output.splitlines()
        errors = [
            l.strip() for l in lines
            if any(kw in l for kw in ("Error:", "ERROR", "ImportError", "SyntaxError", "FAILED", "error["))
        ]
        return errors[:10]

    def _extract_missing_deps(self, stderr: str) -> list[str]:
        missing: list[str] = []
        for m in re.finditer(r"No module named '([^']+)'", stderr):
            missing.append(m.group(1))
        for m in re.finditer(r"Cannot find module '([^']+)'", stderr):
            missing.append(m.group(1))
        return missing[:10]
