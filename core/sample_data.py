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
    df = pd.DataFrame(rows)
    # RFC derived from the supplier number with its own RNG, so the columns above are
    # unchanged by adding it.
    df["beneficiary_rfc"] = df["beneficiary"].map(supplier_rfc)
    return df


def synthetic_rfc(rng: random.Random, prefix: str = "PDE") -> str:
    """Persona-moral-shaped RFC: 3 letters + YYMMDD + 3-character homoclave. Fake."""
    alnum = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
    date = f"{rng.randint(5, 20):02d}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"
    return prefix + date + "".join(rng.choice(alnum) for _ in range(3))


def supplier_rfc(beneficiary: str) -> str:
    return synthetic_rfc(random.Random(f"rfc|{beneficiary}"))


def generate_bank_registry(
    payments: pd.DataFrame,
    seed: int = 7,
    p_nonexistent: float = 0.03,
    p_blocked: float = 0.015,
    p_cancelled: float = 0.015,
    p_wrong_owner: float = 0.03,
) -> pd.DataFrame:
    """What the receiving banks know about each CLABE in a payment file (synthetic).

    Most accounts belong to the supplier on the invoice. A few do not exist, are blocked
    or cancelled, or belong to a different RFC (the "we changed banks" fraud pattern).
    """
    rng = random.Random(seed)
    rows = []
    pairs = payments[["clabe", "beneficiary", "beneficiary_rfc"]].drop_duplicates("clabe")
    for r in pairs.sort_values("clabe").itertuples():
        u = rng.random()
        if u < p_nonexistent:
            continue
        status, owner_name, owner_rfc = "active", r.beneficiary.upper(), r.beneficiary_rfc
        if u < p_nonexistent + p_blocked:
            status = "blocked"
        elif u < p_nonexistent + p_blocked + p_cancelled:
            status = "cancelled"
        elif u < p_nonexistent + p_blocked + p_cancelled + p_wrong_owner:
            owner_name = "TERCERO DEMO SA DE CV"
            owner_rfc = synthetic_rfc(random.Random(f"owner|{r.clabe}"), prefix="TDE")
        rows.append(
            {"clabe": r.clabe, "owner_name": owner_name, "owner_rfc": owner_rfc, "status": status}
        )
    return pd.DataFrame(rows, columns=["clabe", "owner_name", "owner_rfc", "status"])
