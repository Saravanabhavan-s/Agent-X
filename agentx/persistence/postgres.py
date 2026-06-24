from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agentx.loop.state import LoopState, LoopStatus
from agentx.persistence.models import Approval, AuditLog, Base, Session, Turn


class PostgresStore:
    def __init__(self, url: str) -> None:
        self._engine = create_async_engine(url, echo=False, pool_pre_ping=True)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def init_schema(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def create_session(self, state: LoopState) -> None:
        async with self._session_factory() as db:
            db.add(
                Session(
                    id=UUID(state.session_id),
                    goal=state.goal,
                    workspace=state.workspace,
                    status=state.status.value,
                    repo_url=state.repo_url,
                    repo_type=state.repo_type,
                    primary_language=state.primary_language,
                    repo_context=state.repo_context,
                    health_score=state.health_score,
                )
            )
            await db.commit()

    async def record_turn(
        self,
        state: LoopState,
        tool_name: str,
        tool_input: dict,
        observation: str,
        diff: str = "",
        ok: bool = True,
    ) -> None:
        async with self._session_factory() as db:
            db.add(
                Turn(
                    session_id=UUID(state.session_id),
                    turn_number=state.turn,
                    tool_name=tool_name,
                    tool_input=json.dumps(tool_input),
                    observation=observation,
                    diff=diff,
                    ok=ok,
                )
            )
            await db.commit()

    async def update_session_status(self, session_id: str, status: LoopStatus) -> None:
        async with self._session_factory() as db:
            result = await db.execute(select(Session).where(Session.id == UUID(session_id)))
            row = result.scalar_one_or_none()
            if row:
                row.status = status.value
                await db.commit()

    async def log_audit(self, session_id: str, event: str, detail: str = "") -> None:
        async with self._session_factory() as db:
            db.add(AuditLog(session_id=session_id, event=event, detail=detail))
            await db.commit()

    async def get_latest_turn(self, session_id: str):
        """Return the highest-turn-number Turn row for session_id, or None."""
        from sqlalchemy import desc
        async with self._session_factory() as db:
            result = await db.execute(
                select(Turn)
                .where(Turn.session_id == UUID(session_id))
                .order_by(desc(Turn.turn_number))
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def close(self) -> None:
        await self._engine.dispose()
