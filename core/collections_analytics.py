"""Run the collections SQL in /sql against a portfolio, in an in-memory DuckDB."""

from __future__ import annotations

import pandas as pd

from core.db import connect, query
from core.portfolio import Portfolio

ANALYTICS = [
    "collections_kpis",
    "dpd_buckets",
    "roll_rates",
    "cure_rate",
    "recovery_rate",
    "days_to_resolution",
    "vintage_curves",
]


def run_analytics(portfolio: Portfolio) -> dict[str, pd.DataFrame]:
    con = connect()
    for name, df in portfolio.tables().items():
        con.register(name, df)
    out = {"episodes": query(con, "delinquency_episodes")}
    con.register("episodes", out["episodes"])
    for name in ANALYTICS:
        out[name] = query(con, name)
    return out


def roll_rate_matrix(roll_rates: pd.DataFrame) -> pd.DataFrame:
    order = ["current", "1-30", "31-60", "61-90", "90+", "charged_off"]
    matrix = roll_rates.pivot(index="from_bucket", columns="to_bucket", values="roll_rate")
    rows = [b for b in order if b in matrix.index]
    cols = [b for b in order if b in matrix.columns]
    return matrix.reindex(index=rows, columns=cols).fillna(0.0)
