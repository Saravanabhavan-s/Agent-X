from __future__ import annotations

import uuid
from typing import AsyncIterator

from pydantic import BaseModel, ValidationError

from agentx.context.assembler import assemble_context
from agentx.governance.gate import GovernanceGate, NullGate
from agentx.llm.base import ModelClient, NoToolCallError, SessionError
from agentx.llm.types import ToolSpec
from agentx.loop.state import LoopState, LoopStatus
from agentx.loop.termination import DONE_TOOL, DONE_TOOL_SPEC, check_termination
from agentx.runtime.sandbox import Sandbox
from agentx.tools.base import ToolContext, all_tools

# AuditWriter is optional — imported lazily to avoid hard DB dep in tests
_AuditWriterT = None  # forward-declared type alias


def _build_tool_specs() -> list[ToolSpec]:
    specs = [
        ToolSpec(
            name=t.name,
            description=t.description,
            input_schema=t.input_schema,
        )
        for t in all_tools()
    ]
    # Always include the termination signal
    specs.append(
        ToolSpec(
            name=DONE_TOOL_SPEC["name"],
            description=DONE_TOOL_SPEC["description"],
            input_schema=DONE_TOOL_SPEC["input_schema"],
        )
    )
    return specs


async def run_loop(
    *,
    goal: str,
    workspace: str,
    model: ModelClient,
    sandbox: Sandbox | None = None,
    gate: GovernanceGate | None = None,
    audit: object | None = None,
    max_turns: int = 20,
    session_id: str | None = None,
    token_budget: int = 8_000,
    system: str = "",
    repo_context=None,  # agentx.repo.models.RepoContext | None
) -> AsyncIterator[LoopState]:
    """Core agent loop. Yields state after every turn.

    The loop:
      1. Assembles context from state.
      2. Calls the model for one ToolCall.
      3. Routes through the governance gate (approval gate).
      4. Dispatches the tool.
      5. Records the observation.
      6. Checks termination conditions.
    """
    sid = session_id or str(uuid.uuid4())
    state = LoopState(session_id=sid, goal=goal, workspace=workspace)
    if repo_context is not None:
        state.repo_url = repo_context.url
        state.repo_type = repo_context.classification.repo_type.value
        state.primary_language = repo_context.classification.primary_language
        state.repo_context = repo_context.to_dict()
        from agentx.repo.models import RepoType
        health = {"health_score": None}
        if repo_context.test_results:
            tr = repo_context.test_results
            total = tr.get("total", 0)
            passed = tr.get("passed", 0)
            if total > 0:
                health["health_score"] = round(passed / total, 2)
        state.health_score = health["health_score"]
    _gate = gate or NullGate()
    _audit = audit  # optional AuditWriter — None = no audit
    tool_specs = _build_tool_specs()

    # Build symbol intelligence (best-effort — failure must not block the loop)
    _indexer = None
    _symbol_index = None
    if repo_context is not None:
        try:
            import logging as _logging
            _log = _logging.getLogger(__name__)
            from agentx.intelligence.dep_graph import DependencyGraphBuilder
            from agentx.intelligence.query import IntelligenceQuery
            from agentx.intelligence.symbol_index import SymbolIndexer
            _indexer = SymbolIndexer(workspace, repo_context.classification)
            _symbol_index = _indexer.build()
            _dep_graph = DependencyGraphBuilder().build(_symbol_index)
            state.intelligence = IntelligenceQuery(_symbol_index, _dep_graph)
            _log.info(
                "Intelligence ready: %d symbols, %d dep edges",
                len(_symbol_index.symbols),
                len(_dep_graph.edges),
            )
        except Exception:
            state.intelligence = None

    async def _emit_audit(event_type: str, **kwargs) -> None:
        if _audit is None:
            return
        from agentx.governance.audit import AuditEntry
        try:
            await _audit.write(AuditEntry(session_id=sid, event_type=event_type, **kwargs))
        except Exception:  # noqa: BLE001
            pass  # audit failure must not crash the loop

    async def _gen() -> AsyncIterator[LoopState]:
        _notool_retries = 0
        _MAX_NOTOOL_RETRIES = 3

        while True:
            terminal = check_termination(state, max_turns)
            if terminal is not None:
                state.status = terminal
                yield state
                return

            messages = assemble_context(
                goal=goal,
                last_observation=state.last_observation,
                history=state.history,
                workspace=workspace,
                token_budget=token_budget,
                last_diff=state.last_diff,
                error_log=state.error_log,
                repo_context=repo_context,
                intelligence=state.intelligence,
                last_edited_file=state.last_edited_file,
            )

            try:
                tool_call = await model.reason(
                    messages, tool_specs, system=system, turn=state.turn
                )
                _notool_retries = 0  # reset on success
                await _emit_audit(
                    "model_response",
                    turn_number=state.turn,
                    tool_name=tool_call.tool_name,
                    model_response_summary=str(tool_call.tool_input)[:500],
                )
            except NoToolCallError as e:
                _notool_retries += 1
                if _notool_retries >= _MAX_NOTOOL_RETRIES:
                    raise SessionError(
                        f"Model refused to use tools after {_MAX_NOTOOL_RETRIES} retries. "
                        f"Check provider/model tool-calling support. "
                        f"Last response: {e.text[:300]}"
                    ) from e
                correction = (
                    "You returned a text answer without calling any tool. "
                    "You MUST call a tool. Do not explain — act. "
                    f"Your previous response was: {e.text[:200]}"
                )
                state.add_correction(correction)
                yield state
                continue

            # --- termination sentinel ---
            if tool_call.tool_name == DONE_TOOL:
                summary = tool_call.tool_input.get("summary", "")
                state.record_turn(f"DONE: {summary}")
                state.status = LoopStatus.DONE
                yield state
                return

            # --- governance gate ---
            try:
                tool_obj = _get_tool(tool_call.tool_name)
            except KeyError as exc:
                state.record_turn(f"ERROR: {exc}", error=str(exc))
                yield state
                continue

            approved = await _gate.check(tool_call, tool_obj.risk)
            if not approved:
                state.status = LoopStatus.AWAITING_APPROVAL
                yield state
                return

            # --- tool dispatch ---
            ctx = ToolContext(
                workspace=workspace,
                session_id=sid,
                sandbox=sandbox,
            )
            try:
                args_model = _parse_args(tool_obj, tool_call.tool_input)
                result = await tool_obj.run(args_model, ctx)
            except Exception as exc:  # noqa: BLE001
                error_msg = f"Tool {tool_call.tool_name!r} raised: {exc}"
                state.record_turn(error_msg, error=error_msg)
                yield state
                continue

            # Post-edit incremental intelligence update
            if (
                result.ok
                and tool_call.tool_name in {"edit_file", "create_file", "write_file"}
                and _indexer is not None
                and _symbol_index is not None
            ):
                for rel in result.artifacts:
                    try:
                        _indexer.update_file(_symbol_index, rel)
                    except Exception:
                        pass
                if result.artifacts:
                    state.last_edited_file = result.artifacts[-1]

            diff = result.data.get("diff", "") if isinstance(result.data, dict) else ""
            state.record_turn(
                observation=result.observation,
                diff=diff,
                error="" if result.ok else result.observation,
            )
            state.artifacts.extend(result.artifacts)
            await _emit_audit(
                "tool_execution",
                turn_number=state.turn,
                tool_name=tool_call.tool_name,
                tool_args=tool_call.tool_input,
                tool_result_summary=result.observation[:500],
            )
            yield state

    return _gen()


def _get_tool(name: str):  # type: ignore[return]
    from agentx.tools.base import get
    return get(name)


def _parse_args(tool_obj, raw: dict) -> BaseModel:  # type: ignore[return]
    """Find the Args model by convention: module has <ToolName>Args."""
    import importlib
    import inspect
    mod = inspect.getmodule(tool_obj)
    if mod is None:
        from pydantic import RootModel
        return RootModel[dict].model_validate(raw)  # type: ignore[return-value]
    for _name, obj in inspect.getmembers(mod, inspect.isclass):
        if (
            issubclass(obj, BaseModel)
            and obj is not BaseModel
            and _name.endswith("Args")
        ):
            try:
                return obj.model_validate(raw)
            except ValidationError:
                continue
    # Fallback: pass raw dict wrapped in a generic model
    from pydantic import RootModel
    return RootModel[dict].model_validate(raw)  # type: ignore[return-value]
