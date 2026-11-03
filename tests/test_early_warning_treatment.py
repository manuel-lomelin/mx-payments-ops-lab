import pandas as pd
import pytest

from core.early_warning import FEATURES, backtest, compute_features, contributions, score
from core.portfolio import generate_portfolio
from core.treatment import assign, assign_all


@pytest.fixture(scope="module")
def portfolio():
    return generate_portfolio(n_accounts=300, seed=7)


@pytest.fixture(scope="module")
def scored(portfolio):
    return score(compute_features(portfolio))


def test_features_one_row_per_account(portfolio, scored):
    assert len(scored) == 300
    assert scored["account_id"].is_unique
    assert set(FEATURES) <= set(scored.columns)


def test_score_is_sum_of_points_and_bounded(scored):
    pts = scored[[f"pts_{f}" for f in FEATURES]].sum(axis=1).round(1)
    assert (abs(pts - scored["risk_score"]) < 0.2).all()
    assert scored["risk_score"].between(0, 100).all()


def test_bands_follow_thresholds(scored):
    assert (scored.loc[scored["risk_score"] >= 50, "risk_band"] == "high").all()
    assert (scored.loc[scored["risk_score"] < 25, "risk_band"] == "low").all()


def test_features_do_not_look_ahead(portfolio):
    months = sorted(portfolio.statements["statement_month"].unique())
    early = compute_features(portfolio, months[5])
    assert (early["as_of"] == months[5]).all()
    # Changing statements after the cut-off must not change features at the cut-off.
    mutated = generate_portfolio(n_accounts=300, seed=7)
    late = mutated.statements["statement_month"] > months[5]
    mutated.statements.loc[late, "paid_amount"] = 0
    pd.testing.assert_frame_equal(early, compute_features(mutated, months[5]))


def test_hand_built_account_gets_expected_points():
    cfg = {
        "features": {f: {"weight": 20, "cap": 1, "label": f} for f in FEATURES},
        "bands": {"low": 0, "medium": 25, "high": 50},
    }
    row = pd.DataFrame(
        [
            {
                "utilization_spike": 0.5,
                "partial_payments_3m": 1,
                "missed_payments_3m": 0,
                "broken_ptp_6m": 3,
                "current_dpd": 0,
            }
        ]
    )
    out = score(row, cfg)
    assert out.loc[0, "risk_score"] == 10 + 20 + 0 + 20 + 0
    assert out.loc[0, "risk_band"] == "high"
    assert out.loc[0, "top_driver"] in {"partial_payments_3m", "broken_ptp_6m"}
    explained = contributions(out.iloc[0], cfg)
    assert explained["points"].sum() == 50
    zero = score(pd.DataFrame([dict.fromkeys(FEATURES, 0)]), cfg)
    assert pd.isna(zero.loc[0, "top_driver"]) and zero.loc[0, "risk_band"] == "low"


def test_backtest_higher_bands_roll_more(portfolio):
    bt = backtest(portfolio).set_index("risk_band")
    assert bt["accounts"].sum() > 0
    assert bt.loc["high", "roll_rate"] > bt.loc["low", "roll_rate"]


@pytest.mark.parametrize(
    ("row", "stage"),
    [
        ({"dpd_bucket": "current", "risk_score": 10}, "no_action"),
        ({"dpd_bucket": "current", "risk_score": 60}, "reminder"),
        ({"dpd_bucket": "1-30", "risk_score": 10}, "nudge"),
        ({"dpd_bucket": "1-30", "risk_score": 70}, "call"),
        ({"dpd_bucket": "31-60", "risk_score": 30, "broken_ptp_6m": 1}, "payment_plan"),
        ({"dpd_bucket": "31-60", "risk_score": 30, "broken_ptp_6m": 0}, "call"),
        ({"dpd_bucket": "61-90", "risk_score": 30}, "payment_plan"),
        ({"dpd_bucket": "90+", "risk_score": 60, "segment": "medium"}, "payment_plan"),
        ({"dpd_bucket": "90+", "risk_score": 90, "segment": "medium"}, "agency_handoff"),
        ({"dpd_bucket": "90+", "risk_score": 60, "segment": "micro"}, "agency_handoff"),
        ({"dpd_bucket": "90+", "status": "charged_off"}, "agency_handoff"),
    ],
)
def test_treatment_rules(row, stage):
    assert assign(row).stage == stage


def test_unmatched_row_falls_back_to_no_action():
    assert (
        assign(
            {"dpd_bucket": "weird"},
            {
                "stages": {
                    "no_action": {"channel": "none", "max_contacts_per_week": 0, "order": 0}
                },
                "rules": [],
            },
        ).rule
        == "no rule"
    )


def test_assign_all(portfolio, scored):
    wl = assign_all(scored, portfolio.accounts)
    assert len(wl) == len(scored)
    assert (wl.loc[wl["dpd_bucket"] == "1-30", "stage"].isin(["nudge", "call"])).all()
    assert wl["stage_order"].notna().all()
