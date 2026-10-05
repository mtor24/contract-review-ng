"""Tests for core/compliance.py (indicative Nigerian compliance checks)."""

import pytest
import yaml

from core.classify import classify
from core.compliance import check
from core.ingest import clean_text
from core.segment import segment

# expected.yaml compliance_gaps id -> compliance check id.
_GAP_TO_CHECK = {
    "no_labour_act": "labour_act_reference",
    "no_ndpa": "ndpa_reference",
    "no_ama_2023": "ama_2023_reference",
    "no_stamp_duty": "stamp_duty_reminder",
}

DISCLAIMER = (
    "Indicative check only. This is not legal advice; "
    "confirm against current Nigerian law."
)


def _expected(samples_dir):
    return yaml.safe_load((samples_dir / "expected.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def sample_names(samples_dir):
    return [p.name for p in sorted(samples_dir.glob("*.txt"))]


def _run(samples_dir, name):
    raw = (samples_dir / name).read_text(encoding="utf-8")
    text = clean_text(raw)
    spec = _expected(samples_dir)[name]
    clauses = segment(text)
    labels = classify(clauses, spec["contract_type"])
    return text, check(text, clauses, labels, spec["contract_type"])


def test_compliance_gaps_flagged(samples_dir, sample_names):
    for name in sample_names:
        spec = _expected(samples_dir)[name]
        _, findings = _run(samples_dir, name)
        non_pass = {f["label"] for f in findings if f["severity"] != "Pass"}
        for gap in spec.get("compliance_gaps", []):
            assert _GAP_TO_CHECK[gap] in non_pass, (
                f"{name}: expected gap {_GAP_TO_CHECK[gap]} not flagged"
            )


def test_sla_passes_ndpa_ama_and_governing_law(samples_dir):
    _, findings = _run(samples_dir, "service_level_agreement.txt")
    by_label = {f["label"]: f for f in findings}
    for label in ("ndpa_reference", "ama_2023_reference", "governing_law_nigeria"):
        assert by_label[label]["severity"] == "Pass", (
            f"{label}: got {by_label[label]['severity']}"
        )


def test_supply_governing_law_high(samples_dir):
    # Governing law is England and Wales: the Nigeria check must fail High.
    _, findings = _run(samples_dir, "supply_agreement.txt")
    gl = [f for f in findings if f["label"] == "governing_law_nigeria"]
    assert len(gl) == 1
    assert gl[0]["severity"] == "High"


def test_non_applicable_checks_absent(samples_dir):
    _, nda_findings = _run(samples_dir, "nda.txt")
    assert not [f for f in nda_findings if f["label"] == "stamp_duty_reminder"]
    _, loan_findings = _run(samples_dir, "loan_agreement.txt")
    assert not [
        f
        for f in loan_findings
        if f["label"]
        in ("labour_act_reference", "employment_notice_period",
            "employment_termination_clause")
    ]


def test_reasons_end_with_disclaimer(samples_dir, sample_names):
    for name in sample_names:
        _, findings = _run(samples_dir, name)
        for f in findings:
            assert f["reason"].endswith(DISCLAIMER), (
                f"{name}/{f['label']}: reason missing disclaimer"
            )


def test_excerpt_offsets_consistent(samples_dir, sample_names):
    for name in sample_names:
        text, findings = _run(samples_dir, name)
        for f in findings:
            if f["char_start"] is not None:
                assert text[f["char_start"] : f["char_end"]] == f["excerpt"], (
                    f"{name}/{f['label']}: offset mismatch"
                )
            else:
                # No excerpt: label-based passes and all failures.
                assert f["char_end"] is None
                assert f["excerpt"] == ""
