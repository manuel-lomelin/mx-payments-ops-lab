"""SPEI transfer simulator with returns (devoluciones), pending states and retries.

Everything here is synthetic. Return reasons are illustrative labels from
config/spei_returns.yaml, not Banxico's official catalog.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from core.config import load_config
from core.payments import PaymentInstruction
from core.retry import Action, RetryPolicy


@dataclass
class SimConfig:
    p_settled: float
    p_returned: float
    p_pending: float
    latency: dict[str, dict[str, float]]
    pending_settles: float
    pending_return_reason: str
    reasons: list[dict]
    human_hours: dict[str, float]

    @classmethod
    def from_config(cls, **overrides) -> SimConfig:
        cfg = load_config("spei_returns")
        retry = load_config("retry_policy")
        p = cfg["outcome_probabilities"]
        sim = cls(
            p_settled=p["settled"],
            p_returned=p["returned"],
            p_pending=p["pending"],
            latency=cfg["latency_seconds"],
            pending_settles=cfg["pending_resolution"]["settled"],
            pending_return_reason=cfg["pending_resolution"]["returned_reason"],
            reasons=cfg["return_reasons"],
            human_hours=retry["human_resolution_hours"],
        )
        for key, value in overrides.items():
            setattr(sim, key, value)
        sim.normalize()
        return sim

    def normalize(self) -> None:
        total = self.p_settled + self.p_returned + self.p_pending
        if total <= 0:
            raise ValueError("Outcome probabilities must sum to more than 0")
        self.p_settled /= total
        self.p_returned /= total
        self.p_pending /= total

    def reason_label(self, reason_id: str | None) -> str | None:
        return next((r["label"] for r in self.reasons if r["id"] == reason_id), reason_id)


def _lognormal(rng: random.Random, median: float, sigma: float) -> float:
    return rng.lognormvariate(math.log(median), sigma)


@dataclass(frozen=True)
class AttemptResult:
    status: str  # settled | returned
    reason: str | None
    was_pending: bool
    latency_s: float


def simulate_attempt(rng: random.Random, cfg: SimConfig) -> AttemptResult:
    """Simulate one SPEI send until it reaches a final status."""
    u = rng.random()
    if u < cfg.p_settled:
        lat = cfg.latency["settled"]
        return AttemptResult("settled", None, False, _lognormal(rng, lat["median"], lat["sigma"]))
    if u < cfg.p_settled + cfg.p_returned:
        lat = cfg.latency["returned"]
        reason = rng.choices(
            [r["id"] for r in cfg.reasons], weights=[r["weight"] for r in cfg.reasons]
        )[0]
        latency = _lognormal(rng, lat["median"], lat["sigma"])
        return AttemptResult("returned", reason, False, latency)
    lat = cfg.latency["pending"]
    wait = _lognormal(rng, lat["median"], lat["sigma"])
    if rng.random() < cfg.pending_settles:
        return AttemptResult("settled", None, True, wait)
    return AttemptResult("returned", cfg.pending_return_reason, True, wait)


@dataclass
class BatchResult:
    payments: pd.DataFrame
    attempts: pd.DataFrame

    @property
    def human_queue(self) -> pd.DataFrame:
        return self.payments[self.payments["final_status"] == "needs_human"]


def run_batch(
    instructions: list[PaymentInstruction],
    cfg: SimConfig | None = None,
    policy: RetryPolicy | None = None,
    seed: int = 7,
    start: datetime = datetime(2026, 3, 2, 10, 0, 0),
) -> BatchResult:
    cfg = cfg or SimConfig.from_config()
    policy = policy or RetryPolicy.from_config()
    rng = random.Random(seed)
    attempts: list[dict] = []
    payments: list[dict] = []

    for i, ins in enumerate(instructions):
        first_sent = start + timedelta(seconds=i * 0.5)  # files are released in a stream
        sent_at = first_sent
        attempt = 0
        reasons_seen: list[str] = []
        while True:
            attempt += 1
            res = simulate_attempt(rng, cfg)
            resolved_at = sent_at + timedelta(seconds=res.latency_s)
            attempts.append(
                {
                    "payment_id": ins.payment_id,
                    "attempt": attempt,
                    "sent_at": sent_at,
                    "resolved_at": resolved_at,
                    "status": res.status,
                    "was_pending": res.was_pending,
                    "reason": res.reason,
                    "reason_label": cfg.reason_label(res.reason),
                    "latency_s": round(res.latency_s, 3),
                }
            )
            if res.reason:
                reasons_seen.append(res.reason)
            decision = policy.decide(res.status, res.reason, attempt)
            if decision.action == Action.RETRY:
                sent_at = resolved_at + timedelta(seconds=policy.backoff_seconds(attempt, rng))
                continue
            break

        settled = res.status == "settled"
        if settled:
            final_at = resolved_at
        else:
            hours = _lognormal(rng, cfg.human_hours["median"], cfg.human_hours["sigma"])
            final_at = resolved_at + timedelta(hours=hours)  # simulated analyst resolution
        payments.append(
            {
                "payment_id": ins.payment_id,
                "beneficiary": ins.beneficiary,
                "clabe": ins.clabe,
                "bank_name": ins.bank_name,
                "amount_mxn": float(ins.amount_mxn),
                "reference": ins.reference,
                "concept": ins.concept,
                "final_status": "settled" if settled else "needs_human",
                "attempts": attempt,
                "had_return": bool(reasons_seen),
                "first_return_reason": reasons_seen[0] if reasons_seen else None,
                "last_reason": res.reason,
                "last_reason_label": cfg.reason_label(res.reason),
                "retries_exhausted": decision.retries_exhausted,
                "next_action": decision.next_action,
                "first_sent_at": first_sent,
                "settled_at": resolved_at if settled else None,
                "resolved_at": final_at,
                "settlement_s": (resolved_at - first_sent).total_seconds() if settled else None,
                "resolution_s": (final_at - first_sent).total_seconds(),
            }
        )

    return BatchResult(pd.DataFrame(payments), pd.DataFrame(attempts))
