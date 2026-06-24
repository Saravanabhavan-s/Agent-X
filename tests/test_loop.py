from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentx.llm.fake import FakeModelClient
from agentx.llm.types import ToolCall
from agentx.loop.engine import run_loop
from agentx.loop.state import LoopStatus
from agentx.runtime.sandbox import LocalSandbox

# Force tool registration
import agentx.tools.edit_file  # noqa: F401
import agentx.tools.read_file  # noqa: F401
import agentx.tools.run_tests  # noqa: F401


@pytest.fixture()
def toy_ws(tmp_path: Path) -> str:
    src = Path(__file__).parent.parent / "toy_repo"
    dst = tmp_path / "toy_repo"
    shutil.copytree(src, dst)
    return str(dst)


@pytest.mark.asyncio
async def test_loop_done_signal(toy_ws: str) -> None:
    """Model immediately signals done — loop exits with DONE status."""
    model = FakeModelClient([
        ToolCall(tool_name="task_done", tool_input={"summary": "nothing to do"}, call_id="t0"),
    ])
    loop = await run_loop(
        goal="test goal",
        workspace=toy_ws,
        model=model,
        max_turns=5,
    )
    states = [s async for s in loop]
    assert states[-1].status == LoopStatus.DONE


@pytest.mark.asyncio
async def test_loop_max_turns(toy_ws: str) -> None:
    """Loop stops at max_turns if model never signals done."""
    calls = [
        ToolCall(tool_name="read_file", tool_input={"path": "src/calculator/__init__.py"}, call_id=f"r{i}")
        for i in range(10)
    ]
    model = FakeModelClient(calls)
    loop = await run_loop(
        goal="keep reading forever",
        workspace=toy_ws,
        model=model,
        max_turns=3,
    )
    states = [s async for s in loop]
    assert states[-1].status == LoopStatus.MAX_TURNS_REACHED
    assert states[-1].turn <= 3


@pytest.mark.asyncio
async def test_loop_unknown_tool(toy_ws: str) -> None:
    """Unknown tool name — loop records error and continues until done signal."""
    model = FakeModelClient([
        ToolCall(tool_name="no_such_tool", tool_input={}, call_id="bad"),
        ToolCall(tool_name="task_done", tool_input={"summary": "ok"}, call_id="done"),
    ])
    loop = await run_loop(
        goal="test",
        workspace=toy_ws,
        model=model,
        max_turns=5,
    )
    states = [s async for s in loop]
    assert states[-1].status == LoopStatus.DONE
    error_state = states[0]
    assert "Unknown tool" in error_state.error_log or "no_such_tool" in error_state.last_observation


@pytest.mark.asyncio
async def test_loop_fix_calculator_bug(toy_ws: str) -> None:
    """Full end-to-end: agent reads file, applies patch, runs tests, signals done."""
    sandbox = LocalSandbox()
    fix_old = "    return a * b + 1\n"
    fix_new = "    return a * b\n"

    model = FakeModelClient([
        ToolCall(
            tool_name="read_file",
            tool_input={"path": "src/calculator/__init__.py"},
            call_id="r0",
        ),
        ToolCall(
            tool_name="edit_file",
            tool_input={
                "path": "src/calculator/__init__.py",
                "old": fix_old,
                "new": fix_new,
            },
            call_id="e0",
        ),
        ToolCall(
            tool_name="run_tests",
            tool_input={"path": "."},
            call_id="t0",
        ),
        ToolCall(
            tool_name="task_done",
            tool_input={"summary": "Fixed off-by-one in multiply()."},
            call_id="done",
        ),
    ])

    loop = await run_loop(
        goal="Fix the failing test in toy_repo",
        workspace=toy_ws,
        model=model,
        sandbox=sandbox,
        max_turns=10,
    )
    states = [s async for s in loop]
    final = states[-1]
    assert final.status == LoopStatus.DONE, f"Expected DONE, got {final.status}: {final.last_observation}"

    # Confirm the file was actually patched
    patched = (Path(toy_ws) / "src" / "calculator" / "__init__.py").read_text()
    assert "return a * b\n" in patched
    assert "return a * b + 1" not in patched
