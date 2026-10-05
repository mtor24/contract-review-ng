"""End-to-end analysis pipeline: text in, full analysis dict out."""

from core import compliance, obligations, risk
from core.classify import LABEL_NAMES, classify_with_sources, explain
from core.ingest import clean_text, extract_text
from core.missing import detect_type, find_missing
from core.segment import segment
from core.summarise import summarise

# Below this many non-whitespace characters there is nothing to review: an
# empty upload, or a scanned PDF whose pages are images with no text layer.
MIN_TEXT_CHARS = 200
NO_TEXT_MESSAGE = (
    "This file contains little or no readable text. "
    "If it is a scanned PDF, it needs OCR first."
)


def _clause_finding(clause, label, source, confidence, contract_type) -> dict:
    name = LABEL_NAMES[label]
    matched = explain(clause, contract_type)
    hits = matched["matched_heading"] + matched["matched_phrases"]
    if source == "tfidf":
        # A statistical suggestion is weaker than a rule match, so the reason
        # must say so plainly and prompt the reviewer to double-check it.
        reason = (
            "Suggested by the optional statistical model (TF-IDF), "
            f"confidence {confidence:.0%}. Check this label."
        )
    else:
        reason = f"Identified as {name} because it matched: " + ", ".join(hits)
    return {
        "kind": "clause",
        "label": label,
        "name": name,
        "severity": "Info",
        "reason": reason,
        "source": source,
        "excerpt": clause.text,
        "clause_seq": clause.seq,
        "char_start": clause.char_start,
        "char_end": clause.char_end,
    }


def analyse(
    text: str, contract_type: str | None = None, use_tfidf: bool = False
) -> dict:
    """Run the full pipeline on contract text and return the result dict.

    use_tfidf (OFF by default) lets the optional TF-IDF fallback suggest
    labels for clauses the rules label "other".
    """
    text = clean_text(text)
    if sum(not ch.isspace() for ch in text) < MIN_TEXT_CHARS:
        raise ValueError(NO_TEXT_MESSAGE)
    contract_type = contract_type or detect_type(text)
    clauses = segment(text)
    # If the segmenter found no headings, the whole contract sits in one or two
    # clauses and the checklist would wrongly report most clauses as missing.
    # Flag it for the UI instead of emitting false "missing" findings.
    body_clauses = [c for c in clauses if c.heading != "PREAMBLE"]
    segmentation_warning = len(body_clauses) <= 1
    labels, sources, confidences = classify_with_sources(
        clauses, contract_type, use_tfidf
    )

    clause_findings = [
        _clause_finding(clause, label, source, confidences.get(i, 0.0), contract_type)
        for i, (clause, label, source) in enumerate(zip(clauses, labels, sources))
        if label != "other"
    ]
    missing_findings = [] if segmentation_warning else find_missing(labels, contract_type)
    risk_findings = risk.assess(text, clauses, labels)
    compliance_findings = compliance.check(text, clauses, labels, contract_type)
    obligation_findings = obligations.extract(text, clauses)
    # Human name so reports show "Supplier obligation", not a bare kind.
    for finding in obligation_findings:
        finding["name"] = f"{finding['party']} obligation"

    findings = (
        clause_findings
        + missing_findings
        + risk_findings
        + compliance_findings
        + obligation_findings
    )
    # Stable ids: kind plus position within that kind.
    counters = {}
    for finding in findings:
        kind = finding["kind"]
        index = counters.get(kind, 0)
        counters[kind] = index + 1
        finding["fid"] = f"{kind}-{index}"

    summary = summarise(
        text, clauses, labels, findings, obligation_findings, contract_type
    )
    summary["segmentation_warning"] = segmentation_warning

    return {
        "text": text,
        "contract_type": contract_type,
        "clauses": clauses,
        "labels": labels,
        "findings": findings,
        "obligations": obligation_findings,
        "summary": summary,
    }


def analyse_file(
    data: bytes, filename: str, contract_type: str | None = None, use_tfidf: bool = False
) -> dict:
    """Extract text from uploaded bytes (.txt/.docx/.pdf), then analyse."""
    return analyse(extract_text(data, filename), contract_type, use_tfidf)
