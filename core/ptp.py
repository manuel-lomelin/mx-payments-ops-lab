"""Promise-to-pay tracker: record promises and summarize kept/broken outcomes."""

from __future__ import annotations

from datetime import date

import pandas as pd

from core.db import connect, query

OUTCOMES = ("pending", "kept", "broken")


def add_promise(
    promises: pd.DataFrame,
    account_id: str,
    promised_amount: float,
    promised_date: date,
    created_at: date,
    dpd_at_promise: int,
) -> pd.DataFrame:
    if promised_amount <= 0:
        raise ValueError("Promised amount must be greater than 0")
    if promised_date < created_at:
        raise ValueError("Promised date cannot be before the promise is made")
    next_id = f"PTP{len(promises) + 1:05d}"
    row = pd.DataFrame(
        [
            {
                "promise_id": next_id,
                "account_id": account_id,
                "created_at": pd.Timestamp(created_at),
                "promised_date": pd.Timestamp(promised_date),
                "promised_amount": float(promised_amount),
                "dpd_at_promise": int(dpd_at_promise),
                "outcome": "pending",
                "paid_amount_next": None,
            }
        ]
    )
    return pd.concat([promises, row], ignore_index=True)


def resolve_promise(promises: pd.DataFrame, promise_id: str, paid_amount: float) -> pd.DataFrame:
    """Mark a pending promise kept (paid >= 95% of promised) or broken."""
    out = promises.copy()
    idx = out.index[out["promise_id"] == promise_id]
    if len(idx) != 1:
        raise KeyError(promise_id)
    i = idx[0]
    if out.at[i, "outcome"] != "pending":
        raise ValueError(f"{promise_id} is already {out.at[i, 'outcome']}")
    out.at[i, "paid_amount_next"] = float(paid_amount)
    kept = paid_amount >= 0.95 * out.at[i, "promised_amount"]
    out.at[i, "outcome"] = "kept" if kept else "broken"
    return out


def summarize(promises: pd.DataFrame) -> dict[str, pd.DataFrame]:
    con = connect()
    return {
        "by_bucket": query(con, "ptp_outcomes", promises=promises),
        "by_month": query(con, "ptp_by_month"),
    }
