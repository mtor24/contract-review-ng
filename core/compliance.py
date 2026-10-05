"""Indicative Nigerian compliance checks driven by rules/nigeria_compliance.yaml.

Each check produces exactly one finding (Pass or fail severity) when it
applies to the contract; inapplicable checks are skipped entirely.
Findings reuse the shape from core/risk.py with kind "compliance".
"""

import re

from core.rules import load_rules
from core.textutil import sentence_spans

# Severity sort order: High first, then Medium, then Low; Pass last.
_SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2, "Pass": 3}


def _applies_to(check: dict, contract_type: str | None) -> bool:
    applies = check.get("applies_to", "all")
    if applies == "all" or "all" in applies:
        return True
    return contract_type in applies


def _applies_if(check: dict, text: str) -> bool:
    patterns = check.get("applies_if")
    if not patterns:
        return True
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _find_pass_sentence(check: dict, text: str, clauses, labels):
    """Return (sentence, span, clause_seq) of the first sentence matching
    pass_if, or None. Optional `labels` restricts the search to clauses
    with those classification labels."""
    patterns = [re.compile(p, re.IGNORECASE) for p in check.get("pass_if", [])]
    if not patterns:
        return None
    allowed_labels = set(check.get("labels", []))
    for clause, label in zip(clauses, labels):
        if allowed_labels and label not in allowed_labels:
            continue
        for span in sentence_spans(text, clause.char_start, clause.char_end):
            sentence = text[span[0] : span[1]]
            if any(p.search(sentence) for p in patterns):
                return sentence, span, clause.seq
    return None


def _run_check(check: dict, text: str, clauses, labels) -> dict:
    """Run one applicable check; return a single compliance finding."""
    disclaimer = check["_disclaimer"]
    requires_label = check.get("requires_label")

    if requires_label:
        # WHY: a label-based pass has no excerpt; presence of the label is
        # itself the evidence.
        passed = requires_label in labels
        match = None
    else:
        match = _find_pass_sentence(check, text, clauses, labels)
        passed = match is not None

    if passed:
        reason = check["pass_reason"]
        severity = "Pass"
    else:
        reason = check["fail_reason"]
        severity = check["fail_severity"]

    excerpt, clause_seq, char_start, char_end = "", None, None, None
    if match is not None:
        sentence, span, clause_seq = match
        excerpt, char_start, char_end = sentence, span[0], span[1]

    return {
        "kind": "compliance",
        "label": check["id"],
        "name": check["name"],
        "severity": severity,
        "reason": f"{reason} {disclaimer}",
        "reference": check["reference"],
        "excerpt": excerpt,
        "clause_seq": clause_seq,
        "char_start": char_start,
        "char_end": char_end,
    }


def check(text: str, clauses, labels, contract_type: str | None) -> list[dict]:
    """Run every applicable compliance check; return one finding each.

    Ordering: failed checks first (High, Medium, Low), then passes."""
    spec = load_rules("nigeria_compliance")
    findings = []
    for chk in spec["checks"]:
        chk = dict(chk)
        chk["_disclaimer"] = spec["disclaimer"]
        if not _applies_to(chk, contract_type):
            continue
        if not _applies_if(chk, text):
            continue
        findings.append(_run_check(chk, text, clauses, labels))

    findings.sort(key=lambda f: _SEVERITY_ORDER.get(f["severity"], 4))
    return findings
