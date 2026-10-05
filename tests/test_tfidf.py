"""Tests for the optional TF-IDF fallback classifier (core/tfidf.py).

The fallback is OFF by default; these tests prove that turning it on never
changes a rule-based label and only ever reduces the "other" count.
"""

import yaml

from core import tfidf
from core.classify import classify, classify_with_sources
from core.pipeline import analyse
from core.segment import segment


def _sample_texts(samples_dir):
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(samples_dir.glob("*.txt"))}


def _contract_types(samples_dir):
    data = yaml.safe_load((samples_dir / "expected.yaml").read_text(encoding="utf-8"))
    return {name: spec["contract_type"] for name, spec in data.items()}


def test_get_model_trains():
    model = tfidf.get_model()
    # One probability per label in clause_patterns.yaml.
    assert len(model.classes_) == 19


def test_suggest_governing_law_above_threshold():
    results = tfidf.suggest(
        ["This Agreement shall be governed by the laws of the Federal Republic of Nigeria"]
    )
    label, prob = results[0]
    assert label == "governing_law"
    assert prob >= 0.45


def test_classify_default_unchanged_by_flag(samples_dir):
    """classify(..., use_tfidf=False) must equal classify(...) for every sample."""
    types = _contract_types(samples_dir)
    for name, text in _sample_texts(samples_dir).items():
        clauses = segment(text)
        assert classify(clauses, types[name], use_tfidf=False) == classify(
            clauses, types[name]
        ), name


def test_classify_with_sources_respects_rules(samples_dir):
    types = _contract_types(samples_dir)
    for name, text in _sample_texts(samples_dir).items():
        clauses = segment(text)
        rule_only = classify(clauses, types[name])
        labels, sources, confidences = classify_with_sources(
            clauses, types[name], use_tfidf=True
        )
        assert len(labels) == len(sources) == len(clauses), name
        assert set(sources) <= {"rule", "tfidf", "none"}, name
        # A "rule" source means the fallback never touched that clause.
        for source, label, rule_label in zip(sources, labels, rule_only):
            if source == "rule":
                assert label == rule_label, name
            else:
                assert rule_label == "other", name
        # The fallback may only reduce the number of "other" clauses.
        assert labels.count("other") <= rule_only.count("other"), name
        # Confidences only exist for tfidf-suggested clauses.
        assert set(confidences) == {
            i for i, source in enumerate(sources) if source == "tfidf"
        }, name


def test_analyse_tfidf_findings_carry_source_and_reason(samples_dir):
    types = _contract_types(samples_dir)
    saw_tfidf = False
    for name, text in _sample_texts(samples_dir).items():
        result = analyse(text, types[name], use_tfidf=True)
        clause_findings = [f for f in result["findings"] if f["kind"] == "clause"]
        for finding in clause_findings:
            assert finding["source"] in {"rule", "tfidf"}, name
            if finding["source"] == "tfidf":
                saw_tfidf = True
                assert (
                    "Suggested by the optional statistical model" in finding["reason"]
                ), (name, finding["reason"])
    # The samples contain clauses the rules miss (e.g. boilerplate "GENERAL"
    # clauses), so at least one suggestion should appear across the set.
    assert saw_tfidf


def test_analyse_default_has_no_tfidf_sources(samples_dir):
    result = analyse(_sample_texts(samples_dir)["nda.txt"], "nda")
    clause_findings = [f for f in result["findings"] if f["kind"] == "clause"]
    assert {f["source"] for f in clause_findings} == {"rule"}
