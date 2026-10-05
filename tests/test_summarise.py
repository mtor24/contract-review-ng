from datetime import date

import pytest

from core.money import find_amounts, format_kobo, parse_naira
from core.pipeline import analyse


def test_parse_naira_whole():
    assert parse_naira("N18,000,000") == 1_800_000_000


def test_parse_naira_with_kobo():
    assert parse_naira("N1,250.50") == 125_050


def test_parse_naira_ngn_prefix():
    assert parse_naira("NGN 5,000") == 500_000


def test_parse_naira_returns_int():
    assert isinstance(parse_naira("N850,000"), int)


def test_salary_example():
    assert parse_naira("N850,000") == 85_000_000


def test_format_kobo():
    assert format_kobo(1_800_000_000) == "N18,000,000.00"


def test_round_trip():
    assert parse_naira(format_kobo(125_050)) == 125_050


def test_find_amounts_loan_sample(samples_dir):
    text = (samples_dir / "loan_agreement.txt").read_text(encoding="utf-8")
    amounts = find_amounts(text)
    assert any(kobo == 25_000_000_000 for kobo, _, _ in amounts)
    for kobo, start, end in amounts:
        assert isinstance(kobo, int)
        assert text[start:end].startswith(("N", "NGN"))


def test_find_amounts_offsets_point_at_match():
    text = "Fee is N1,250.50 payable."
    [(kobo, start, end)] = find_amounts(text)
    assert kobo == 125_050
    assert text[start:end] == "N1,250.50"


@pytest.fixture
def employment(samples_dir):
    return analyse((samples_dir / "employment_agreement.txt").read_text(encoding="utf-8"))


def test_employment_parties(employment):
    parties = {p["name"]: p["role"] for p in employment["summary"]["parties"]}
    assert parties["ZENITH CREST INDUSTRIES LIMITED"] == "Employer"
    assert parties["MR. CHUKWUEMEKA ADEWALE OKAFOR"] == "Employee"


def test_employment_dates(employment):
    assert employment["summary"]["agreement_date"] == date(2026, 11, 14)
    assert employment["summary"]["effective_date"] == date(2026, 12, 1)


@pytest.fixture
def supply(samples_dir):
    return analyse((samples_dir / "supply_agreement.txt").read_text(encoding="utf-8"))


def test_supply_value(supply):
    assert supply["summary"]["value_kobo"] == 120_000_000 * 100
    assert isinstance(supply["summary"]["value_kobo"], int)


def test_supply_expiry(supply):
    assert supply["summary"]["expiry_date"] == date(2027, 11, 1)


def test_supply_top_risk_is_high(supply):
    assert supply["summary"]["top_risks"][0]["severity"] == "High"


# ---------------------------------------------------------------------------
# Money parsing: naira sign, multipliers, and false prefixes
# ---------------------------------------------------------------------------


def test_parse_naira_sign():
    assert parse_naira("₦18,000,000") == 1_800_000_000


def test_parse_naira_million():
    assert parse_naira("N18 million") == 18_000_000 * 100


def test_parse_naira_decimal_billion():
    assert parse_naira("N2.5 billion") == 2_500_000_000 * 100


def test_parse_naira_ngn_bn():
    kobo = parse_naira("NGN 5 bn")
    assert kobo == 5_000_000_000 * 100
    assert isinstance(kobo, int)


def test_parse_naira_plain_digits():
    assert parse_naira("N500") == 50_000


def test_find_amounts_skips_registration_numbers():
    assert find_amounts("Tax ID TIN12345678 and business name BN 1234567.") == []
    assert find_amounts("Reference BN1234567 issued.") == []


def test_find_amounts_offsets_cover_multiplier():
    text = "A fee of N2.5 billion and ₦500 apply."
    found = find_amounts(text)
    assert [(k, text[s:e]) for k, s, e in found] == [
        (250_000_000_000, "N2.5 billion"),
        (50_000, "₦500"),
    ]


def test_summary_role_with_the_outside_quotes():
    from core.summarise import _ROLE_RE

    m = _ROLE_RE.search('ACME LIMITED, RC Number 123 (the "Lender"); and')
    assert m and m.group(1) == "Lender"
