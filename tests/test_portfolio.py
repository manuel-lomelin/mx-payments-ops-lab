from datetime import date

import pandas as pd
import pytest

from core.collections_analytics import roll_rate_matrix, run_analytics
from core.portfolio import add_months, dpd_bucket, generate_portfolio, month_end


@pytest.fixture(scope="module")
def portfolio():
    return generate_portfolio(n_accounts=250, seed=99)


@pytest.fixture(scope="module")
def analytics(portfolio):
    return run_analytics(portfolio)


@pytest.mark.parametrize(
    ("dpd", "bucket"),
    [
        (0, "current"),
        (-1, "current"),
        (1, "1-30"),
        (30, "1-30"),
        (31, "31-60"),
        (60, "31-60"),
        (61, "61-90"),
        (90, "61-90"),
        (91, "90+"),
        (400, "90+"),
    ],
)
def test_dpd_bucket_edges(dpd, bucket):
    assert dpd_bucket(dpd) == bucket


def test_date_helpers():
    assert month_end(date(2024, 2, 3)) == date(2024, 2, 29)
    assert month_end(date(2026, 12, 1)) == date(2026, 12, 31)
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 3, 31), -14) == date(2025, 1, 31)


def test_portfolio_is_seeded(portfolio):
    again = generate_portfolio(n_accounts=250, seed=99)
    pd.testing.assert_frame_equal(portfolio.statements, again.statements)
    pd.testing.assert_frame_equal(portfolio.promises, again.promises)
    other = generate_portfolio(n_accounts=250, seed=100)
    assert not portfolio.statements.equals(other.statements)


def test_twelve_months_per_account(portfolio):
    counts = portfolio.statements.groupby("account_id")["statement_month"].nunique()
    assert (counts == 12).all()
    assert len(counts) == 250
    assert portfolio.statements["statement_month"].max().date() == date(2026, 9, 30)


def test_statement_invariants(portfolio):
    s = portfolio.statements
    assert (s["dpd_bucket"] == s["dpd"].map(dpd_bucket)).all()
    assert (s["balance"] >= 0).all() and (s["paid_amount"] >= 0).all()
    assert s["utilization"].between(0, 1.0001).all()
    assert set(s["status"]) <= {"active", "charged_off"}
    assert (s.loc[s["status"] == "charged_off", "dpd"] >= 180).all()
    assert set(portfolio.accounts["segment"]) == {"micro", "small", "medium"}
    assert portfolio.accounts["company_name"].str.startswith("PyME Demo").all()


def test_promise_outcomes_match_next_month_payment(portfolio):
    p = portfolio.promises
    assert set(p["outcome"]) == {"kept", "broken", "pending"}
    resolved = p[p["outcome"] != "pending"]
    kept = resolved["paid_amount_next"] >= 0.95 * resolved["promised_amount"]
    assert (kept == (resolved["outcome"] == "kept")).all()
    assert (p.loc[p["outcome"] == "pending", "created_at"].dt.date == date(2026, 9, 30)).all()


def test_bucket_shares_sum_to_one(analytics):
    shares = analytics["dpd_buckets"].groupby("statement_month")["share_accounts"].sum()
    assert shares.round(9).eq(1).all()


def test_roll_rate_rows_sum_to_one(analytics):
    matrix = roll_rate_matrix(analytics["roll_rates"])
    assert matrix.sum(axis=1).round(9).eq(1).all()
    assert list(matrix.index)[:2] == ["current", "1-30"]
    # current accounts can only stay current or roll to 1-30 in one month
    assert matrix.loc["current"].drop(["current", "1-30"]).sum() == 0


def test_cure_and_recovery_rates_are_rates(analytics):
    cure = analytics["cure_rate"]
    assert cure["cure_rate"].between(0, 1).all()
    assert len(cure) == 11  # last month has no t+1
    rec = analytics["recovery_rate"]
    assert (rec["recovery_rate"].dropna() >= 0).all()
    total = rec[rec["segment"].isna()].iloc[0]
    assert total["accounts_90_plus"] == rec["accounts_90_plus"].iloc[:-1].sum()


def test_episodes_and_days_to_resolution(analytics):
    ep = analytics["episodes"]
    resolved = ep[ep["resolved"]]
    assert (resolved["days_to_resolution"] > 0).all()
    assert ep.loc[~ep["resolved"], "days_to_resolution"].isna().all()
    summary = analytics["days_to_resolution"]
    assert summary["episodes"].sum() == len(ep)


def test_vintage_curves(analytics, portfolio):
    v = analytics["vintage_curves"]
    assert v["ever_30_plus_rate"].between(0, 1).all()
    assert set(v["cohort"]) <= set(portfolio.accounts["cohort"])


def test_kpis(analytics):
    k = analytics["collections_kpis"].iloc[0]
    assert k["accounts"] == 250
    assert 0 < k["delinquency_rate"] < 1
    assert k["dpd_30_plus_rate"] <= k["delinquency_rate"]
