from __future__ import annotations

from agentx.context.budget import TokenBudget, estimate_tokens
from agentx.context.selectors import select_files, select_history
from agentx.llm.types import Message, Role


def assemble_context(
    *,
    goal: str,
    last_observation: str,
    history: list[str],
    workspace: str,
    token_budget: int = 8_000,
    last_diff: str = "",
    error_log: str = "",
    repo_context=None,   # agentx.repo.models.RepoContext | None
    intelligence=None,   # agentx.intelligence.query.IntelligenceQuery | None
    last_edited_file: str | None = None,
) -> list[Message]:
    """Build the message list sent to the model each turn.

    Slot priority (highest first):
      1. goal (always included)
      1b. repo context (if present — injected right after goal on Turn 1)
      2. last observation
      3. last diff (if any)
      4. error log (if any)
      5. relevant workspace files (token-budgeted)
      6. recent history (token-budgeted, lowest priority)
    """
    budget = TokenBudget(total=token_budget)
    messages: list[Message] = []

    def _add(role: Role, text: str) -> None:
        tokens = estimate_tokens(text)
        budget.consume(tokens)
        messages.append(Message(role=role, content=text))

    # Slot 1: goal
    _add(Role.USER, f"## Goal\n{goal}")

    # Slot 1b: repo context (only on Turn 1 — when last_observation is empty)
    if repo_context is not None and not last_observation:
        _render_repo_context(repo_context, budget, messages)

    # Slot 2: last observation
    if last_observation:
        _add(Role.USER, f"## Last Observation\n{last_observation}")

    # Slot 3: last diff
    if last_diff:
        tokens = estimate_tokens(last_diff)
        if budget.fits(tokens):
            budget.consume(tokens)
            messages.append(Message(role=Role.USER, content=f"## Last Diff\n```diff\n{last_diff}\n```"))

    # Slot 4: error log
    if error_log:
        tokens = estimate_tokens(error_log)
        if budget.fits(tokens):
            budget.consume(tokens)
            messages.append(Message(role=Role.USER, content=f"## Error Log\n{error_log}"))

    # Slot 5: workspace files
    file_budget = TokenBudget(total=budget.remaining // 2)
    files = select_files(workspace, file_budget, intelligence=intelligence)

    # 5a: impact warning for last edited file
    if intelligence is not None and last_edited_file is not None:
        try:
            impact = intelligence.impact_of_change(last_edited_file)
            if impact.risk_level in ("medium", "high"):
                n = len(impact.directly_affected)
                msg = (
                    f"[impact] Changing {last_edited_file} affects {n} file(s) directly. "
                    f"Risk: {impact.risk_level}. Reason: {impact.risk_reason}"
                )
                tokens = estimate_tokens(msg)
                if budget.fits(tokens):
                    budget.consume(tokens)
                    messages.append(Message(role=Role.USER, content=msg))
        except Exception:
            pass

    if files:
        parts = [f"### {rel}\n```\n{content}\n```" for rel, content in files]
        block = "## Workspace Files\n\n" + "\n\n".join(parts)
        tokens = estimate_tokens(block)
        if budget.fits(tokens):
            budget.consume(tokens)
            messages.append(Message(role=Role.USER, content=block))

    # 5b: intelligence symbol summaries for each file in context
    if intelligence is not None and files:
        summaries: list[str] = []
        for rel, _ in files:
            try:
                summary = intelligence.format_for_context(rel)
                if summary:
                    summaries.append(summary)
            except Exception:
                pass
        if summaries:
            block = "## Symbol Intelligence\n\n" + "\n\n".join(summaries)
            tokens = estimate_tokens(block)
            if budget.fits(tokens):
                budget.consume(tokens)
                messages.append(Message(role=Role.USER, content=block))

    # Slot 6: history
    history_budget = TokenBudget(total=budget.remaining)
    history_turns = select_history(history, history_budget)
    for turn in history_turns:
        messages.append(Message(role=Role.USER, content=turn))

    return messages


def _render_repo_context(repo_context, budget: TokenBudget, messages: list[Message]) -> None:
    c = repo_context.classification
    parts = [
        "## Repository Context",
        f"Type: {c.repo_type.value.upper()}",
        f"Language: {c.primary_language}" + (f" ({', '.join(c.frameworks)})" if c.frameworks else ""),
        f"Package manager: {c.package_manager or 'unknown'}",
        f"Test runner: {c.test_runner or 'none'}",
        f"Has tests: {c.has_tests}  Has CI: {c.has_ci}  Has Docker: {c.has_docker}",
        f"Complexity: {repo_context.estimated_complexity}",
    ]
    if c.last_commit_days_ago is not None:
        parts.append(f"Last commit: {c.last_commit_days_ago} days ago")
    if c.entry_points:
        parts.append(f"Entry points: {', '.join(c.entry_points[:5])}")
    if repo_context.build_errors:
        parts.append(f"Build errors: {len(repo_context.build_errors)}")
        parts.extend(f"  - {e}" for e in repo_context.build_errors[:3])
    if repo_context.test_results:
        tr = repo_context.test_results
        parts.append(f"Test results: {tr.get('passed', '?')}/{tr.get('total', '?')} passing")
    if c.open_issues_hint:
        parts.append(f"Open issues ({len(c.open_issues_hint)}):")
        parts.extend(f"  {h}" for h in c.open_issues_hint[:5])
    if repo_context.file_tree:
        parts.append("\n### File Tree\n```\n" + repo_context.file_tree + "\n```")
    if repo_context.git_log_summary:
        parts.append("\n### Recent Commits\n```\n" + repo_context.git_log_summary + "\n```")

    block = "\n".join(parts)
    tokens = estimate_tokens(block)
    if budget.fits(tokens):
        budget.consume(tokens)
        messages.append(Message(role=Role.USER, content=block))
