from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from agentx.llm.types import LLMConfig


@dataclass
class Config:
    """Central DI container — load from env or pass directly in tests."""

    # Workspace
    workspace: str = field(default_factory=lambda: str(Path.cwd()))

    # Postgres
    postgres_url: str = field(
        default_factory=lambda: os.environ.get(
            "AGENTX_POSTGRES_URL",
            "postgresql+asyncpg://agentx:agentx@localhost:5432/agentx",
        )
    )

    # Redis
    redis_url: str = field(
        default_factory=lambda: os.environ.get("AGENTX_REDIS_URL", "redis://localhost:6379/0")
    )
    redis_enabled: bool = field(
        default_factory=lambda: os.environ.get("AGENTX_REDIS_ENABLED", "true").lower() == "true"
    )

    # LLM — Anthropic (kept for back-compat; resolve_llm() supersedes these)
    anthropic_api_key: str = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", "")
    )
    model_id: str = field(
        default_factory=lambda: os.environ.get("AGENTX_MODEL", "claude-opus-4-8")
    )

    # Loop
    max_turns: int = field(
        default_factory=lambda: int(os.environ.get("AGENTX_MAX_TURNS", "20"))
    )
    token_budget: int = field(
        default_factory=lambda: int(os.environ.get("AGENTX_TOKEN_BUDGET", "8000"))
    )

    # Governance
    require_approval: bool = field(
        default_factory=lambda: os.environ.get("AGENTX_REQUIRE_APPROVAL", "true").lower() == "true"
    )

    # Sandbox
    sandbox_type: str = field(
        default_factory=lambda: os.environ.get("AGENTX_SANDBOX_TYPE", "local")
    )
    docker_image: str = field(
        default_factory=lambda: os.environ.get("AGENTX_DOCKER_IMAGE", "agentx-sandbox:latest")
    )

    # Repository auth
    github_token: str = field(
        default_factory=lambda: os.environ.get("AGENTX_GITHUB_TOKEN", "")
    )
    gitlab_token: str = field(
        default_factory=lambda: os.environ.get("AGENTX_GITLAB_TOKEN", "")
    )
    bitbucket_token: str = field(
        default_factory=lambda: os.environ.get("AGENTX_BITBUCKET_TOKEN", "")
    )
    ssh_key_path: str = field(
        default_factory=lambda: os.environ.get("AGENTX_SSH_KEY_PATH", "")
    )

    # Workspace storage root (for --repo clones)
    workspace_root: str = field(
        default_factory=lambda: os.environ.get("AGENTX_WORKSPACE_ROOT", "./workspaces")
    )

    def resolve_repo_auth(self, url: str) -> "RepoAuth | None":
        """Return a RepoAuth for the URL using env/config, or None for public."""
        from agentx.repo.models import AuthMethod, RepoAuth
        from urllib.parse import urlparse
        try:
            host = urlparse(url).hostname or ""
        except Exception:
            host = ""
        if "github.com" in host and self.github_token:
            return RepoAuth(method=AuthMethod.GITHUB_TOKEN, token=self.github_token)
        if "gitlab.com" in host and self.gitlab_token:
            return RepoAuth(method=AuthMethod.GITLAB_TOKEN, token=self.gitlab_token)
        if "bitbucket.org" in host and self.bitbucket_token:
            return RepoAuth(method=AuthMethod.BITBUCKET_TOKEN, token=self.bitbucket_token)
        if self.ssh_key_path:
            return RepoAuth(method=AuthMethod.SSH_KEY, ssh_key_path=self.ssh_key_path)
        return None

    @classmethod
    def from_env(cls) -> "Config":
        return cls()

    @classmethod
    def for_tests(cls, workspace: str) -> "Config":
        return cls(
            workspace=workspace,
            postgres_url="",
            redis_url="",
            redis_enabled=False,
            anthropic_api_key="fake",
            max_turns=10,
            token_budget=4000,
            require_approval=False,
        )

    def resolve_llm(
        self,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> LLMConfig:
        """Build LLMConfig with precedence: explicit args > env > defaults."""

        # --- provider ---
        env_provider = os.environ.get("AGENTX_LLM_PROVIDER", "")
        resolved_provider = provider or env_provider or ""

        # --- auto-select from API key env vars (only when provider not set) ---
        if not resolved_provider:
            keys_present = [
                p for p, env in [
                    ("anthropic", "ANTHROPIC_API_KEY"),
                    ("openai", "OPENAI_API_KEY"),
                    ("openrouter", "OPENROUTER_API_KEY"),
                ]
                if os.environ.get(env)
            ]
            if len(keys_present) == 1:
                resolved_provider = keys_present[0]
            elif len(keys_present) > 1:
                raise ValueError(
                    f"Multiple API keys set ({keys_present}) but "
                    f"AGENTX_LLM_PROVIDER is not specified. Set it explicitly."
                )
            else:
                resolved_provider = "ollama"

        # --- model ---
        _default_model = (
            "qwen3:8b" if resolved_provider == "ollama" else ""
        )
        resolved_model = (
            model
            or os.environ.get("AGENTX_LLM_MODEL", "")
            or _default_model
        )

        # --- base_url ---
        _default_base_url = (
            "http://localhost:11434" if resolved_provider == "ollama" else None
        )
        resolved_base_url = (
            base_url
            or os.environ.get("AGENTX_LLM_BASE_URL", "")
            or _default_base_url
            or None
        )

        # --- api_key ---
        _key_env_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }
        env_key_name = _key_env_map.get(resolved_provider, "")
        resolved_api_key = api_key or (
            os.environ.get(env_key_name, "") if env_key_name else ""
        ) or None

        # --- tuning ---
        temperature = float(os.environ.get("AGENTX_LLM_TEMPERATURE", "0.2"))
        max_tokens = int(os.environ.get("AGENTX_LLM_MAX_TOKENS", "4096"))

        return LLMConfig(
            provider=resolved_provider,
            model=resolved_model,
            api_key=resolved_api_key,
            base_url=resolved_base_url or None,
            temperature=temperature,
            max_tokens=max_tokens,
        )
