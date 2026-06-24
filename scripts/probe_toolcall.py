"""
Quick probe: verify that Ollama + Qwen returns a structured tool call.

Usage:
    python scripts/probe_toolcall.py
    python scripts/probe_toolcall.py --model qwen2.5-coder:14b

If NoToolCallError fires, the model is not using tool-calling format.
Try a larger model: ollama pull qwen2.5-coder:14b
"""
from __future__ import annotations

import asyncio
import sys


async def probe(model: str = "qwen3:8b") -> None:
    from agentx.llm.registry import get_client
    from agentx.llm.types import LLMConfig, Message, Role, ToolSpec
    from agentx.llm.base import NoToolCallError

    cfg = LLMConfig(
        provider="ollama",
        model=model,
        base_url="http://localhost:11434",
        timeout=60,
    )
    client = get_client(cfg)

    tools = [
        ToolSpec(
            name="read_file",
            description="Read a source file from the workspace.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path relative to workspace root"}},
                "required": ["path"],
            },
        )
    ]
    messages = [
        Message(role=Role.USER, content="Read the file src/calculator/__init__.py")
    ]

    print(f"Probing provider=ollama model={model} ...")
    try:
        result = await client.reason(messages, tools, turn=0)
        print(f"  tool_name  : {result.tool_name}")
        print(f"  tool_input : {result.tool_input}")
        print(f"  call_id    : {result.call_id}")
        print("PASS — model called a tool.")
    except NoToolCallError as e:
        print(f"FAIL — NoToolCallError: {e.text[:300]}")
        print("Hint: try ollama pull qwen2.5-coder:14b, then re-probe with --model qwen2.5-coder:14b")
        sys.exit(1)


if __name__ == "__main__":
    _model = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--model" else "qwen3:8b"
    asyncio.run(probe(_model))
