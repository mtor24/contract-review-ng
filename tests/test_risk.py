"""Tests for core/risk.py and core/textutil.py."""

import pytest
import yaml

from core.classify import classify
from core.ingest import clean_text
from core.risk import assess
from core.segment import segment
from core.textutil import sentence_spans


# ---------------------------------------------------------------------------
# textutil: sentence_spans
# ---------------------------------------------------------------------------


def test_sentence_spans_basic():
    text = "First one. Second one; third.\n\nFourth"
    spans = sentence_spans(text, 0, len(text))
    assert len(spans) == 4
    sentences = [text[s:e] for s, e in spans]
    assert sentences[0] == "First one."
    assert sentences[1] == "Second one;"
    assert sentences[2] == "third."
    assert sentences[3] == "Fourth"


def test_sentence_spans_keeps_decimal_intact():
    text = "The fee is N1,000.00 payable monthly. Next sentence."
    spans = sentence_spans(text, 0, len(text))
    sentences = [text[s:e] for s, e in spans]
    assert any("N1,000.00" in s for s in sentences)
    # "N1,000.00" must not cause a split inside the number.
    for s in sentences:
        assert "1,000.00" not in s or "N1,000.00" in s


# ---------------------------------------------------------------------------
# risk.assess on sample contracts
# ---------------------------------------------------------------------------


def _expected(samples_dir):
    return yaml.safe_load((samples_dir / "expected.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def sample_names(samples_dir):
    return [p.name for p in sorted(samples_dir.glob("*.txt"))]


def test_seeded_risks_found(samples_dir, sample_names):
    for name in sample_names:
        raw = (samples_dir / name).read_text(encoding="utf-8")
        text = clean_text(raw)
        spec = _expected(samples_dir)[name]
        clauses = segment(text)
        labels = classify(clauses, spec["contract_type"])
        findings = assess(text, clauses, labels)
        found_labels = {f["label"] for f in findings}
        assert set(spec["seeded_risks"]) <= found_labels, (
            f"{name}: missing {set(spec['seeded_risks']) - found_labels}"
        )


def test_finding_offsets_match_excerpt(samples_dir, sample_names):
    for name in sample_names:
        raw = (samples_dir / name).read_text(encoding="utf-8")
        text = clean_text(raw)
        spec = _expected(samples_dir)[name]
        clauses = segment(text)
        labels = classify(clauses, spec["contract_type"])
        findings = assess(text, clauses, labels)
        for f in findings:
            if f["char_start"] is not None:
                assert text[f["char_start"] : f["char_end"]] == f["excerpt"], (
                    f"{name}: offset mismatch for {f['label']}"
                )


def test_service_level_agreement_no_high_severity(samples_dir):
    raw = (samples_dir / "service_level_agreement.txt").read_text(encoding="utf-8")
    text = clean_text(raw)
    clauses = segment(text)
    labels = classify(clauses, "sla")
    findings = assess(text, clauses, labels)
    high = [f for f in findings if f["severity"] == "High"]
    assert high == [], f"Unexpected High findings: {[f['label'] for f in high]}"


# ---------------------------------------------------------------------------
# Regression tests for the four risk-engine defects
# ---------------------------------------------------------------------------


def _assess_sample(samples_dir, name: str, contract_type: str):
    raw = (samples_dir / name).read_text(encoding="utf-8")
    text = clean_text(raw)
    clauses = segment(text)
    labels = classify(clauses, contract_type)
    return text, assess(text, clauses, labels)


def test_sla_not_flagged_one_sided_indemnity(samples_dir):
    # 8.1 Provider indemnifies Client and 8.2 Client indemnifies Provider:
    # two distinct subjects across clauses, so the indemnity is balanced.
    _, findings = _assess_sample(samples_dir, "service_level_agreement.txt", "sla")
    assert not [f for f in findings if f["label"] == "one_sided_indemnity"]
    assert not [f for f in findings if f["severity"] == "High"]


def test_loan_flagged_one_sided_termination(samples_dir):
    # Only "the Lender may terminate" appears: exactly one subject.
    _, findings = _assess_sample(samples_dir, "loan_agreement.txt", "loan")
    one_sided = [f for f in findings if f["label"] == "one_sided_termination"]
    assert len(one_sided) >= 1
    assert "Lender" in one_sided[0]["excerpt"]


def test_supply_one_sided_indemnity_reason(samples_dir):
    # Only the Supplier gives an indemnity: the reason names the party.
    _, findings = _assess_sample(samples_dir, "supply_agreement.txt", "supply")
    one_sided = [f for f in findings if f["label"] == "one_sided_indemnity"]
    assert len(one_sided) >= 1
    assert one_sided[0]["reason"].startswith("Only the Supplier")


def test_supply_foreign_governing_law_excerpt_and_single_arbitration(samples_dir):
    _, findings = _assess_sample(samples_dir, "supply_agreement.txt", "supply")
    fgl = [f for f in findings if f["label"] == "foreign_governing_law"]
    assert len(fgl) == 1
    assert "England and Wales" in fgl[0]["excerpt"]
    arb = [f for f in findings if f["label"] == "foreign_arbitration"]
    assert len(arb) == 1


def test_employment_still_flagged_one_sided_termination(samples_dir):
    _, findings = _assess_sample(samples_dir, "employment_agreement.txt", "employment")
    assert [f for f in findings if f["label"] == "one_sided_termination"]


def test_nda_flagged_one_sided_indemnity(samples_dir):
    # Only the Recipient indemnifies the Discloser.
    _, findings = _assess_sample(samples_dir, "nda.txt", "nda")
    one_sided = [f for f in findings if f["label"] == "one_sided_indemnity"]
    assert len(one_sided) >= 1
    assert "Recipient" in one_sided[0]["excerpt"]


# ---------------------------------------------------------------------------
# Hand-written texts proving specific rule behaviour
# ---------------------------------------------------------------------------


def _assess_simple(text: str, contract_type: str = "supply"):
    """Helper: segment, classify, assess a small text."""
    clauses = segment(text)
    labels = classify(clauses, contract_type)
    return assess(text, clauses, labels)


def test_rate_threshold_flags_10_percent_per_month():
    text = (
        "Clause 1: INTEREST\n"
        "1.1 The Loan shall bear interest at the rate of 10% per month.\n"
    )
    findings = _assess_simple(text)
    high_interest = [f for f in findings if f["label"] == "high_interest"]
    assert len(high_interest) >= 1
    assert "10% per month" in high_interest[0]["excerpt"]


def test_rate_threshold_ignores_28_percent_per_annum():
    text = (
        "Clause 1: INTEREST\n"
        "1.1 The Loan shall bear interest at the rate of 28% per annum.\n"
    )
    findings = _assess_simple(text)
    high_interest = [f for f in findings if f["label"] == "high_interest"]
    assert len(high_interest) == 0


def test_pattern_without_skips_auto_renewal_with_notice():
    text = (
        "Clause 1: TERM\n"
        "1.1 This Agreement shall automatically renew for successive periods of one year. "
        "Either party may give notice of non-renewal at least 30 days before expiry.\n"
    )
    findings = _assess_simple(text)
    auto = [f for f in findings if f["label"] == "auto_renewal_no_notice"]
    assert len(auto) == 0


def test_termination_balance_no_flag_when_either_party():
    text = (
        "Clause 1: TERMINATION\n"
        "1.1 Either party may terminate this Agreement by giving thirty days' written notice.\n"
    )
    findings = _assess_simple(text)
    one_sided = [f for f in findings if f["label"] == "one_sided_termination"]
    assert len(one_sided) == 0


# ---------------------------------------------------------------------------
# Regression tests for reviewer-reported false positives and misses
# ---------------------------------------------------------------------------


def _labels_for(text: str, label: str, contract_type: str = "supply"):
    return [f for f in _assess_simple(text, contract_type) if f["label"] == label]


def test_uncapped_liability_ignores_without_limitation_with_cap():
    text = (
        "Clause 1: LIABILITY\n"
        "1.1 The Supplier's total liability under this Agreement, including without "
        "limitation loss of profit, shall not exceed N10,000,000.\n"
    )
    assert _labels_for(text, "uncapped_liability") == []


def test_uncapped_liability_without_limitation_alone_is_not_uncapped():
    # "without limitation" is a drafting idiom, not a statement that liability is uncapped.
    text = (
        "Clause 1: LIABILITY\n"
        "1.1 The Supplier shall bear liability for, without limitation, loss of profit.\n"
    )
    assert _labels_for(text, "uncapped_liability") == []


def test_uncapped_liability_still_flags_without_limit():
    text = (
        "Clause 1: LIABILITY\n"
        "1.1 The Supplier's liability under this Agreement shall be without limit.\n"
    )
    assert len(_labels_for(text, "uncapped_liability")) == 1


def test_uncapped_liability_not_limited_to_is_not_a_cap():
    # "including but not limited to" is not a cap, so the unlimited sentence still counts.
    text = (
        "Clause 1: LIABILITY\n"
        "1.1 The Supplier's liability for all losses, including but not limited to "
        "loss of profit, shall be unlimited.\n"
    )
    assert len(_labels_for(text, "uncapped_liability")) == 1


def test_uncapped_liability_still_flags_supply_sample(samples_dir):
    _, findings = _assess_sample(samples_dir, "supply_agreement.txt", "supply")
    hits = [f for f in findings if f["label"] == "uncapped_liability"]
    assert len(hits) == 1
    assert "shall be unlimited" in hits[0]["excerpt"]


def test_high_interest_bracketed_percent_per_month():
    text = (
        "Clause 1: INTEREST\n"
        "1.1 Overdue sums shall bear interest at ten per cent (10%) per month.\n"
    )
    hits = _labels_for(text, "high_interest", "loan")
    assert len(hits) == 1
    assert "10" in hits[0]["reason"]


def test_high_interest_digits_with_per_cent_words():
    text = (
        "Clause 1: INTEREST\n"
        "1.1 Overdue sums shall bear interest at 10 per cent per month.\n"
    )
    assert len(_labels_for(text, "high_interest", "loan")) == 1


def test_high_interest_bracketed_per_annum_under_threshold_not_flagged():
    text = (
        "Clause 1: INTEREST\n"
        "1.1 The Loan shall bear interest at twenty-eight per cent (28%) per annum.\n"
    )
    assert _labels_for(text, "high_interest", "loan") == []


def test_high_interest_bracketed_per_annum_over_threshold_flagged():
    text = (
        "Clause 1: INTEREST\n"
        "1.1 The Loan shall bear interest at forty per cent (40%) per annum.\n"
    )
    assert len(_labels_for(text, "high_interest", "loan")) == 1


def test_termination_without_notice_ignores_neither_party():
    text = (
        "Clause 1: TERMINATION\n"
        "1.1 Neither party may terminate this Agreement without notice.\n"
    )
    assert _labels_for(text, "termination_without_notice", "employment") == []


def test_termination_without_notice_ignores_negated_verb():
    text = (
        "Clause 1: TERMINATION\n"
        "1.1 The Employer may not terminate this Agreement without notice.\n"
        "1.2 The Employee shall not terminate this Agreement without prior notice.\n"
    )
    assert _labels_for(text, "termination_without_notice", "employment") == []


def test_termination_without_notice_still_flags_positive_right():
    text = (
        "Clause 1: TERMINATION\n"
        "1.1 The Employer may terminate this Agreement at any time without notice.\n"
    )
    assert len(_labels_for(text, "termination_without_notice", "employment")) == 1
