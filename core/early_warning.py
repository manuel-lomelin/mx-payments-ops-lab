"""Explainable early-warning score: a points table, not a model.

Each feature earns up to `weight` points, reaching full weight at `cap`. The score is the
sum of points, so every point can be traced back to one behaviour in the account history.
"""

from __future__ import annotations

import pandas as pd

from core.config import load_config
from core.portfolio import Portfolio

FEATURES = [
    "utilization_spike",
    "partial_payments_3m",
    "missed_payments_3m",
    "broken_ptp_6m",
    "current_dpd",
]


def compute_features(portfolio: Portfolio, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """One row per account using only data up to and including `as_of` (no look-ahead)."""
    s = portfolio.statements
    as_of = pd.Timestamp(as_of) if as_of is not None else s["statement_month"].max()
    hist = s[s["statement_month"] <= as_of].sort_values(["account_id", "statement_month"])
    g = hist.groupby("account_id")

    latest = g.tail(1).set_index("account_id")
    last3 = g.tail(3)
    prior3 = hist[g.cumcount(ascending=False).between(1, 3)]  # the 3 statements before latest

    owed = last3["amount_due"] > 0
    partial = owed & (last3["paid_amount"] > 0) & (last3["paid_amount"] < last3["amount_due"])
    missed = owed & (last3["paid_amount"] == 0)

    p = portfolio.promises
    window_start = as_of - pd.DateOffset(months=6)
    # A promise made at month t is only known to be broken after month t+1's statement.
    known = p[(p["created_at"] < as_of) & (p["created_at"] >= window_start)]
    broken = known[known["outcome"] == "broken"].groupby("account_id").size()

    feats = pd.DataFrame(index=latest.index)
    feats["utilization_spike"] = (
        latest["utilization"] - prior3.groupby("account_id")["utilization"].mean()
    ).fillna(0.0)
    feats["partial_payments_3m"] = partial.groupby(last3["account_id"]).sum()
    feats["missed_payments_3m"] = missed.groupby(last3["account_id"]).sum()
    feats["broken_ptp_6m"] = broken.reindex(feats.index, fill_value=0)
    feats["current_dpd"] = latest["dpd"]
    feats["dpd_bucket"] = latest["dpd_bucket"]
    feats["status"] = latest["status"]
    feats["balance"] = latest["balance"]
    feats["past_due_amount"] = latest["past_due_amount"]
    feats["amount_due"] = latest["amount_due"]
    feats["as_of"] = as_of
    return feats.reset_index()


def score(features: pd.DataFrame, cfg: dict | None = None) -> pd.DataFrame:
    cfg = cfg or load_config("early_warning")
    out = features.copy()
    total = 0
    for name, spec in cfg["features"].items():
        ratio = (out[name].astype(float) / spec["cap"]).clip(lower=0, upper=1)
        out[f"pts_{name}"] = (ratio * spec["weight"]).round(1)
        total = total + out[f"pts_{name}"]
    out["risk_score"] = total.round(1)
    bands = sorted(cfg["bands"].items(), key=lambda kv: kv[1])
    out["risk_band"] = "low"
    for band, threshold in bands:
        out.loc[out["risk_score"] >= threshold, "risk_band"] = band
    pts = out[[f"pts_{n}" for n in cfg["features"]]]
    out["top_driver"] = pts.idxmax(axis=1).str.removeprefix("pts_").where(pts.max(axis=1) > 0)
    return out


def contributions(row: pd.Series, cfg: dict | None = None) -> pd.DataFrame:
    """Per-feature explanation for one scored account."""
    cfg = cfg or load_config("early_warning")
    return pd.DataFrame(
        [
            {
                "feature": name,
                "label": spec["label"],
                "value": row[name],
                "points": row[f"pts_{name}"],
                "max_points": spec["weight"],
            }
            for name, spec in cfg["features"].items()
        ]
    )


def backtest(portfolio: Portfolio) -> pd.DataFrame:
    """Score at month T-1, then check who rolled to a worse bucket at month T."""
    months = sorted(portfolio.statements["statement_month"].unique())
    t_prev, t_last = pd.Timestamp(months[-2]), pd.Timestamp(months[-1])
    scored = score(compute_features(portfolio, t_prev))
    nxt = portfolio.statements[portfolio.statements["statement_month"] == t_last]
    nxt = nxt.set_index("account_id")["dpd"]
    scored["next_dpd"] = scored["account_id"].map(nxt)
    scored["rolled"] = (scored["next_dpd"] > 0) & (scored["next_dpd"] > scored["current_dpd"])
    active = scored[scored["status"] == "active"]
    return (
        active.groupby("risk_band", observed=True)
        .agg(accounts=("account_id", "size"), roll_rate=("rolled", "mean"))
        .reindex(["low", "medium", "high"])
        .dropna(how="all")
        .reset_index()
    )
