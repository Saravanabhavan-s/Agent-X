from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TokenBudget:
    """Tracks token spend across context assembly slots."""

    total: int
    spent: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.spent)

    def fits(self, tokens: int) -> bool:
        return tokens <= self.remaining

    def consume(self, tokens: int) -> None:
        self.spent += tokens


def estimate_tokens(text: str) -> int:
    """Cheap word-count heuristic: ~1.3 tokens per word."""
    return max(1, int(len(text.split()) * 1.3))
