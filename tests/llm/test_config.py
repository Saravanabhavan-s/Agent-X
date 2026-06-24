from __future__ import annotations

import pytest

from agentx.config import Config


def _fresh() -> Config:
    return Config(
        workspace="/tmp/test",
        postgres_url="",
        redis_url="",
        redis_enabled=False,
        anthropic_api_key="",
        model_id="",
        max_turns=10,
        token_budget=4000,
        require_approval=False,
    )


def test_defaults_resolve_ollama(monkeypatch):
    """No env → ollama defaults."""
    for k in ["AGENTX_LLM_PROVIDER", "AGENTX_LLM_MODEL", "AGENTX_LLM_BASE_URL",
              "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"]:
        monkeypatch.delenv(k, raising=False)

    cfg = _fresh()
    llm = cfg.resolve_llm()
    assert llm.provider == "ollama"
    assert llm.model == "qwen3:8b"
    assert llm.base_url == "http://localhost:11434"
    assert llm.api_key is None


def test_explicit_provider_env(monkeypatch):
    """AGENTX_LLM_PROVIDER=anthropic + ANTHROPIC_API_KEY set → anthropic config."""
    monkeypatch.setenv("AGENTX_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("AGENTX_LLM_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    for k in ["OPENAI_API_KEY", "OPENROUTER_API_KEY", "AGENTX_LLM_BASE_URL"]:
        monkeypatch.delenv(k, raising=False)

    cfg = _fresh()
    llm = cfg.resolve_llm()
    assert llm.provider == "anthropic"
    assert llm.model == "claude-sonnet-4-6"
    assert llm.api_key == "sk-ant-test"


def test_auto_select_single_key(monkeypatch):
    """Only OPENAI_API_KEY set, no AGENTX_LLM_PROVIDER → infers openai."""
    for k in ["AGENTX_LLM_PROVIDER", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai-test")
    monkeypatch.delenv("AGENTX_LLM_MODEL", raising=False)
    monkeypatch.delenv("AGENTX_LLM_BASE_URL", raising=False)

    cfg = _fresh()
    llm = cfg.resolve_llm()
    assert llm.provider == "openai"
    assert llm.api_key == "sk-oai-test"


def test_auto_select_conflict_raises(monkeypatch):
    """Both ANTHROPIC_API_KEY and OPENAI_API_KEY set, no provider → ValueError."""
    monkeypatch.delenv("AGENTX_LLM_PROVIDER", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    cfg = _fresh()
    with pytest.raises(ValueError, match="Multiple API keys"):
        cfg.resolve_llm()


def test_explicit_arg_overrides_env(monkeypatch):
    """Explicit provider= arg beats env."""
    monkeypatch.setenv("AGENTX_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    cfg = _fresh()
    llm = cfg.resolve_llm(provider="ollama")
    assert llm.provider == "ollama"


def test_no_ollama_model_attribute():
    """Config no longer has ollama_model attribute."""
    cfg = _fresh()
    assert not hasattr(cfg, "ollama_model"), (
        "Config.ollama_model should have been removed; use resolve_llm().model"
    )
