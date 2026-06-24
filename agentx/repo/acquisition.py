from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from agentx.repo.models import AuthMethod, RepoAuth


class AcquisitionError(Exception):
    def __init__(self, message: str, cause: str, fix_hint: str) -> None:
        self.cause = cause
        self.fix_hint = fix_hint
        super().__init__(f"{message}\nCause: {cause}\nFix: {fix_hint}")


def _detect_provider(url: str) -> str | None:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        host = ""
    if "github.com" in host:
        return "github"
    if "gitlab.com" in host:
        return "gitlab"
    if "bitbucket.org" in host:
        return "bitbucket"
    return None


def _inject_token(url: str, auth: RepoAuth) -> str:
    parsed = urlparse(url)
    if auth.method == AuthMethod.GITHUB_TOKEN:
        netloc = f"{auth.token}@{parsed.hostname}"
    elif auth.method == AuthMethod.GITLAB_TOKEN:
        netloc = f"oauth2:{auth.token}@{parsed.hostname}"
    elif auth.method == AuthMethod.BITBUCKET_TOKEN:
        netloc = f"x-token-auth:{auth.token}@{parsed.hostname}"
    else:
        return url
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return parsed._replace(netloc=netloc).geturl()


def _clean_url(url: str) -> str:
    """Strip credentials from URL for storage in .git/config."""
    parsed = urlparse(url)
    clean_netloc = parsed.hostname or ""
    if parsed.port:
        clean_netloc = f"{clean_netloc}:{parsed.port}"
    return parsed._replace(netloc=clean_netloc).geturl()


def _map_git_error(stderr: str) -> tuple[str, str]:
    s = stderr.lower()
    if "authentication failed" in s or "could not read username" in s or "invalid username or password" in s:
        return "Authentication failed", "Check that the token is valid and has repo read access"
    if "repository not found" in s or "not found" in s:
        return "Repository not found", "Verify the URL and that the token has access to this repo"
    if "permission denied (publickey)" in s or "host key verification failed" in s:
        return "SSH authentication rejected", "Ensure the SSH key is added to the provider and AGENTX_SSH_KEY_PATH is correct"
    if "could not resolve host" in s:
        return "DNS resolution failed", "Check network connectivity and the repo URL hostname"
    if "already exists and is not an empty directory" in s:
        return "Target directory already exists", "Remove the target directory or choose a different destination"
    return "Git operation failed", "Check the URL and credentials, then retry"


def _run_git(cmd: list[str], *, cwd: str | None = None, env: dict | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


class RepositoryAcquisition:

    def __init__(self, config=None) -> None:
        self._config = config

    def _resolve_auth(self, url: str, explicit: RepoAuth | None) -> RepoAuth | None:
        if explicit is not None:
            return explicit
        cfg = self._config
        provider = _detect_provider(url)
        if provider == "github":
            token = (cfg.github_token if cfg else None) or os.environ.get("AGENTX_GITHUB_TOKEN", "")
            if token:
                return RepoAuth(method=AuthMethod.GITHUB_TOKEN, token=token)
        elif provider == "gitlab":
            token = (cfg.gitlab_token if cfg else None) or os.environ.get("AGENTX_GITLAB_TOKEN", "")
            if token:
                return RepoAuth(method=AuthMethod.GITLAB_TOKEN, token=token)
        elif provider == "bitbucket":
            token = (cfg.bitbucket_token if cfg else None) or os.environ.get("AGENTX_BITBUCKET_TOKEN", "")
            if token:
                return RepoAuth(method=AuthMethod.BITBUCKET_TOKEN, token=token)
        ssh_key = (getattr(cfg, "ssh_key_path", None) if cfg else None) or os.environ.get("AGENTX_SSH_KEY_PATH", "")
        if ssh_key:
            return RepoAuth(method=AuthMethod.SSH_KEY, ssh_key_path=ssh_key)
        return None

    def _normalize_source(self, source: str) -> tuple[str, bool]:
        """Return (url_or_path, is_remote). Expands owner/repo shorthand."""
        if source.startswith(("https://", "http://", "git@", "ssh://")):
            return source, True
        if source.startswith(("/", "./", "../", "~")):
            return str(Path(source).expanduser().resolve()), False
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source):
            return f"https://github.com/{source}.git", True
        return source, False

    async def acquire(
        self,
        source: str,
        target_dir: str,
        auth: RepoAuth | None = None,
        branch: str | None = None,
    ) -> str:
        url_or_path, is_remote = self._normalize_source(source)

        if not is_remote:
            local = Path(url_or_path)
            if not local.exists():
                raise AcquisitionError(
                    f"Local path not found: {url_or_path}",
                    cause="Path does not exist on disk",
                    fix_hint="Provide an absolute path or a valid relative path",
                )
            return str(local)

        resolved_auth = self._resolve_auth(url_or_path, auth)
        clone_url = url_or_path
        clone_env: dict | None = None

        if resolved_auth:
            if resolved_auth.method in (
                AuthMethod.GITHUB_TOKEN, AuthMethod.GITLAB_TOKEN, AuthMethod.BITBUCKET_TOKEN
            ):
                clone_url = _inject_token(url_or_path, resolved_auth)
            elif resolved_auth.method == AuthMethod.SSH_KEY and resolved_auth.ssh_key_path:
                base_env = os.environ.copy()
                base_env["GIT_SSH_COMMAND"] = (
                    f"ssh -i {resolved_auth.ssh_key_path} -o StrictHostKeyChecking=no"
                )
                clone_env = base_env

        cmd = ["git", "clone"]
        if branch:
            cmd += ["--branch", branch]
        cmd += ["--", clone_url, target_dir]

        try:
            result = _run_git(cmd, env=clone_env)
        except subprocess.TimeoutExpired:
            raise AcquisitionError(
                f"Clone timed out for {source}",
                cause="Git clone exceeded 120s timeout",
                fix_hint="Check network speed or try a shallow clone",
            )
        except OSError as exc:
            raise AcquisitionError(
                f"Failed to run git for {source}",
                cause=str(exc),
                fix_hint="Ensure git is installed and on PATH",
            )

        if result.returncode != 0:
            cause, hint = _map_git_error(result.stderr)
            raise AcquisitionError(
                f"Clone failed for {source}",
                cause=f"{cause}: {result.stderr.strip()[:500]}",
                fix_hint=hint,
            )

        # Strip credentials from remote URL so nothing lives in .git/config
        if clone_url != url_or_path:
            clean = _clean_url(url_or_path)
            _run_git(["git", "remote", "set-url", "origin", clean], cwd=target_dir)

        return str(Path(target_dir).resolve())
