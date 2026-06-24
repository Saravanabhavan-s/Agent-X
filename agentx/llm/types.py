from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_RESULT = "tool_result"


@dataclass
class Message:
    role: Role
    content: str
    tool_call_id: str | None = None
    tool_name: str | None = None


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    tool_name: str
    tool_input: dict[str, Any]
    call_id: str = ""


@dataclass
class StreamEvent:
    event_type: str  # "text_delta" | "tool_call" | "done" | "error"
    data: Any = None


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 4096
    timeout: int = 120
