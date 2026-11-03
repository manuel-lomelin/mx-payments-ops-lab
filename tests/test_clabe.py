import pytest

from core.clabe import (
    ClabeError,
    build_clabe,
    compute_check_digit,
    is_valid_clabe,
    load_banks,
    normalize,
    validate_clabe,
)

# Example CLABE published in Banxico's CLABE documentation.
BANXICO_EXAMPLE = "002010077777777771"


def test_known_valid_clabe():
    result = validate_clabe(BANXICO_EXAMPLE)
    assert result.valid
    assert result.bank_code == "002"
    assert result.bank_name == "BANAMEX"
    assert result.plaza_code == "010"
    assert result.account_number == "07777777777"
    assert result.check_digit == result.expected_check_digit == 1
    assert result.messages == []


# Worked example from https://es.wikipedia.org/wiki/CLABE
WIKIPEDIA_EXAMPLE = "032180000118359719"


def test_check_digit_formula():
    assert compute_check_digit(BANXICO_EXAMPLE[:17]) == 1
    assert compute_check_digit(WIKIPEDIA_EXAMPLE[:17]) == 9


def test_wikipedia_example_structure():
    result = validate_clabe(WIKIPEDIA_EXAMPLE)
    assert result.plaza_code == "180"
    assert result.account_number == "00011835971"
    assert result.check_digit == 9
    # Bank code 032 is not in the Wikipedia catalog itself, so it is flagged as unknown.
    assert result.errors == (ClabeError.UNKNOWN_BANK,)


def test_check_digit_zero_case():
    # (10 - 0) mod 10 must give 0, not 10.
    assert compute_check_digit("0" * 17) == 0


@pytest.mark.parametrize("bad", ["", "123", "0" * 16, "0" * 18, "A" * 17])
def test_compute_check_digit_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        compute_check_digit(bad)


def test_wrong_check_digit():
    result = validate_clabe(BANXICO_EXAMPLE[:17] + "2")
    assert not result.valid
    assert result.errors == (ClabeError.CHECK_DIGIT,)
    assert result.expected_check_digit == 1


@pytest.mark.parametrize("value", ["00201007777777777", "0020100777777777710", "1", ""])
def test_invalid_lengths(value):
    result = validate_clabe(value)
    assert ClabeError.LENGTH in result.errors
    assert result.bank_code is None


@pytest.mark.parametrize(
    "value", ["00201007777777777A", "002O10077777777771", "²02010077777777771"]
)
def test_non_digits(value):
    result = validate_clabe(value)
    assert result.errors == (ClabeError.NON_DIGIT,)


def test_non_digit_and_wrong_length_reports_both():
    result = validate_clabe("ABC")
    assert set(result.errors) == {ClabeError.NON_DIGIT, ClabeError.LENGTH}


def test_unknown_bank_code_with_valid_check_digit():
    clabe = build_clabe("999", "180", "12345678901")
    result = validate_clabe(clabe)
    assert result.errors == (ClabeError.UNKNOWN_BANK,)
    assert result.bank_name is None


def test_unknown_bank_and_bad_check_digit():
    clabe = build_clabe("999", "180", "12345678901")
    bad = clabe[:17] + str((int(clabe[17]) + 1) % 10)
    assert set(validate_clabe(bad).errors) == {ClabeError.UNKNOWN_BANK, ClabeError.CHECK_DIGIT}


def test_normalizes_spaces_and_hyphens():
    assert normalize(" 002 010-0777 7777 7771 ") == BANXICO_EXAMPLE
    assert is_valid_clabe("002 010 07777777777 1")


def test_custom_bank_catalog():
    assert validate_clabe(BANXICO_EXAMPLE, banks={"002": "TEST BANK"}).bank_name == "TEST BANK"
    assert ClabeError.UNKNOWN_BANK in validate_clabe(BANXICO_EXAMPLE, banks={}).errors


def test_build_clabe_roundtrip_for_every_catalog_bank():
    for code in load_banks():
        clabe = build_clabe(code, "180", "00012345678")
        assert len(clabe) == 18
        assert is_valid_clabe(clabe), code


def test_build_clabe_rejects_bad_parts():
    with pytest.raises(ValueError):
        build_clabe("12", "180", "123456789012")
    with pytest.raises(ValueError):
        build_clabe("AB1", "180", "12345678901")


def test_every_single_digit_error_is_detected():
    # Weights 3/7/1 are coprime with 10, so any one-digit substitution changes the check.
    for pos in range(17):
        for new in "0123456789":
            if new == BANXICO_EXAMPLE[pos]:
                continue
            mutated = BANXICO_EXAMPLE[:pos] + new + BANXICO_EXAMPLE[pos + 1 :]
            assert ClabeError.CHECK_DIGIT in validate_clabe(mutated).errors


def test_bank_catalog_matches_wikipedia_table():
    banks = load_banks()
    assert len(banks) == 99
    assert all(len(code) == 3 and code.isdigit() for code in banks)
    assert "999" not in banks  # the N/A placeholder row is excluded
    spot_checks = {
        "002": "BANAMEX",
        "012": "BBVA MÉXICO",
        "030": "BAJÍO",
        "137": "BANCOPPEL",
        "167": "HEY BANCO",
        "646": "STP",
        "722": "MERCADO PAGO W",
        "902": "INDEVAL",
    }
    assert {code: banks[code] for code in spot_checks} == spot_checks


def test_catalog_is_read_as_utf8():
    assert load_banks()["605"] == "VALUÉ"
