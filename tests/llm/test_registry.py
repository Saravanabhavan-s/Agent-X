from __future__ import annotations

import sys

import pytest

from agentx.llm.types import LLMConfig


def test_get_client_ollama():
    from agentx.llm.registry import get_client
    from agentx.llm.ollama_client import OllamaClient

    cfg = LLMConfig(provider="ollama", model="qwen2.5-coder:7b")
    client = get_client(cfg)
    assert isinstance(client, OllamaClient)


def test_get_client_anthropic():
    from agentx.llm.registry import get_client
    from agentx.llm.anthropic_client import AnthropicClient

    cfg = LLMConfig(provider="anthropic", model="claude-sonnet-4-6", api_key="sk-ant-test")
    client = get_client(cfg)
    assert isinstance(client, AnthropicClient)


def test_get_client_openai():
    from agentx.llm.registry import get_client
    from agentx.llm.openai_client import OpenAIClient

    cfg = LLMConfig(provider="openai", model="gpt-4o", api_key="sk-test")
    client = get_client(cfg)
    assert isinstance(client, OpenAIClient)


def test_get_client_openrouter():
    from agentx.llm.registry import get_client
    from agentx.llm.openrouter_client import OpenRouterClient

    cfg = LLMConfig(provider="openrouter", model="meta-llama/llama-3-70b-instruct", api_key="sk-or-test")
    client = get_client(cfg)
    assert isinstance(client, OpenRouterClient)


def test_get_client_unknown():
    from agentx.llm.registry import get_client

    cfg = LLMConfig(provider="unknown_provider", model="x")
    with pytest.raises(ValueError, match="Unknown provider"):
        get_client(cfg)


def test_lazy_import_does_not_load_anthropic():
    """Importing registry + creating ollama client must not import anthropic SDK."""
    # Remove anthropic from sys.modules to simulate a cold import
    anthropic_mods = [k for k in sys.modules if k.startswith("anthropic")]
    saved = {k: sys.modules.pop(k) for k in anthropic_mods}
    try:
        # Re-import registry (it might already be imported, but the key test is
        # that get_client("ollama") doesn't load anthropic)
        from agentx.llm.registry import get_client
        from agentx.llm.types import LLMConfig

        cfg = LLMConfig(provider="ollama", model="qwen2.5-coder:7b")
        get_client(cfg)
        # anthropic should still not be loaded
        assert "anthropic" not in sys.modules
    finally:
        sys.modules.update(saved)
