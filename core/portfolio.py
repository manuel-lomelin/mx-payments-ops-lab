"""Seeded synthetic SME credit-line portfolio. No real companies or people.

Each account is simulated month by month from origination; the last `months` statements
are kept. Latent "distress" episodes raise utilization first and hurt payments next,
which is what gives the early-warning signals something real (synthetic) to detect.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

SEGMENTS = {
    # segment: (share, credit line range MXN, risk shift)
    "micro": (0.5, (50_000, 250_000), 0.06),
    "small": (0.35, (250_000, 1_500_000), 0.0),
    "medium": (0.15, (1_500_000, 6_000_000), -0.03),
}
INDUSTRIES = ["comercio", "manufactura", "servicios", "construccion", "logistica", "alimentos"]
STATES = {
    # state: IANA timezone (debtor local time drives the contact window)
    "Ciudad de Mexico": "America/Mexico_City",
    "Jalisco": "America/Mexico_City",
    "Nuevo Leon": "America/Monterrey",
    "Estado de Mexico": "America/Mexico_City",
    "Puebla": "America/Mexico_City",
    "Baja California": "America/Tijuana",
    "Sonora": "America/Hermosillo",
    "Chihuahua": "America/Chihuahua",
    "Quintana Roo": "America/Cancun",
    "Yucatan": "America/Merida",
}
FIRST_NAMES = [
    "Ana",
    "Luis",
    "Carmen",
    "Jorge",
    "Sofia",
    "Miguel",
    "Lucia",
    "Raul",
    "Elena",
    "Diego",
    "Patricia",
    "Hector",
    "Rosa",
    "Arturo",
    "Laura",
    "Ivan",
]

BUCKETS = ["current", "1-30", "31-60", "61-90", "90+"]


def dpd_bucket(dpd: int) -> str:
    if dpd <= 0:
        return "current"
    if dpd <= 30:
        return "1-30"
    if dpd <= 60:
        return "31-60"
    if dpd <= 90:
        return "61-90"
    return "90+"


def month_end(d: date) -> date:
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return month_end(date(d.year + y, m + 1, 1))


@dataclass
class Portfolio:
    accounts: pd.DataFrame
    statements: pd.DataFrame
    payments: pd.DataFrame
    promises: pd.DataFrame
    as_of: date

    def tables(self) -> dict[str, pd.DataFrame]:
        return {
            "accounts": self.accounts,
            "statements": self.statements,
            "payments": self.payments,
            "promises": self.promises,
        }


def generate_portfolio(
    n_accounts: int = 400, months: int = 12, seed: int = 2026, as_of: date = date(2026, 9, 30)
) -> Portfolio:
    rng = np.random.default_rng(seed)
    as_of = month_end(as_of)
    window_start = add_months(as_of, -(months - 1))
    seg_names = list(SEGMENTS)
    seg_p = [SEGMENTS[s][0] for s in seg_names]
    states = list(STATES)

    accounts, statements, payments, promises = [], [], [], []
    for i in range(1, n_accounts + 1):
        acc_id = f"A{i:04d}"
        segment = str(rng.choice(seg_names, p=seg_p))
        lo, hi = SEGMENTS[segment][1]
        line = float(round(rng.uniform(lo, hi), -3))
        risk = float(np.clip(rng.beta(2, 9) + SEGMENTS[segment][2], 0.01, 0.9))
        mob_at_start = int(rng.integers(0, 13))  # months on book at window start
        orig = add_months(window_start, -mob_at_start)
        state = str(rng.choice(states))
        accounts.append(
            {
                "account_id": acc_id,
                "company_name": f"PyME Demo {i:04d} SA de CV",
                "contact_first_name": str(rng.choice(FIRST_NAMES)),
                "segment": segment,
                "industry": str(rng.choice(INDUSTRIES)),
                "state": state,
                "timezone": STATES[state],
                "credit_line": line,
                "origination_date": orig,
                "cohort": f"{orig.year}-Q{(orig.month - 1) // 3 + 1}",
            }
        )

        util = float(rng.uniform(0.15, 0.6))
        dpd, past_due, balance = 0, 0.0, 0.0
        distressed, charged_off, open_ptp = False, False, None
        total_months = mob_at_start + months
        for k in range(total_months):
            stmt_month = add_months(orig, k)
            keep = stmt_month >= window_start

            # Resolve last month's promise against this month's payment (below).
            ptp_boost = 0.2 if open_ptp is not None else 0.0

            if not charged_off and dpd <= 90:
                if not distressed and rng.random() < risk * 0.22:
                    distressed = True
                    util += rng.uniform(0.12, 0.3)  # spend spike precedes missed payments
                elif distressed and rng.random() < 0.3:
                    distressed = False
                util = float(np.clip(util + rng.normal(0, 0.05), 0.02, 1.0))
                balance = round(util * line, 2)

            due_now = round(max(0.06 * balance, 500.0), 2) if balance > 0 else 0.0
            amount_due = round(due_now + past_due, 2) if not charged_off else 0.0

            if charged_off:
                paid = round(balance * rng.uniform(0.05, 0.25), 2) if rng.random() < 0.15 else 0
                balance = round(balance - paid, 2)
            else:
                late = 0.15 * (dpd // 30) + (0.3 if dpd > 90 else 0)
                p_pay = 0.97 - 0.5 * risk - (0.45 if distressed else 0) - late
                p_pay = float(np.clip(p_pay + ptp_boost, 0.02, 0.99))
                u = rng.random()
                if u < p_pay:
                    paid = amount_due
                elif u < p_pay + 0.55 * (1 - p_pay):
                    paid = round(amount_due * rng.uniform(0.15, 0.85), 2)
                else:
                    paid = 0.0

                if amount_due == 0 or paid >= amount_due:
                    dpd, past_due = 0, 0.0
                elif paid >= 0.5 * amount_due and dpd > 0:
                    past_due = round(amount_due - paid, 2)  # holds the bucket, no roll
                else:
                    past_due = round(amount_due - paid, 2)
                    dpd = dpd + 30 if dpd > 0 else int(rng.integers(10, 21))
                if dpd > 90:
                    util = balance / line  # line frozen once 90+
                if dpd >= 180:
                    charged_off = True

            if open_ptp is not None:
                open_ptp["paid_amount_next"] = paid
                kept = paid >= 0.95 * open_ptp["promised_amount"]
                open_ptp["outcome"] = "kept" if kept else "broken"
                if open_ptp["keep"]:
                    promises.append(open_ptp)
                open_ptp = None

            if keep:
                statements.append(
                    {
                        "account_id": acc_id,
                        "statement_month": stmt_month,
                        "months_on_book": k + 1,
                        "credit_line": line,
                        "balance": balance,
                        "utilization": round(balance / line, 4),
                        "amount_due": amount_due,
                        "paid_amount": float(paid),
                        "past_due_amount": past_due if not charged_off else balance,
                        "dpd": dpd,
                        "dpd_bucket": dpd_bucket(dpd),
                        "status": "charged_off" if charged_off else "active",
                    }
                )
                if paid > 0:
                    payments.append(
                        {
                            "account_id": acc_id,
                            "paid_at": stmt_month - timedelta(days=int(rng.integers(0, 20))),
                            "amount": float(paid),
                            "is_recovery": charged_off or dpd > 90,
                        }
                    )

            if dpd > 0 and not charged_off and rng.random() < 0.45:
                open_ptp = {
                    "account_id": acc_id,
                    "created_at": stmt_month,
                    "promised_date": stmt_month + timedelta(days=int(rng.integers(5, 21))),
                    "promised_amount": round(past_due if past_due else amount_due, 2),
                    "dpd_at_promise": dpd,
                    "keep": keep,
                }
        if open_ptp is not None and open_ptp["keep"]:
            open_ptp.update(outcome="pending", paid_amount_next=None)
            promises.append(open_ptp)

    promises_df = pd.DataFrame(promises).drop(columns="keep")
    promises_df.insert(0, "promise_id", [f"PTP{i:05d}" for i in range(1, len(promises_df) + 1)])
    st_df = pd.DataFrame(statements)
    st_df["statement_month"] = pd.to_datetime(st_df["statement_month"])
    acc_df = pd.DataFrame(accounts)
    acc_df["origination_date"] = pd.to_datetime(acc_df["origination_date"])
    pay_df = pd.DataFrame(payments)
    pay_df["paid_at"] = pd.to_datetime(pay_df["paid_at"])
    promises_df["created_at"] = pd.to_datetime(promises_df["created_at"])
    promises_df["promised_date"] = pd.to_datetime(promises_df["promised_date"])
    return Portfolio(acc_df, st_df, pay_df, promises_df, as_of)
