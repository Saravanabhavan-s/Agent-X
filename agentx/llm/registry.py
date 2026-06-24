from __future__ import annotations

from agentx.llm.types import LLMConfig


def get_client(config: LLMConfig):  # type: ignore[return]
    """Resolve provider name → client instance. Only place provider names are resolved."""
    if config.provider == "ollama":
        from agentx.llm.ollama_client import OllamaClient
        return OllamaClient(config)
    elif config.provider == "anthropic":
        from agentx.llm.anthropic_client import AnthropicClient
        return AnthropicClient(config)
    elif config.provider == "openai":
        from agentx.llm.openai_client import OpenAIClient
        return OpenAIClient(config)
    elif config.provider == "openrouter":
        from agentx.llm.openrouter_client import OpenRouterClient
        return OpenRouterClient(config)
    else:
        raise ValueError(
            f"Unknown provider: {config.provider!r}. "
            f"Valid: ollama | anthropic | openai | openrouter"
        )
