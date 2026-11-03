"""Retry and fallback policy for SPEI transfers."""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel

from core.config import load_config


class Action(StrEnum):
    DONE = "done"
    WAIT = "wait_for_final_status"
    RETRY = "retry"
    NEEDS_HUMAN = "needs_human"


class Backoff(BaseModel):
    base_seconds: float = 60
    multiplier: float = 2.0
    max_seconds: float = 900
    jitter_fraction: float = 0.1


class RetryPolicy(BaseModel):
    max_attempts: int = 3
    backoff: Backoff = Backoff()
    never_resend_pending: bool = True
    retryable_reasons: frozenset[str] = frozenset()
    next_actions: dict[str, str] = {}

    @classmethod
    def from_config(cls) -> RetryPolicy:
        cfg = load_config("retry_policy")
        returns = load_config("spei_returns")["return_reasons"]
        return cls(
            max_attempts=cfg["max_attempts"],
            backoff=Backoff(**cfg["backoff"]),
            never_resend_pending=cfg["never_resend_pending"],
            retryable_reasons=frozenset(r["id"] for r in returns if r["retryable"]),
            next_actions={r["id"]: " ".join(r["next_action"].split()) for r in returns},
        )

    def backoff_seconds(self, attempt: int, rng: random.Random | None = None) -> float:
        """Delay before attempt `attempt + 1`, given `attempt` already failed (1-based)."""
        b = self.backoff
        delay = min(b.base_seconds * b.multiplier ** (attempt - 1), b.max_seconds)
        if rng is not None and b.jitter_fraction:
            delay *= 1 + rng.uniform(-b.jitter_fraction, b.jitter_fraction)
        return delay

    def decide(self, status: str, reason: str | None, attempt: int) -> Decision:
        if status == "settled":
            return Decision(Action.DONE)
        if status == "pending":
            # Never resend while pending: wait for a final status to avoid a double payment.
            return Decision(Action.WAIT if self.never_resend_pending else Action.RETRY)
        if reason in self.retryable_reasons and attempt < self.max_attempts:
            return Decision(Action.RETRY)
        exhausted = reason in self.retryable_reasons
        return Decision(
            Action.NEEDS_HUMAN,
            next_action=self.next_actions.get(reason or "", "Review manually."),
            retries_exhausted=exhausted,
        )


@dataclass(frozen=True)
class Decision:
    action: Action
    next_action: str | None = None
    retries_exhausted: bool = False
