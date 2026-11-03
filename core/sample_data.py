"""Synthetic sample data. No real people, companies or accounts."""

from __future__ import annotations

import random

import pandas as pd

from core.clabe import build_clabe

# Banks the synthetic suppliers bank with. Pinned (not the whole catalog) so the seeded
# sample file stays stable when the catalog changes.
SAMPLE_BANK_CODES = [
    "002",
    "006",
    "009",
    "012",
    "014",
    "019",
    "021",
    "030",
    "036",
    "042",
    "044",
    "058",
    "059",
    "060",
    "062",
    "072",
    "106",
    "127",
    "130",
    "137",
    "166",
    "646",
]

CONCEPTS = [
    "Pago factura",
    "Servicios de limpieza",
    "Renta oficina",
    "Insumos de papeleria",
    "Mantenimiento equipo",
    "Fletes y envios",
    "Honorarios consultoria",
    "Material de empaque",
]


def generate_payment_batch(n: int = 120, seed: int = 42, error_rate: float = 0.08) -> pd.DataFrame:
    """Generate a supplier payment file. About `error_rate` of rows get a deliberate defect."""
    rng = random.Random(seed)
    banks = SAMPLE_BANK_CODES
    rows = []
    for _ in range(n):
        plaza, account = f"{rng.randint(1, 999):03d}", f"{rng.randint(0, 10**11 - 1):011d}"
        clabe = build_clabe(rng.choice(banks), plaza, account)
        rows.append(
            {
                "beneficiary": f"Proveedor Demo {rng.randint(1, 60):03d} SA de CV",
                "clabe": clabe,
                "amount_mxn": f"{rng.lognormvariate(9.5, 1.0):.2f}",
                "reference": str(rng.randint(1, 9_999_999)),
                "concept": f"{rng.choice(CONCEPTS)} {rng.randint(100, 999)}",
            }
        )

    defects = ["bad_check", "short_clabe", "negative", "long_ref", "duplicate", "letters"]
    for idx in rng.sample(range(n), k=max(1, int(n * error_rate))):
        kind = rng.choice(defects)
        row = rows[idx]
        if kind == "bad_check":
            row["clabe"] = row["clabe"][:17] + str((int(row["clabe"][17]) + 3) % 10)
        elif kind == "short_clabe":
            row["clabe"] = row["clabe"][:16]
        elif kind == "negative":
            row["amount_mxn"] = f"-{row['amount_mxn']}"
        elif kind == "long_ref":
            row["reference"] = "1234567890"
        elif kind == "letters":
            row["clabe"] = row["clabe"][:10] + "ABCD" + row["clabe"][14:]
        elif kind == "duplicate" and idx > 0:
            rows[idx] = dict(rows[idx - 1])
    return pd.DataFrame(rows)
