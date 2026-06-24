from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis


class RedisLayer:
    """Hot-state cache + pub/sub for the agent loop.

    Falls back gracefully if Redis is unavailable — callers catch ConnectionError.
    """

    _KEY_STATE = "agentx:session:{sid}:state"
    _KEY_LOCK = "agentx:session:{sid}:lock"
    _CHANNEL = "agentx:session:{sid}:events"
    _TTL = 3600  # 1 hour

    def __init__(self, client: Redis) -> None:
        self._r = client

    # --- State cache ---

    async def set_state(self, session_id: str, data: dict[str, Any]) -> None:
        key = self._KEY_STATE.format(sid=session_id)
        await self._r.setex(key, self._TTL, json.dumps(data))

    async def get_state(self, session_id: str) -> dict[str, Any] | None:
        key = self._KEY_STATE.format(sid=session_id)
        raw = await self._r.get(key)
        return json.loads(raw) if raw else None

    async def delete_state(self, session_id: str) -> None:
        key = self._KEY_STATE.format(sid=session_id)
        await self._r.delete(key)

    # --- Distributed lock ---

    async def acquire_lock(self, session_id: str, ttl: int = 30) -> bool:
        key = self._KEY_LOCK.format(sid=session_id)
        return bool(await self._r.set(key, "1", ex=ttl, nx=True))

    async def release_lock(self, session_id: str) -> None:
        key = self._KEY_LOCK.format(sid=session_id)
        await self._r.delete(key)

    # --- Pub/sub events ---

    async def publish(self, session_id: str, event: dict[str, Any]) -> None:
        channel = self._CHANNEL.format(sid=session_id)
        await self._r.publish(channel, json.dumps(event))

    def subscribe_channel(self, session_id: str) -> str:
        return self._CHANNEL.format(sid=session_id)
