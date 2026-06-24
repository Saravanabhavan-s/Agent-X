from __future__ import annotations

import sys
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentx.loop.state import LoopState, LoopStatus
from agentx.persistence.state_store import StateStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pg(latest_turn=None):
    pg = AsyncMock()
    pg.create_session = AsyncMock()
    pg.record_turn = AsyncMock()
    pg.update_session_status = AsyncMock()
    pg.get_latest_turn = AsyncMock(return_value=latest_turn)
    return pg


def _make_redis():
    r = AsyncMock()
    r.set_state = AsyncMock()
    r.get_state = AsyncMock(return_value=None)
    r.delete_state = AsyncMock()
    return r


def _make_state(session_id="sess-001") -> LoopState:
    return LoopState(
        session_id=session_id,
        goal="test goal",
        workspace="/tmp/ws",
        turn=3,
        last_observation="obs",
        status=LoopStatus.RUNNING,
    )


# ---------------------------------------------------------------------------
# Redis available — happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_open_session_writes_postgres_and_redis():
    pg = _make_pg()
    redis = _make_redis()
    store = StateStore(pg=pg, redis=redis)
    state = _make_state()
    await store.open_session(state)
    pg.create_session.assert_awaited_once()
    redis.set_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_turn_writes_both():
    pg = _make_pg()
    redis = _make_redis()
    store = StateStore(pg=pg, redis=redis)
    state = _make_state()
    await store.persist_turn(state, tool_name="read_file", tool_input={"path": "f.py"})
    pg.record_turn.assert_awaited_once()
    redis.set_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_state_returns_redis_data_when_available():
    pg = _make_pg()
    redis = _make_redis()
    cached = {"turn": 3, "status": "running", "last_observation": "obs"}
    redis.get_state = AsyncMock(return_value=cached)
    store = StateStore(pg=pg, redis=redis)
    result = await store.load_state("sess-001")
    assert result == cached
    pg.get_latest_turn.assert_not_awaited()


# ---------------------------------------------------------------------------
# Redis unavailable — degrade path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_state_falls_back_to_postgres_on_connection_error():
    pg = _make_pg()
    redis = _make_redis()
    redis.get_state = AsyncMock(side_effect=ConnectionError("Redis down"))

    # Simulate a Turn row returned from Postgres
    fake_turn = MagicMock()
    fake_turn.turn_number = 5
    fake_turn.observation = "latest obs from pg"
    pg.get_latest_turn = AsyncMock(return_value=fake_turn)

    store = StateStore(pg=pg, redis=redis)
    result = await store.load_state("sess-001")
    assert result is not None
    assert result["turn"] == 5
    assert result["last_observation"] == "latest obs from pg"


@pytest.mark.asyncio
async def test_redis_unavailable_warning_emitted_once(capsys):
    pg = _make_pg()
    redis = _make_redis()
    redis.set_state = AsyncMock(side_effect=ConnectionError("Redis down"))
    pg.create_session = AsyncMock()

    store = StateStore(pg=pg, redis=redis)
    state = _make_state("sess-warn")
    # Trigger the warning twice — should only print once
    await store._cache_state(state)
    await store._cache_state(state)

    captured = capsys.readouterr()
    warnings = [l for l in captured.err.splitlines() if "degrading" in l]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_redis_unavailable_does_not_prevent_postgres_write():
    pg = _make_pg()
    redis = _make_redis()
    redis.set_state = AsyncMock(side_effect=ConnectionError("Redis down"))

    store = StateStore(pg=pg, redis=redis)
    state = _make_state()
    # persist_turn should still write to Postgres even if Redis fails
    await store.persist_turn(state, tool_name="bash", tool_input={"command": "ls"})
    pg.record_turn.assert_awaited_once()


# ---------------------------------------------------------------------------
# Session rebuild from Postgres
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rebuild_returns_none_when_no_turns():
    pg = _make_pg(latest_turn=None)
    store = StateStore(pg=pg)
    result = await store._rebuild_from_postgres("sess-empty")
    assert result is None


@pytest.mark.asyncio
async def test_rebuild_returns_state_dict_from_latest_turn():
    pg = _make_pg()
    fake_turn = MagicMock()
    fake_turn.turn_number = 7
    fake_turn.observation = "rebuilt obs"
    pg.get_latest_turn = AsyncMock(return_value=fake_turn)

    store = StateStore(pg=pg)
    result = await store._rebuild_from_postgres("sess-rebuild")
    assert result["turn"] == 7
    assert result["last_observation"] == "rebuilt obs"
    assert result["status"] == LoopStatus.RUNNING.value


@pytest.mark.asyncio
async def test_no_redis_load_state_goes_to_postgres():
    pg = _make_pg()
    fake_turn = MagicMock()
    fake_turn.turn_number = 2
    fake_turn.observation = "obs"
    pg.get_latest_turn = AsyncMock(return_value=fake_turn)

    store = StateStore(pg=pg, redis=None)
    result = await store.load_state("sess-nored")
    assert result is not None
    pg.get_latest_turn.assert_awaited_once()
