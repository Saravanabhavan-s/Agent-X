from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LoopStatus(str, Enum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"
    MAX_TURNS_REACHED = "max_turns_reached"


@dataclass
class LoopState:
    session_id: str
    goal: str
    workspace: str
    status: LoopStatus = LoopStatus.RUNNING
    turn: int = 0
    last_observation: str = ""
    last_diff: str = ""
    error_log: str = ""
    history: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    # Repo acquisition metadata — populated when --repo flag is used
    repo_url: str | None = None
    repo_type: str | None = None
    primary_language: str | None = None
    repo_context: dict | None = None
    health_score: float | None = None

    def record_turn(self, observation: str, diff: str = "", error: str = "") -> None:
        self.turn += 1
        self.history.append(observation)
        self.last_observation = observation
        if diff:
            self.last_diff = diff
        if error:
            self.error_log = error

    def add_correction(self, text: str) -> None:
        """Inject a correction into error_log so assembler surfaces it next turn."""
        self.error_log = text
