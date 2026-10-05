import pytest
import yaml

from core.classify import classify
from core.missing import detect_type, find_missing
from core.segment import segment


def _expected(samples_dir):
    return yaml.safe_load((samples_dir / "expected.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def sample_names(samples_dir):
    return [p.name for p in sorted(samples_dir.glob("*.txt"))]


def test_detect_type_matches_expected(samples_dir, sample_names):
    for name in sample_names:
        text = (samples_dir / name).read_text(encoding="utf-8")
        assert detect_type(text) == _expected(samples_dir)[name]["contract_type"], name


def test_detect_type_defaults_to_supply():
    assert detect_type("The quick brown fox jumps over the lazy dog.") == "supply"


def test_find_missing_covers_expected(samples_dir, sample_names):
    for name in sample_names:
        text = (samples_dir / name).read_text(encoding="utf-8")
        spec = _expected(samples_dir)[name]
        clauses = segment(text)
        labels = classify(clauses, spec["contract_type"])
        findings = find_missing(labels, spec["contract_type"])
        missing_labels = {f["label"] for f in findings}
        assert set(spec["missing_clauses"]) <= missing_labels, name
        if name == "service_level_agreement.txt":
            assert findings == []


def test_severity_rule():
    labels = ["parties"]  # everything else missing
    findings = find_missing(labels, "employment")
    by_label = {f["label"]: f["severity"] for f in findings}
    for label in ("governing_law", "dispute_resolution", "termination", "data_protection"):
        assert by_label[label] == "High", label
    for label in ("term", "payment", "confidentiality"):
        assert by_label[label] == "Medium", label
    # present labels produce no finding
    assert "parties" not in by_label
