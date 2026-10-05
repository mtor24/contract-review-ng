"""Rule-based clause classification driven by rules/clause_patterns.yaml."""

import functools
import re

from spacy.matcher import PhraseMatcher

from core.nlp import get_nlp
from core.rules import load_rules
from core import tfidf


def _build_matchers():
    """Compile one PhraseMatcher per label from the YAML, once per process."""
    nlp = get_nlp()
    rules = load_rules("clause_patterns")
    matchers = {}
    for label_id, spec in rules["labels"].items():
        matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
        patterns = [nlp.make_doc(phrase) for phrase in spec["phrases"]]
        matcher.add(label_id, patterns)
        matchers[label_id] = matcher
    return rules, matchers


@functools.lru_cache(maxsize=1)
def _cached_matchers():
    return _build_matchers()


def _heading_hits(heading: str | None, keywords: list[str]) -> list[str]:
    """Return keywords that appear as whole words in the heading."""
    if not heading:
        return []
    text = heading.lower()
    hits = []
    for kw in keywords:
        # Whole-word match so "term" does not match inside "termination".
        if re.search(rf"\b{re.escape(kw)}\b", text):
            hits.append(kw)
    return hits


def _heading_weight(clause, rules) -> int:
    # Level 2 clauses inherit their parent's heading; that inherited signal
    # is weaker than the sub-clause's own words, so it scores phrase_weight.
    # A clause's own heading line (level 0/1) keeps the full heading_weight.
    if getattr(clause, "level", 1) >= 2:
        return rules["phrase_weight"]
    return rules["heading_weight"]


def _score_clause(clause, rules, matchers, contract_type=None) -> tuple[dict, dict, dict]:
    """Score every label for one clause; returns (scores, heading_hits, phrase_hits)."""
    hw = _heading_weight(clause, rules)
    pw = rules["phrase_weight"]
    scores, heading_hits, phrase_hits = {}, {}, {}
    doc = get_nlp()(clause.text)
    for label_id, spec in rules["labels"].items():
        # only_for restricts a label to listed contract types; None allows all.
        only_for = spec.get("only_for")
        if contract_type is not None and only_for and contract_type not in only_for:
            scores[label_id] = 0
            heading_hits[label_id] = []
            phrase_hits[label_id] = []
            continue
        h_hits = _heading_hits(clause.heading, spec["heading_keywords"])
        matches = matchers[label_id](doc)
        # Count distinct matched phrases, not occurrences, to stop repetition
        # of one word (e.g. "the indemnity ... the indemnity") dominating.
        p_hits = sorted({doc[start:end].text.lower() for _, start, end in matches})
        # A heading counts once per label: overlapping keywords such as "law" and
        # "governing law" on one heading must not outvote the clause's own words.
        scores[label_id] = hw * bool(h_hits) + pw * len(p_hits)
        heading_hits[label_id] = h_hits
        phrase_hits[label_id] = p_hits
    return scores, heading_hits, phrase_hits


def _pick_label(clause, scores) -> str:
    # The preamble (seq 0) always describes the parties, by construction.
    if clause.heading == "PREAMBLE" and clause.seq == 0:
        return "parties"
    best, best_score = "other", 0
    # dict order is YAML order, so max-with->-first-wins breaks ties correctly.
    for label_id, score in scores.items():
        if score > best_score:
            best, best_score = label_id, score
    return best


def _allowed(label_id: str, rules, contract_type: str | None) -> bool:
    """True when the label's only_for list permits this contract type."""
    only_for = rules["labels"][label_id].get("only_for")
    return not (contract_type is not None and only_for and contract_type not in only_for)


def _tfidf_suggestions(clauses, labels, rules, contract_type) -> dict:
    """Map clause index -> (suggested label, confidence) for clauses the rules
    called "other" (never the preamble). Suggestions respect only_for, so the
    model cannot label an NDA clause "rent" just because it mentions payments."""
    other_idx = [
        i
        for i, (clause, label) in enumerate(zip(clauses, labels))
        if label == "other" and not (clause.heading == "PREAMBLE" and clause.seq == 0)
    ]
    suggestions = tfidf.suggest([clauses[i].text for i in other_idx])
    return {
        i: (suggested, prob)
        for i, (suggested, prob) in zip(other_idx, suggestions)
        if suggested is not None and _allowed(suggested, rules, contract_type)
    }


def classify_with_sources(
    clauses, contract_type: str | None = None, use_tfidf: bool = False
) -> tuple[list[str], list[str], dict]:
    """Classify clauses, returning (labels, sources, confidences).

    Sources are "rule" (matched the YAML rules), "tfidf" (suggested by the
    optional statistical fallback) or "none" (still "other"). Confidences
    maps clause index -> model probability for tfidf labels only. use_tfidf
    is False by default: the fallback never runs unless asked for.
    """
    rules, matchers = _cached_matchers()
    labels = []
    for clause in clauses:
        scores, _, _ = _score_clause(clause, rules, matchers, contract_type)
        labels.append(_pick_label(clause, scores))
    sources = ["none" if label == "other" else "rule" for label in labels]
    confidences = {}

    if use_tfidf:
        for i, (suggested, prob) in _tfidf_suggestions(
            clauses, labels, rules, contract_type
        ).items():
            labels[i] = suggested
            sources[i] = "tfidf"
            confidences[i] = prob
    return labels, sources, confidences


def classify(
    clauses, contract_type: str | None = None, use_tfidf: bool = False
) -> list[str]:
    """Return one label per clause, in the same order. When contract_type is
    given, labels whose only_for list excludes it score 0. When use_tfidf is
    True, the optional statistical fallback may re-label "other" clauses."""
    labels, _, _ = classify_with_sources(clauses, contract_type, use_tfidf)
    return labels


def explain(clause, contract_type: str | None = None) -> dict:
    """Show WHY a clause got its label, for the UI transparency panel."""
    rules, matchers = _cached_matchers()
    scores, heading_hits, phrase_hits = _score_clause(
        clause, rules, matchers, contract_type
    )
    label = _pick_label(clause, scores)
    return {
        "label": label,
        "score": scores.get(label, 0),
        "matched_heading": heading_hits.get(label, []),
        "matched_phrases": phrase_hits.get(label, []),
    }


def _build_label_names() -> dict[str, str]:
    rules = load_rules("clause_patterns")
    names = {label_id: spec["name"] for label_id, spec in rules["labels"].items()}
    names["other"] = "Other"
    return names


# id -> human-readable name, for display in the UI.
LABEL_NAMES: dict[str, str] = _build_label_names()
