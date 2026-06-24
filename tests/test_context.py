from __future__ import annotations

from pathlib import Path

import pytest

from agentx.context.budget import TokenBudget, estimate_tokens
from agentx.context.assembler import assemble_context
from agentx.llm.types import Role


def test_token_budget_basic() -> None:
    b = TokenBudget(total=100)
    assert b.remaining == 100
    b.consume(30)
    assert b.remaining == 70
    assert b.fits(70)
    assert not b.fits(71)


def test_estimate_tokens_nonzero() -> None:
    assert estimate_tokens("hello world foo bar") > 0


def test_assemble_context_includes_goal(tmp_path: Path) -> None:
    msgs = assemble_context(
        goal="fix the bug",
        last_observation="tests failed",
        history=[],
        workspace=str(tmp_path),
        token_budget=2000,
    )
    combined = " ".join(m.content for m in msgs)
    assert "fix the bug" in combined


def test_assemble_context_includes_observation(tmp_path: Path) -> None:
    msgs = assemble_context(
        goal="x",
        last_observation="OBSERVATION_MARKER",
        history=[],
        workspace=str(tmp_path),
        token_budget=2000,
    )
    combined = " ".join(m.content for m in msgs)
    assert "OBSERVATION_MARKER" in combined


def test_assemble_context_includes_diff(tmp_path: Path) -> None:
    msgs = assemble_context(
        goal="x",
        last_observation="obs",
        history=[],
        workspace=str(tmp_path),
        token_budget=2000,
        last_diff="--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new",
    )
    combined = " ".join(m.content for m in msgs)
    assert "old" in combined


def test_assemble_context_workspace_files(tmp_path: Path) -> None:
    (tmp_path / "example.py").write_text("print('hello')\n")
    msgs = assemble_context(
        goal="x",
        last_observation="obs",
        history=[],
        workspace=str(tmp_path),
        token_budget=4000,
    )
    combined = " ".join(m.content for m in msgs)
    assert "example.py" in combined


def test_assemble_context_budget_respected(tmp_path: Path) -> None:
    # Very tight budget — only goal fits
    msgs = assemble_context(
        goal="tiny",
        last_observation="obs",
        history=["turn1", "turn2"],
        workspace=str(tmp_path),
        token_budget=10,
    )
    # Should not crash; may produce very few messages
    assert len(msgs) >= 1
