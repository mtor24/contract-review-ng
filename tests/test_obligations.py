from datetime import date, timedelta

import pytest

from core import obligations
from core.ingest import clean_text
from core.segment import segment


def _load(samples_dir, name):
    text = (samples_dir / name).read_text(encoding="utf-8")
    return text, segment(text)


def test_loan_anchor_dates(samples_dir):
    text, _ = _load(samples_dir, "loan_agreement.txt")
    anchors = obligations.find_anchor_dates(text)
    assert anchors["drawdown date"] == date(2026, 11, 15)
    assert anchors["date of this agreement"] == date(2026, 11, 2)


def test_loan_first_instalment_due(samples_dir):
    text, clauses = _load(samples_dir, "loan_agreement.txt")
    obs = obligations.extract(text, clauses)
    first = [o for o in obs if "first instalment" in o["excerpt"]]
    assert first, "expected an obligation mentioning the first instalment"
    assert first[0]["due_date"] == date(2026, 12, 15)
    assert "within 30 days of the Drawdown Date" in first[0]["period_text"]


def test_employment_commencement(samples_dir):
    text, _ = _load(samples_dir, "employment_agreement.txt")
    anchors = obligations.find_anchor_dates(text)
    assert anchors["commencement date"] == date(2026, 12, 1)


def test_employment_motor_vehicle(samples_dir):
    text, clauses = _load(samples_dir, "employment_agreement.txt")
    obs = obligations.extract(text, clauses)
    vehicle = [o for o in obs if "motor vehicle" in o["excerpt"]]
    assert vehicle, "expected a motor vehicle obligation"
    assert vehicle[0]["due_date"] == date(2026, 12, 31)
    assert vehicle[0]["party"] == "Employer"


def test_lease_key_dates(samples_dir):
    text, _ = _load(samples_dir, "lease_agreement.txt")
    keys = obligations.key_dates(text)
    assert keys["effective_date"] == date(2026, 10, 1)
    assert keys["expiry_date"] == date(2029, 9, 30)


def test_sla_key_dates(samples_dir):
    text, _ = _load(samples_dir, "service_level_agreement.txt")
    keys = obligations.key_dates(text)
    assert keys["effective_date"] == date(2026, 11, 1)
    assert keys["expiry_date"] == date(2028, 11, 1)


def test_supply_key_dates(samples_dir):
    text, _ = _load(samples_dir, "supply_agreement.txt")
    keys = obligations.key_dates(text)
    assert keys["expiry_date"] == date(2027, 11, 1)


def test_add_months_clamps_to_month_end():
    assert obligations.add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)


def test_business_days_skip_weekend():
    anchors = {"effective date": date(2026, 3, 6)}  # a Friday
    sentence = "The Provider shall deliver the report within 5 business days of the Effective Date."
    period_text, anchor, due = obligations._deadline(sentence, anchors)
    assert due == date(2026, 3, 13)  # the following Friday


SAMPLES = [
    "employment_agreement.txt",
    "lease_agreement.txt",
    "loan_agreement.txt",
    "nda.txt",
    "partnership_agreement.txt",
    "service_level_agreement.txt",
    "supply_agreement.txt",
]


@pytest.mark.parametrize("name", SAMPLES)
def test_every_sample_yields_obligations(samples_dir, name):
    text, clauses = _load(samples_dir, name)
    obs = obligations.extract(text, clauses)
    assert len(obs) >= 5, f"{name} yielded only {len(obs)} obligations"
    for o in obs:
        assert text[o["char_start"] : o["char_end"]] == o["excerpt"]
        assert "shall mean" not in o["excerpt"].lower()


def test_upcoming_filters_by_window():
    obs = [
        {"due_date": date(2026, 3, 10), "excerpt": "a"},
        {"due_date": date(2026, 3, 5), "excerpt": "b"},
        {"due_date": date(2026, 4, 1), "excerpt": "c"},
        {"due_date": None, "excerpt": "d"},
    ]
    result = obligations.upcoming(obs, date(2026, 3, 1), days=30)
    assert [o["excerpt"] for o in result] == ["b", "a"]


def test_upcoming_inclusive_boundaries():
    today = date(2026, 3, 1)
    obs = [
        {"due_date": today, "excerpt": "today"},
        {"due_date": today + timedelta(days=7), "excerpt": "edge"},
        {"due_date": today + timedelta(days=8), "excerpt": "outside"},
    ]
    result = obligations.upcoming(obs, today, days=7)
    assert [o["excerpt"] for o in result] == ["today", "edge"]


def test_party_roles_employment(samples_dir):
    text, _ = _load(samples_dir, "employment_agreement.txt")
    roles = obligations.party_roles(text)
    assert "Employer" in roles
    assert "Employee" in roles


def test_party_roles_loan(samples_dir):
    text, _ = _load(samples_dir, "loan_agreement.txt")
    roles = obligations.party_roles(text)
    assert "Lender" in roles
    assert "Borrower" in roles


BAD_PARTIES = {"Agreement", "This Agreement", "Loan", "Termination"}


@pytest.mark.parametrize("name", SAMPLES)
def test_no_bogus_parties(samples_dir, name):
    text, clauses = _load(samples_dir, name)
    obs = obligations.extract(text, clauses)
    for o in obs:
        assert o["party"] not in BAD_PARTIES, f"{name}: {o['party']} in {o['excerpt'][:60]}"


def test_nda_drops_non_duty_sentences(samples_dir):
    text, clauses = _load(samples_dir, "nda.txt")
    obs = obligations.extract(text, clauses)
    for o in obs:
        assert not o["excerpt"].startswith("5.1 This Agreement shall come into force")


def test_loan_default_interest_party(samples_dir):
    text, clauses = _load(samples_dir, "loan_agreement.txt")
    obs = obligations.extract(text, clauses)
    match = [o for o in obs if o["excerpt"].startswith("4.1 If the Borrower fails")]
    if match:
        assert match[0]["party"] == "Borrower"


def test_lease_first_rent_execution_alias(samples_dir):
    text, clauses = _load(samples_dir, "lease_agreement.txt")
    obs = obligations.extract(text, clauses)
    rent = [o for o in obs if "first year's rent" in o["excerpt"]]
    assert rent, "expected a first year's rent obligation"
    assert rent[0]["due_date"] == date(2026, 9, 19)


def test_effective_date_of_termination_is_not_the_effective_date(samples_dir):
    # Regression: the anchor "effective date of termination" used to resolve to the
    # contract's effective date by substring match, inventing a deadline.
    text = clean_text((samples_dir / "lease_agreement.txt").read_text(encoding="utf-8"))
    obs = obligations.extract(text, segment(text))
    for o in obs:
        if "effective date of termination" in o["excerpt"]:
            assert o["due_date"] is None


# ---------------------------------------------------------------------------
# Defined dates and roles written as (the "X")
# ---------------------------------------------------------------------------


def test_defined_date_uses_date_nearest_the_definition():
    text = (
        'The Loan shall be disbursed on 1 March 2026 and repaid in full on '
        '1 March 2027 (the "Maturity Date").'
    )
    anchors = obligations.find_anchor_dates(text)
    assert anchors["maturity date"] == date(2027, 3, 1)


def test_defined_date_quotes_inside_brackets_after_the():
    text = 'The Loan shall be repaid on 30 June 2027 (the "Maturity Date").'
    assert obligations.find_anchor_dates(text)["maturity date"] == date(2027, 6, 30)


def test_defined_date_hereinafter_form_still_found():
    text = 'Drawn on 15 November 2026 (hereinafter referred to as "the Drawdown Date").'
    assert obligations.find_anchor_dates(text)["drawdown date"] == date(2026, 11, 15)


def test_party_roles_the_outside_quotes():
    text = (
        "LOAN AGREEMENT\n"
        '(1) ACME FINANCE LIMITED, RC Number 123 (the "Lender"); and\n'
        '(2) BETA TRADING LIMITED, RC Number 456 (the "Borrower").\n'
    )
    roles = obligations.party_roles(text)
    assert "Lender" in roles
    assert "Borrower" in roles


def test_party_roles_the_inside_quotes():
    text = (
        "LOAN AGREEMENT\n"
        '(1) ACME FINANCE LIMITED, RC Number 123 ("the Lender"); and\n'
        '(2) BETA TRADING LIMITED, RC Number 456 (hereinafter referred to as "the Borrower").\n'
    )
    roles = obligations.party_roles(text)
    assert "Lender" in roles
    assert "Borrower" in roles


def test_two_year_term_expiry_is_the_anniversary():
    # Convention kept on purpose: the expiry is the anniversary, not the day before.
    text = (
        "This Agreement shall commence on 1 March 2026 and shall continue for an "
        "initial term of two (2) years."
    )
    assert obligations.key_dates(text)["expiry_date"] == date(2028, 3, 1)
