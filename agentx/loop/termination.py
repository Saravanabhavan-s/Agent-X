from __future__ import annotations

from agentx.loop.state import LoopState, LoopStatus

# The model emits this tool name to signal it considers the task done.
DONE_TOOL = "task_done"
DONE_TOOL_SPEC = {
    "name": DONE_TOOL,
    "description": "Signal that the task is complete. Call this when tests pass and the goal is achieved.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Short description of what was accomplished."}
        },
        "required": ["summary"],
    },
}


def check_termination(state: LoopState, max_turns: int) -> LoopStatus | None:
    """Return a terminal status if the loop should stop, else None."""
    if state.status != LoopStatus.RUNNING:
        return state.status
    if state.turn >= max_turns:
        return LoopStatus.MAX_TURNS_REACHED
    return None
