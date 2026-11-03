"""Bulk payment file parsing and pre-flight validation."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pandas as pd
from pydantic import BaseModel, Field

from core.clabe import validate_clabe
from core.config import load_config

REQUIRED_COLUMNS = ["beneficiary", "clabe", "amount_mxn", "reference", "concept"]

ERROR = "error"
WARNING = "warning"


class PaymentInstruction(BaseModel):
    payment_id: str
    beneficiary: str = Field(min_length=1)
    clabe: str = Field(min_length=18, max_length=18)
    bank_name: str
    amount_mxn: Decimal = Field(gt=0, decimal_places=2)
    reference: str
    concept: str


class PreflightError(ValueError):
    """The file itself is unusable (e.g. missing columns)."""


def read_payments_csv(source) -> pd.DataFrame:
    # Read everything as text: CLABEs and references have meaningful leading zeros.
    df = pd.read_csv(source, dtype=str, keep_default_na=False)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise PreflightError(f"Missing required columns: {', '.join(missing)}")
    df = df[REQUIRED_COLUMNS].copy()
    for col in REQUIRED_COLUMNS:
        df[col] = df[col].astype(str).str.strip()
    return df


def _parse_amount(raw: str) -> Decimal | None:
    try:
        value = Decimal(str(raw).replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def preflight(df: pd.DataFrame, limits: dict | None = None) -> pd.DataFrame:
    """Validate every row and return the frame with `issues`, `severity` and `status` columns.

    status: ready (no issues), warning (sendable, review advised), blocked (will not be sent).
    """
    limits = limits or load_config("billpay")
    out = df.reset_index(drop=True).copy()
    out.insert(0, "row", range(1, len(out) + 1))
    out["payment_id"] = [f"P{i:05d}" for i in out["row"]]

    issues: list[list[tuple[str, str]]] = [[] for _ in range(len(out))]
    bank_names: list[str | None] = []
    amounts: list[float | None] = []
    clabes: list[str] = []

    for i, row in out.iterrows():
        res = validate_clabe(row["clabe"])
        clabes.append(res.clabe)
        bank_names.append(res.bank_name)
        for msg in res.messages:
            issues[i].append((ERROR, f"CLABE: {msg}"))

        amount = _parse_amount(row["amount_mxn"])
        if amount is None:
            issues[i].append((ERROR, "Amount is not a number."))
        elif amount <= 0:
            issues[i].append((ERROR, "Amount must be greater than 0."))
        elif amount.as_tuple().exponent < -2:
            issues[i].append((ERROR, "Amount has more than 2 decimals."))
        elif amount > Decimal(str(limits["max_amount_mxn"])):
            issues[i].append((WARNING, "Amount above the per-transfer approval limit."))
        amounts.append(float(amount) if amount is not None else None)

        ref = row["reference"]
        if not ref:
            issues[i].append((ERROR, "Reference is empty."))
        elif not ref.isdigit():
            issues[i].append((ERROR, "Reference must be numeric."))
        elif len(ref) > limits["reference_max_len"]:
            issues[i].append(
                (ERROR, f"Reference longer than {limits['reference_max_len']} digits.")
            )

        if not row["beneficiary"]:
            issues[i].append((ERROR, "Beneficiary is empty."))
        elif len(row["beneficiary"]) > limits["beneficiary_max_len"]:
            issues[i].append((WARNING, "Beneficiary name will be truncated."))
        if not row["concept"]:
            issues[i].append((WARNING, "Concept is empty."))
        elif len(row["concept"]) > limits["concept_max_len"]:
            issues[i].append(
                (ERROR, f"Concept longer than {limits['concept_max_len']} characters.")
            )

    out["clabe"] = clabes
    out["bank_name"] = bank_names
    out["amount"] = amounts

    # Exact duplicates (same CLABE + amount + reference) block every copy after the first.
    key = out["clabe"] + "|" + out["amount"].astype(str) + "|" + out["reference"]
    for i in out.index[key.duplicated(keep="first")]:
        first = out.loc[key == key[i], "row"].iloc[0]
        issues[i].append((ERROR, f"Duplicate of row {first} (same CLABE, amount, reference)."))
    # Same CLABE + amount with a different reference is a common double-pay pattern.
    soft = out["clabe"] + "|" + out["amount"].astype(str)
    soft_dupes = soft.duplicated(keep=False) & ~key.duplicated(keep=False)
    for i in out.index[soft_dupes]:
        issues[i].append((WARNING, "Same CLABE and amount as another row: possible double pay."))

    out["issues"] = ["; ".join(m for _, m in row) for row in issues]
    out["severity"] = [
        ERROR if any(s == ERROR for s, _ in row) else WARNING if row else "" for row in issues
    ]
    out["status"] = out["severity"].map({ERROR: "blocked", WARNING: "warning"}).fillna("ready")
    return out


def preflight_summary(report: pd.DataFrame) -> dict:
    sendable = report[report["status"] != "blocked"]
    return {
        "rows": len(report),
        "ready": int((report["status"] == "ready").sum()),
        "warning": int((report["status"] == "warning").sum()),
        "blocked": int((report["status"] == "blocked").sum()),
        "sendable_amount_mxn": round(float(sendable["amount"].sum()), 2),
    }


def to_instructions(report: pd.DataFrame) -> list[PaymentInstruction]:
    """Convert sendable pre-flight rows into validated instruction models."""
    sendable = report[report["status"] != "blocked"]
    return [
        PaymentInstruction(
            payment_id=r.payment_id,
            beneficiary=r.beneficiary,
            clabe=r.clabe,
            bank_name=r.bank_name,
            amount_mxn=Decimal(str(r.amount)).quantize(Decimal("0.01")),
            reference=r.reference,
            concept=r.concept,
        )
        for r in sendable.itertuples()
    ]
