from pathlib import Path

import pytest
import yaml

from core.classify import classify, explain
from core.segment import Clause, segment


def _clause(heading, text, seq=1):
    return Clause(
        seq=seq,
        number=None,
        heading=heading,
        text=text,
        char_start=0,
        char_end=len(text),
        level=1,
    )


def test_governing_law_by_heading_and_text():
    c = _clause(
        "GOVERNING LAW",
        "GOVERNING LAW\n\nThis Agreement shall be governed by the laws of the "
        "Federal Republic of Nigeria.",
    )
    assert classify([c]) == ["governing_law"]


def test_arbitration_is_dispute_resolution():
    c = _clause(
        None,
        "Any dispute shall be referred to arbitration by a sole arbitrator, "
        "with the seat of arbitration in Lagos.",
    )
    assert classify([c]) == ["dispute_resolution"]


def test_data_protection():
    c = _clause(
        None,
        "Each party shall process personal data in accordance with the "
        "Nigeria Data Protection Act 2023.",
    )
    assert classify([c]) == ["data_protection"]


def test_rent_clause():
    c = _clause("RENT", "RENT\n\nThe Tenant shall pay rent of N18,000,000 per annum.")
    assert classify([c]) == ["rent"]


def test_nonsense_is_other():
    c = _clause(None, "The quick brown fox jumps over the lazy dog repeatedly.")
    assert classify([c]) == ["other"]


def test_explain_governing_law():
    c = _clause(
        "GOVERNING LAW",
        "This Agreement shall be governed by the laws of the Federal Republic "
        "of Nigeria.",
    )
    info = explain(c)
    assert info["label"] == "governing_law"
    assert info["score"] > 0
    assert info["matched_phrases"]  # at least one phrase recorded


def _contract_types(samples_dir):
    data = yaml.safe_load((samples_dir / "expected.yaml").read_text(encoding="utf-8"))
    return {name: spec["contract_type"] for name, spec in data.items()}


def _labels_for(samples_dir, name):
    text = (samples_dir / name).read_text(encoding="utf-8")
    clauses = segment(text)
    contract_type = _contract_types(samples_dir)[name]
    return clauses, classify(clauses, contract_type=contract_type)


def _clause_rows(samples_dir, name):
    """(number, heading, label) per clause, for targeted regression checks."""
    clauses, labels = _labels_for(samples_dir, name)
    return [(c.number, c.heading or "", label) for c, label in zip(clauses, labels)]


def test_supply_agreement_expected_labels(samples_dir):
    _, labels = _labels_for(samples_dir, "supply_agreement.txt")
    assert {
        "governing_law",
        "dispute_resolution",
        "indemnity",
        "limitation_of_liability",
        "payment",
        "force_majeure",
    } <= set(labels)
    assert "notices" not in labels


def test_sla_expected_labels(samples_dir):
    _, labels = _labels_for(samples_dir, "service_level_agreement.txt")
    assert {
        "data_protection",
        "service_levels",
        "notices",
        "assignment",
        "confidentiality",
        "force_majeure",
    } <= set(labels)


def test_every_sample_mostly_labelled(samples_dir):
    for path in sorted(samples_dir.glob("*.txt")):
        clauses = segment(path.read_text(encoding="utf-8"))
        labels = classify(clauses)
        assert len(labels) == len(clauses), path.name
        other_ratio = labels.count("other") / len(labels)
        assert other_ratio < 0.40, (path.name, labels)


def test_employment_no_service_levels(samples_dir):
    clauses, labels = _labels_for(samples_dir, "employment_agreement.txt")
    assert "service_levels" not in labels
    for c, label in zip(clauses, labels):
        if c.number == "8.1":
            assert label == "other"


def test_partnership_no_service_levels_rent_repayment(samples_dir):
    _, labels = _labels_for(samples_dir, "partnership_agreement.txt")
    assert "service_levels" not in labels
    assert "rent" not in labels
    assert "repayment" not in labels


def test_loan_representations_not_definitions(samples_dir):
    rows = _clause_rows(samples_dir, "loan_agreement.txt")
    in_reps = False
    for number, heading, label in rows:
        if heading == "REPRESENTATIONS AND WARRANTIES":
            in_reps = True
        elif number and "." not in number:
            in_reps = False
        if in_reps:
            assert label != "definitions", (number, heading)


def test_lease_repair_clauses_not_termination(samples_dir):
    rows = _clause_rows(samples_dir, "lease_agreement.txt")
    labels = [label for _, _, label in rows]
    assert "repayment" not in labels
    for _, heading, label in rows:
        if heading in ("REPAIRS", "HOLDING OVER"):
            assert label != "termination", heading
        if heading == "RENT REVIEW":
            assert label == "rent"


def test_supply_payment_liability_indemnity(samples_dir):
    rows = _clause_rows(samples_dir, "supply_agreement.txt")
    for _, heading, label in rows:
        if heading == "PRICE AND PAYMENT":
            assert label == "payment"
        if heading == "LIABILITY":
            assert label == "limitation_of_liability"
        if heading == "INDEMNITY":
            assert label == "indemnity"


def test_sla_service_level_clauses(samples_dir):
    rows = _clause_rows(samples_dir, "service_level_agreement.txt")
    for _, heading, label in rows:
        if heading in ("SERVICE LEVELS", "SERVICE CREDITS"):
            assert label == "service_levels", heading


def test_classify_without_contract_type_still_works(samples_dir):
    text = (samples_dir / "service_level_agreement.txt").read_text(encoding="utf-8")
    clauses = segment(text)
    labels = classify(clauses)
    assert len(labels) == len(clauses)
    assert "service_levels" in labels
