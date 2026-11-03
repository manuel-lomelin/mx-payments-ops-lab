"""CLABE (Clave Bancaria Estandarizada) validation.

Layout of the 18 digits: 3 bank + 3 plaza + 11 account + 1 check digit.
Check digit: weights 3, 7, 1 repeated over the first 17 digits; sum (digit * weight) mod 10
for each position, then check = (10 - (sum mod 10)) mod 10.

The bank catalog in data/banks.csv is the "clave del banco" table from the Spanish
Wikipedia article on CLABE (https://es.wikipedia.org/wiki/CLABE), short names as listed
there, excluding the "999 N/A" placeholder. Wikipedia lags real changes in SPEI
participants, so verify against Banxico's participant catalog before production use.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

CLABE_LENGTH = 18
WEIGHTS = (3, 7, 1)
BANKS_CSV = Path(__file__).resolve().parent.parent / "data" / "banks.csv"


class ClabeError(StrEnum):
    LENGTH = "length"
    NON_DIGIT = "non_digit"
    CHECK_DIGIT = "check_digit"
    UNKNOWN_BANK = "unknown_bank"


ERROR_MESSAGES = {
    ClabeError.LENGTH: "CLABE must have exactly 18 digits.",
    ClabeError.NON_DIGIT: "CLABE must contain digits only.",
    ClabeError.CHECK_DIGIT: "Check digit does not match.",
    ClabeError.UNKNOWN_BANK: "Bank code not found in the catalog.",
}


@dataclass(frozen=True)
class ClabeResult:
    clabe: str
    errors: tuple[ClabeError, ...]
    bank_code: str | None = None
    bank_name: str | None = None
    plaza_code: str | None = None
    account_number: str | None = None
    check_digit: int | None = None
    expected_check_digit: int | None = None

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def messages(self) -> list[str]:
        return [ERROR_MESSAGES[e] for e in self.errors]


@lru_cache(maxsize=4)
def load_banks(path: Path = BANKS_CSV) -> dict[str, str]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return {row["code"].zfill(3): row["name"] for row in csv.DictReader(fh)}


def normalize(value: str) -> str:
    """Strip whitespace and hyphens, which are common when CLABEs are copy-pasted."""
    return "".join(ch for ch in str(value) if not ch.isspace() and ch != "-")


def compute_check_digit(first17: str) -> int:
    if len(first17) != CLABE_LENGTH - 1 or not first17.isdigit():
        raise ValueError("compute_check_digit expects exactly 17 digits")
    total = sum((int(d) * WEIGHTS[i % 3]) % 10 for i, d in enumerate(first17))
    return (10 - (total % 10)) % 10


def validate_clabe(value: str, banks: dict[str, str] | None = None) -> ClabeResult:
    banks = load_banks() if banks is None else banks
    clabe = normalize(value)

    # isdecimal + isascii rejects things like superscripts and non-ASCII digits.
    if not (clabe.isascii() and clabe.isdecimal()):
        errors = [ClabeError.NON_DIGIT]
        if len(clabe) != CLABE_LENGTH:
            errors.append(ClabeError.LENGTH)
        return ClabeResult(clabe=clabe, errors=tuple(errors))
    if len(clabe) != CLABE_LENGTH:
        return ClabeResult(clabe=clabe, errors=(ClabeError.LENGTH,))

    errors: list[ClabeError] = []
    bank_code = clabe[:3]
    bank_name = banks.get(bank_code)
    if bank_name is None:
        errors.append(ClabeError.UNKNOWN_BANK)
    expected = compute_check_digit(clabe[:17])
    actual = int(clabe[17])
    if expected != actual:
        errors.append(ClabeError.CHECK_DIGIT)

    return ClabeResult(
        clabe=clabe,
        errors=tuple(errors),
        bank_code=bank_code,
        bank_name=bank_name,
        plaza_code=clabe[3:6],
        account_number=clabe[6:17],
        check_digit=actual,
        expected_check_digit=expected,
    )


def is_valid_clabe(value: str) -> bool:
    return validate_clabe(value).valid


def build_clabe(bank_code: str, plaza_code: str, account_number: str) -> str:
    """Build a valid CLABE from its parts. Used to generate synthetic test data."""
    first17 = f"{bank_code:0>3}{plaza_code:0>3}{account_number:0>11}"
    if len(first17) != 17 or not first17.isdigit():
        raise ValueError("bank(3) + plaza(3) + account(11) must be 17 digits")
    return first17 + str(compute_check_digit(first17))
