import random

import pytest

from core.clabe import build_clabe
from core.payments import PaymentInstruction
from core.retry import Action, RetryPolicy
from core.spei_sim import SimConfig, run_batch, simulate_attempt


def instructions(n=200):
    return [
        PaymentInstruction(
            payment_id=f"P{i:05d}",
            beneficiary="Proveedor Demo",
            clabe=build_clabe("012", "180", f"{i:011d}"),
            bank_name="BBVA MEXICO",
            amount_mxn="100.00",
            reference=str(i),
            concept="Pago",
        )
        for i in range(1, n + 1)
    ]


def test_config_loads_and_normalizes():
    cfg = SimConfig.from_config(p_settled=2, p_returned=1, p_pending=1)
    assert cfg.p_settled == pytest.approx(0.5)
    assert cfg.reason_label("NONEXISTENT_ACCOUNT") == "Cuenta inexistente"
    assert cfg.reason_label(None) is None


def test_zero_probabilities_rejected():
    with pytest.raises(ValueError):
        SimConfig.from_config(p_settled=0, p_returned=0, p_pending=0)


def test_all_settled_when_returns_disabled():
    cfg = SimConfig.from_config(p_settled=1, p_returned=0, p_pending=0)
    result = run_batch(instructions(50), cfg=cfg)
    assert (result.payments["final_status"] == "settled").all()
    assert (result.payments["attempts"] == 1).all()
    assert result.human_queue.empty
    assert result.payments["settlement_s"].median() < 30


def test_batch_is_reproducible():
    a = run_batch(instructions(), seed=3)
    b = run_batch(instructions(), seed=3)
    assert a.payments.equals(b.payments)
    assert a.attempts.equals(b.attempts)


def test_returns_route_to_retry_or_human():
    cfg = SimConfig.from_config(p_settled=0.5, p_returned=0.5, p_pending=0)
    policy = RetryPolicy.from_config()
    result = run_batch(instructions(), cfg=cfg, policy=policy, seed=11)
    pays, atts = result.payments, result.attempts
    assert atts.groupby("payment_id")["attempt"].max().max() <= policy.max_attempts
    queue = result.human_queue
    assert not queue.empty
    assert queue["next_action"].notna().all()
    # A non-retryable return is never retried.
    first = atts[atts["attempt"] == 1]
    non_retry = first[first["reason"].notna() & ~first["reason"].isin(policy.retryable_reasons)]
    assert (pays.set_index("payment_id").loc[non_retry["payment_id"], "attempts"] == 1).all()
    # Retries happen after the previous attempt resolved (no overlapping sends).
    for _, grp in atts.groupby("payment_id"):
        grp = grp.sort_values("attempt")
        assert (grp["sent_at"].iloc[1:].values >= grp["resolved_at"].iloc[:-1].values).all()


def test_pending_transfers_resolve_with_long_latency():
    cfg = SimConfig.from_config(p_settled=0, p_returned=0, p_pending=1)
    rng = random.Random(0)
    results = [simulate_attempt(rng, cfg) for _ in range(300)]
    assert all(r.was_pending for r in results)
    assert {r.status for r in results} == {"settled", "returned"}
    assert {r.reason for r in results if r.status == "returned"} == {"TIMEOUT"}
    assert min(r.latency_s for r in results) > 60


def test_policy_decisions():
    policy = RetryPolicy.from_config()
    assert policy.decide("settled", None, 1).action == Action.DONE
    assert policy.decide("pending", None, 1).action == Action.WAIT
    assert policy.decide("returned", "TIMEOUT", 1).action == Action.RETRY
    exhausted = policy.decide("returned", "TIMEOUT", policy.max_attempts)
    assert exhausted.action == Action.NEEDS_HUMAN and exhausted.retries_exhausted
    hard = policy.decide("returned", "NONEXISTENT_ACCOUNT", 1)
    assert hard.action == Action.NEEDS_HUMAN and not hard.retries_exhausted
    assert "CLABE" in hard.next_action
    assert policy.decide("returned", "UNKNOWN", 1).next_action == "Review manually."


def test_policy_can_allow_resend_of_pending():
    policy = RetryPolicy(never_resend_pending=False)
    assert policy.decide("pending", None, 1).action == Action.RETRY


def test_backoff_is_exponential_and_capped():
    policy = RetryPolicy.from_config()
    assert [policy.backoff_seconds(a) for a in (1, 2, 3)] == [60, 120, 240]
    assert policy.backoff_seconds(10) == policy.backoff.max_seconds
    jittered = policy.backoff_seconds(1, random.Random(1))
    assert 54 <= jittered <= 66
