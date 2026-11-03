import io

import pandas as pd
import pytest

from core.clabe import build_clabe
from core.payments import (
    PreflightError,
    preflight,
    preflight_summary,
    read_payments_csv,
    to_instructions,
)
from core.sample_data import generate_payment_batch

GOOD = build_clabe("012", "180", "00012345678")
OTHER = build_clabe("072", "180", "00087654321")


def frame(rows):
    base = {
        "beneficiary": "Proveedor Demo 001",
        "clabe": GOOD,
        "amount_mxn": "100.00",
        "reference": "1234567",
        "concept": "Pago factura 1",
    }
    return pd.DataFrame([{**base, **r} for r in rows])


def issues_of(rows):
    return preflight(frame(rows))


def test_clean_row_is_ready():
    report = issues_of([{}])
    assert report.loc[0, "status"] == "ready"
    assert report.loc[0, "bank_name"] == "BBVA MÉXICO"
    assert report.loc[0, "payment_id"] == "P00001"


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"clabe": GOOD[:17] + str((int(GOOD[17]) + 1) % 10)}, "Check digit"),
        ({"clabe": "123"}, "exactly 18 digits"),
        ({"amount_mxn": "0"}, "greater than 0"),
        ({"amount_mxn": "-5"}, "greater than 0"),
        ({"amount_mxn": "abc"}, "not a number"),
        ({"amount_mxn": "1.234"}, "more than 2 decimals"),
        ({"reference": ""}, "Reference is empty"),
        ({"reference": "12A"}, "numeric"),
        ({"reference": "12345678"}, "longer than 7"),
        ({"beneficiary": ""}, "Beneficiary is empty"),
        ({"concept": "x" * 41}, "Concept longer"),
    ],
)
def test_blocking_errors(override, fragment):
    report = issues_of([override])
    assert report.loc[0, "status"] == "blocked"
    assert fragment in report.loc[0, "issues"]


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"amount_mxn": "9000000"}, "approval limit"),
        ({"beneficiary": "B" * 41}, "truncated"),
        ({"concept": ""}, "Concept is empty"),
    ],
)
def test_warnings_are_sendable(override, fragment):
    report = issues_of([override])
    assert report.loc[0, "status"] == "warning"
    assert fragment in report.loc[0, "issues"]


def test_exact_duplicate_blocks_second_copy_only():
    report = issues_of([{}, {}, {"clabe": OTHER}])
    assert list(report["status"]) == ["ready", "blocked", "ready"]
    assert "Duplicate of row 1" in report.loc[1, "issues"]


def test_same_clabe_amount_different_reference_warns():
    report = issues_of([{"reference": "1"}, {"reference": "2"}])
    assert list(report["status"]) == ["warning", "warning"]
    assert "double pay" in report.loc[0, "issues"]


def test_amount_accepts_thousand_separators_and_symbol():
    assert issues_of([{"amount_mxn": "$1,250.50"}]).loc[0, "amount"] == 1250.50


def test_summary_and_instructions():
    report = issues_of([{}, {"amount_mxn": "0"}, {"clabe": OTHER, "concept": ""}])
    summary = preflight_summary(report)
    assert summary == {
        "rows": 3,
        "ready": 1,
        "warning": 1,
        "blocked": 1,
        "sendable_amount_mxn": 200.0,
    }
    instructions = to_instructions(report)
    assert [i.payment_id for i in instructions] == ["P00001", "P00003"]
    assert str(instructions[0].amount_mxn) == "100.00"


def test_read_csv_keeps_leading_zeros_and_normalizes_headers():
    csv = f" Beneficiary ,CLABE,amount_mxn,reference,concept,extra\nA,{GOOD},10,0012,x,y\n"
    df = read_payments_csv(io.StringIO(csv))
    assert list(df.columns) == ["beneficiary", "clabe", "amount_mxn", "reference", "concept"]
    assert df.loc[0, "clabe"] == GOOD
    assert df.loc[0, "reference"] == "0012"


def test_read_csv_missing_columns():
    with pytest.raises(PreflightError, match="amount_mxn"):
        read_payments_csv(io.StringIO("beneficiary,clabe,reference,concept\n"))


def test_sample_batch_is_seeded_and_has_defects():
    a = generate_payment_batch(n=80, seed=1)
    b = generate_payment_batch(n=80, seed=1)
    pd.testing.assert_frame_equal(a, b)
    summary = preflight_summary(preflight(a))
    assert summary["blocked"] >= 1
    assert summary["ready"] > summary["blocked"]
