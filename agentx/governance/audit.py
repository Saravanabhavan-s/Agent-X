from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field

from agentx.persistence.models import AuditLog

logger = logging.getLogger(__name__)

_MAX_SUMMARY = 500


@dataclass
class AuditEntry:
    session_id: str
    event_type: str  # "model_response" | "tool_execution" | "tool_error" | "loop_done" | ...
    turn_number: int = 0
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    tool_result_summary: str = ""
    model_response_summary: str = ""


def _trunc(text: str) -> str:
    return text[:_MAX_SUMMARY]


class AuditWriter:
    """Append-only audit log writer backed by Postgres.

    Failures are caught and logged to stderr — never propagated to the caller.
    """

    def __init__(self, session_factory) -> None:
        self._factory = session_factory

    async def write(self, entry: AuditEntry) -> None:
        try:
            await self._write_unsafe(entry)
        except Exception as exc:  # noqa: BLE001
            print(f"[audit] write failed (non-fatal): {exc}", file=sys.stderr)

    async def _write_unsafe(self, entry: AuditEntry) -> None:
        row = AuditLog(
            session_id=entry.session_id,
            event=entry.event_type,
            turn_number=entry.turn_number,
            tool_name=entry.tool_name,
            tool_args=_trunc(json.dumps(entry.tool_args, default=str)),
            tool_result_summary=_trunc(entry.tool_result_summary),
            model_response_summary=_trunc(entry.model_response_summary),
            detail="",
        )
        async with self._factory() as db:
            db.add(row)
            await db.commit()


class InMemoryAuditWriter:
    """Test double — stores entries in a list, never hits a DB."""

    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def write(self, entry: AuditEntry) -> None:
        self.entries.append(entry)
