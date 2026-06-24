from __future__ import annotations

import sys

from agentx.loop.state import LoopState, LoopStatus
from agentx.persistence.postgres import PostgresStore
from agentx.persistence.redis_layer import RedisLayer


class StateStore:
    """Combines Postgres (durable) and Redis (hot) into a single interface.

    Postgres is the system of record. Redis is best-effort: if it's down,
    we degrade gracefully and rely on Postgres for state reconstruction.
    One warning is emitted to stderr per session the first time Redis fails.
    """

    def __init__(self, pg: PostgresStore, redis: RedisLayer | None = None) -> None:
        self._pg = pg
        self._redis = redis
        self._redis_warned: set[str] = set()  # session IDs that already got a warning

    # ------------------------------------------------------------------ write

    async def open_session(self, state: LoopState) -> None:
        await self._pg.create_session(state)
        await self._cache_state(state)

    async def persist_turn(
        self,
        state: LoopState,
        tool_name: str,
        tool_input: dict,
    ) -> None:
        await self._pg.record_turn(
            state,
            tool_name=tool_name,
            tool_input=tool_input,
            observation=state.last_observation,
            diff=state.last_diff,
            ok=state.status == LoopStatus.RUNNING or state.status == LoopStatus.DONE,
        )
        await self._cache_state(state)

    async def close_session(self, state: LoopState) -> None:
        await self._pg.update_session_status(state.session_id, state.status)
        if self._redis:
            try:
                await self._redis.delete_state(state.session_id)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ read

    async def load_state(self, session_id: str) -> dict | None:
        """Return cached state dict for session_id.

        Tries Redis first; on ConnectionError falls back to Postgres turns table.
        Returns None if session has no recorded turns.
        """
        if self._redis is not None:
            try:
                data = await self._redis.get_state(session_id)
                if data is not None:
                    return data
            except Exception:  # noqa: BLE001
                self._warn_redis_down(session_id)
                # Redis unavailable — rebuild from Postgres
                return await self._rebuild_from_postgres(session_id)

        # No Redis configured — go straight to Postgres
        return await self._rebuild_from_postgres(session_id)

    # ------------------------------------------------------------------ internals

    async def _cache_state(self, state: LoopState) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set_state(
                state.session_id,
                {
                    "turn": state.turn,
                    "status": state.status.value,
                    "last_observation": state.last_observation,
                },
            )
        except Exception:  # noqa: BLE001
            self._warn_redis_down(state.session_id)
            # Redis down — writes already go to Postgres via persist_turn; nothing else needed

    async def _rebuild_from_postgres(self, session_id: str) -> dict | None:
        """Reconstruct minimal hot-state from the latest Turn row in Postgres."""
        latest = await self._pg.get_latest_turn(session_id)
        if latest is None:
            return None
        return {
            "turn": latest.turn_number,
            "status": LoopStatus.RUNNING.value,
            "last_observation": latest.observation,
        }

    def _warn_redis_down(self, session_id: str) -> None:
        if session_id not in self._redis_warned:
            self._redis_warned.add(session_id)
            print(
                f"[state_store] Redis unavailable for session {session_id!r} — "
                "degrading to Postgres-only mode.",
                file=sys.stderr,
            )
