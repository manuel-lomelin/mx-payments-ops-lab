"""Reconciliation of sent payments against a (mock) bank statement.

Matching order:
1. Reversal pairs: a returned transfer shows up as a debit plus a DEVOLUCION credit.
2. Exact: same reference and same amount.
3. Fuzzy: amount within tolerance, value date within N days, and a combined
   reference/name similarity above a threshold. Greedy, best score first, one-to-one.
Anything left over is surfaced as unmatched, both ways.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import timedelta
from difflib import SequenceMatcher

import pandas as pd


@dataclass
class StatementNoise:
    reformat_reference: float = 0.06  # bank prints "REF 0001234" instead of "1234"
    amount_drift: float = 0.02  # small amount difference (FX / fee netting)
    missing: float = 0.03  # not yet posted by the bank
    returned_pairs: bool = True  # debit + DEVOLUCION credit for returned attempts
    bank_fees: int = 3  # unrelated COMISION lines
    unknown_debits: int = 2  # debits nobody can explain


def generate_bank_statement(
    payments: pd.DataFrame,
    attempts: pd.DataFrame | None = None,
    noise: StatementNoise | None = None,
    seed: int = 21,
) -> pd.DataFrame:
    """Build a mock bank statement from a simulated run. Amounts: debits negative."""
    noise = noise or StatementNoise()
    rng = random.Random(seed)
    lines: list[dict] = []

    for p in payments[payments["final_status"] == "settled"].itertuples():
        if rng.random() < noise.missing:
            continue
        ref, amount = p.reference, -p.amount_mxn
        if rng.random() < noise.reformat_reference:
            ref = f"REF {p.reference.zfill(7)}"
        if rng.random() < noise.amount_drift:
            amount = round(amount + rng.choice([-1, 1]) * rng.uniform(0.01, 0.99), 2)
        lines.append(
            {
                "value_date": p.settled_at.date(),
                "description": f"SPEI ENVIADO {p.beneficiary[:24].upper()}",
                "reference": ref,
                "amount": amount,
            }
        )

    if noise.returned_pairs and attempts is not None and not attempts.empty:
        by_id = payments.set_index("payment_id")
        for a in attempts[attempts["status"] == "returned"].itertuples():
            p = by_id.loc[a.payment_id]
            for sign, desc in ((-1, "SPEI ENVIADO"), (1, "DEVOLUCION SPEI")):
                lines.append(
                    {
                        "value_date": a.resolved_at.date(),
                        "description": f"{desc} {p.beneficiary[:24].upper()}",
                        "reference": p.reference,
                        "amount": sign * p.amount_mxn,
                    }
                )

    base_date = payments["first_sent_at"].min().date() if len(payments) else None
    for _ in range(noise.bank_fees):
        lines.append(
            {
                "value_date": base_date,
                "description": "COMISION SPEI",
                "reference": "",
                "amount": -round(rng.uniform(3, 8), 2),
            }
        )
    for _ in range(noise.unknown_debits):
        lines.append(
            {
                "value_date": base_date,
                "description": "CARGO DOMICILIADO",
                "reference": str(rng.randint(10**6, 10**7 - 1)),
                "amount": -round(rng.lognormvariate(8, 1), 2),
            }
        )

    rng.shuffle(lines)
    stmt = pd.DataFrame(lines, columns=["value_date", "description", "reference", "amount"])
    stmt.insert(0, "line_id", [f"L{i:05d}" for i in range(1, len(stmt) + 1)])
    return stmt


def normalize_reference(ref: str) -> str:
    digits = re.sub(r"\D", "", str(ref or ""))
    return digits.lstrip("0")


def _normalize_name(text: str) -> str:
    text = re.sub(r"^(SPEI ENVIADO|DEVOLUCION SPEI)\s+", "", str(text).upper())
    return re.sub(r"[^A-Z0-9 ]", "", text).strip()


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class ReconResult:
    matches: pd.DataFrame
    unmatched_payments: pd.DataFrame
    unmatched_lines: pd.DataFrame
    reversals: pd.DataFrame
    summary: dict = field(default_factory=dict)


def reconcile(
    payments: pd.DataFrame,
    statement: pd.DataFrame,
    amount_tolerance: float = 1.00,
    date_window_days: int = 1,
    fuzzy_threshold: float = 0.80,
) -> ReconResult:
    expected = payments[payments["final_status"] == "settled"].copy()
    stmt = statement.copy()
    stmt["norm_ref"] = stmt["reference"].map(normalize_reference)
    stmt["norm_name"] = stmt["description"].map(_normalize_name)
    used_lines: set[str] = set()

    # 1. Reversal pairs (debit + DEVOLUCION credit with same reference and amount).
    reversals = []
    credits = stmt[stmt["description"].str.startswith("DEVOLUCION")]
    for c in credits.itertuples():
        debit = stmt[
            (stmt["amount"] == -c.amount)
            & (stmt["norm_ref"] == c.norm_ref)
            & ~stmt["line_id"].isin(used_lines | {c.line_id})
            & (stmt["amount"] < 0)
        ]
        if not debit.empty:
            # Prefer the debit printed exactly like the credit: that is the returned send,
            # not a later successful retry of the same payment.
            same_print = debit[debit["reference"] == c.reference]
            d = (same_print if not same_print.empty else debit).iloc[0]
            used_lines |= {c.line_id, d["line_id"]}
            reversals.append(
                {
                    "debit_line": d["line_id"],
                    "credit_line": c.line_id,
                    "reference": c.reference,
                    "amount": c.amount,
                }
            )

    matches: list[dict] = []
    matched_payments: set[str] = set()

    # 2. Exact: reference + amount.
    open_lines = stmt[~stmt["line_id"].isin(used_lines)]
    exact_index: dict[tuple[str, float], list[str]] = {}
    for line in open_lines.itertuples():
        exact_index.setdefault((str(line.reference), round(-line.amount, 2)), []).append(
            line.line_id
        )
    for p in expected.itertuples():
        candidates = exact_index.get((p.reference, round(p.amount_mxn, 2)), [])
        candidates = [lid for lid in candidates if lid not in used_lines]
        if candidates:
            used_lines.add(candidates[0])
            matched_payments.add(p.payment_id)
            matches.append(
                {
                    "payment_id": p.payment_id,
                    "line_id": candidates[0],
                    "match_type": "exact",
                    "score": 1.0,
                    "amount_diff": 0.0,
                }
            )

    # 3. Fuzzy.
    open_lines = stmt[~stmt["line_id"].isin(used_lines) & (stmt["amount"] < 0)]
    window = timedelta(days=date_window_days)
    scored = []
    for p in expected[~expected["payment_id"].isin(matched_payments)].itertuples():
        p_ref = normalize_reference(p.reference)
        p_name = _normalize_name(p.beneficiary)
        p_date = p.settled_at.date()
        for line in open_lines.itertuples():
            diff = round(-line.amount - p.amount_mxn, 2)
            if abs(diff) > amount_tolerance:
                continue
            if line.value_date is None or abs(line.value_date - p_date) > window:
                continue
            ref_score = similarity(p_ref, line.norm_ref)
            name_score = similarity(p_name[:24], line.norm_name)
            score = 0.6 * ref_score + 0.4 * name_score
            if score >= fuzzy_threshold:
                scored.append((score, p.payment_id, line.line_id, diff))
    for score, pid, lid, diff in sorted(scored, reverse=True):
        if pid in matched_payments or lid in used_lines:
            continue
        matched_payments.add(pid)
        used_lines.add(lid)
        matches.append(
            {
                "payment_id": pid,
                "line_id": lid,
                "match_type": "fuzzy",
                "score": round(score, 3),
                "amount_diff": diff,
            }
        )

    matches_df = pd.DataFrame(
        matches, columns=["payment_id", "line_id", "match_type", "score", "amount_diff"]
    )
    unmatched_payments = expected[~expected["payment_id"].isin(matched_payments)]
    unmatched_lines = statement[~statement["line_id"].isin(used_lines)]
    reversals_df = pd.DataFrame(
        reversals, columns=["debit_line", "credit_line", "reference", "amount"]
    )

    with_diff = int((matches_df["amount_diff"] != 0).sum()) if len(matches_df) else 0
    base = len(expected) + len(statement) - 2 * len(reversals_df)
    exceptions = len(unmatched_payments) + len(unmatched_lines) + with_diff
    summary = {
        "expected_payments": len(expected),
        "statement_lines": len(statement),
        "exact": int((matches_df["match_type"] == "exact").sum()),
        "fuzzy": int((matches_df["match_type"] == "fuzzy").sum()),
        "reversal_pairs": len(reversals_df),
        "matched_with_amount_diff": with_diff,
        "unmatched_payments": len(unmatched_payments),
        "unmatched_lines": len(unmatched_lines),
        "recon_error_rate": exceptions / base if base else 0.0,
    }
    return ReconResult(matches_df, unmatched_payments, unmatched_lines, reversals_df, summary)
