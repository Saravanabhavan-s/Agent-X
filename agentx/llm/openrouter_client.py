from __future__ import annotations

import dataclasses
from typing import Any

from agentx.llm.openai_client import OpenAIClient
from agentx.llm.types import LLMConfig

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://agentx.local",
    "X-Title": "Agent X",
}


class OpenRouterClient(OpenAIClient):
    """OpenAI-compatible client for OpenRouter. Thin subclass adding required headers."""

    def __init__(self, config: LLMConfig) -> None:
        if not config.base_url:
            config = dataclasses.replace(config, base_url=_OPENROUTER_BASE_URL)
        if not config.api_key:
            raise ValueError(
                "OpenRouterClient requires api_key. "
                "Set OPENROUTER_API_KEY or pass --api-key."
            )
        super().__init__(config)

    def _make_headers(self) -> dict[str, Any]:
        headers = super()._make_headers()
        headers.update(_OPENROUTER_HEADERS)
        return headers
