import pandas as pd
import pytest

from core.billpay_metrics import compute_metrics
from core.payments import preflight, read_payments_csv, to_instructions
from core.recon import (
    StatementNoise,
    generate_bank_statement,
    normalize_reference,
    reconcile,
    similarity,
)
from core.spei_sim import SimConfig, run_batch

QUIET = dict(reformat_reference=0, amount_drift=0, missing=0, bank_fees=0, unknown_debits=0)


@pytest.fixture(scope="module")
def run():
    report = preflight(read_payments_csv("data/sample_payments.csv"))
    return run_batch(to_instructions(report), seed=5)


def test_clean_statement_matches_exactly(run):
    stmt = generate_bank_statement(run.payments, run.attempts, StatementNoise(**QUIET))
    res = reconcile(run.payments, stmt)
    s = res.summary
    assert s["exact"] == s["expected_payments"]
    assert s["unmatched_payments"] == s["unmatched_lines"] == 0
    assert s["recon_error_rate"] == 0
    assert s["reversal_pairs"] == int((run.attempts["status"] == "returned").sum())


def test_reformatted_references_match_fuzzily(run):
    noise = StatementNoise(**{**QUIET, "reformat_reference": 1.0})
    res = reconcile(run.payments, generate_bank_statement(run.payments, run.attempts, noise))
    assert res.summary["fuzzy"] == res.summary["expected_payments"]
    assert res.summary["unmatched_payments"] == 0


def test_amount_drift_is_fuzzy_and_counted_as_exception(run):
    noise = StatementNoise(**{**QUIET, "amount_drift": 1.0})
    res = reconcile(run.payments, generate_bank_statement(run.payments, run.attempts, noise))
    assert res.summary["fuzzy"] == res.summary["matched_with_amount_diff"] > 0
    assert res.summary["recon_error_rate"] > 0
    assert (res.matches["amount_diff"].abs() <= 1.0).all()


def test_missing_lines_and_unknown_debits_surface_both_ways(run):
    noise = StatementNoise(**{**QUIET, "missing": 1.0, "bank_fees": 2, "unknown_debits": 3})
    stmt = generate_bank_statement(run.payments, run.attempts, noise, seed=1)
    res = reconcile(run.payments, stmt)
    assert len(res.unmatched_payments) == res.summary["expected_payments"]
    assert len(res.unmatched_lines) == 5
    assert set(res.unmatched_lines["description"]) == {"COMISION SPEI", "CARGO DOMICILIADO"}


def test_amount_outside_tolerance_is_not_matched():
    pay = pd.DataFrame(
        [
            {
                "payment_id": "P1",
                "final_status": "settled",
                "reference": "55",
                "amount_mxn": 100.0,
                "beneficiary": "Proveedor Demo 001",
                "settled_at": pd.Timestamp("2026-03-02 10:00"),
            }
        ]
    )
    stmt = pd.DataFrame(
        [
            {
                "line_id": "L1",
                "value_date": pd.Timestamp("2026-03-02").date(),
                "description": "SPEI ENVIADO PROVEEDOR DEMO 001",
                "reference": "55",
                "amount": -105.0,
            }
        ]
    )
    res = reconcile(pay, stmt)
    assert res.matches.empty
    assert res.summary["recon_error_rate"] == 1.0
    stmt.loc[0, "amount"] = -100.5
    assert reconcile(pay, stmt).matches.loc[0, "match_type"] == "fuzzy"


def test_helpers():
    assert normalize_reference("REF 0001234") == "1234"
    assert normalize_reference(None) == ""
    assert similarity("", "x") == 0.0
    assert similarity("ABC", "ABC") == 1.0


def test_statement_without_attempts_and_empty_recon():
    empty = pd.DataFrame(columns=["payment_id", "final_status", "first_sent_at"])
    stmt = generate_bank_statement(empty, None, StatementNoise(**QUIET))
    assert stmt.empty
    res = reconcile(empty, stmt)
    assert res.summary["recon_error_rate"] == 0.0


def test_metrics_from_sql(run):
    stmt = generate_bank_statement(run.payments, run.attempts)
    m = compute_metrics(run, reconcile(run.payments, stmt))
    k = m.kpis
    assert k["payments"] == len(run.payments)
    assert 0 < k["success_rate"] <= 1
    assert k["p90_settlement_s"] >= k["median_settlement_s"] > 0
    assert 0 <= k["recon_error_rate"] < 0.2
    assert m.returns_by_reason["share_of_returns"].sum() == pytest.approx(1.0)
    assert set(m.time_to_resolve["resolution_path"]) <= {"auto-retry recovered", "needs human"}


def test_metrics_without_returns():
    cfg = SimConfig.from_config(p_settled=1, p_returned=0, p_pending=0)
    report = preflight(read_payments_csv("data/sample_payments.csv"))
    m = compute_metrics(run_batch(to_instructions(report), cfg=cfg))
    assert m.kpis["success_rate"] == 1.0
    assert m.kpis["median_hours_to_resolve_failed"] is None
    assert m.returns_by_reason.empty
    assert "recon_error_rate" not in m.kpis
