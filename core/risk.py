"""Rule-based risk analysis driven by editable YAML.

Each rule type is a small function dispatched by a dict.
Findings follow the same shape as core/missing.py.
"""

import re

from core.rules import load_rules
from core.textutil import sentence_spans

# Severity sort order: High first, then Medium, then Low.
_SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def _make_finding(
    rule: dict,
    reason: str,
    excerpt: str = "",
    clause_seq: int | None = None,
    char_start: int | None = None,
    char_end: int | None = None,
) -> dict:
    """Build a finding dict in the standard shape."""
    return {
        "kind": "risk",
        "label": rule["id"],
        "name": rule["name"],
        "severity": rule["severity"],
        "reason": reason,
        "excerpt": excerpt,
        "clause_seq": clause_seq,
        "char_start": char_start,
        "char_end": char_end,
    }


# ---------------------------------------------------------------------------
# Rule-type implementations (one small function per type)
# ---------------------------------------------------------------------------


def _pattern(rule, text, clauses, labels):
    """Flag any sentence matching one of the rule's patterns, unless the
    same sentence matches one of its optional exclude-regexes."""
    findings = []
    seen = set()
    patterns = [re.compile(p, re.IGNORECASE) for p in rule["patterns"]]
    excludes = [re.compile(p, re.IGNORECASE) for p in rule.get("exclude", [])]
    allowed_labels = set(rule.get("labels", []))

    for clause, label in zip(clauses, labels):
        if allowed_labels and label not in allowed_labels:
            continue
        for span in sentence_spans(text, clause.char_start, clause.char_end):
            sentence = text[span[0] : span[1]]
            if any(e.search(sentence) for e in excludes):
                continue
            if any(p.search(sentence) for p in patterns):
                if span not in seen:
                    seen.add(span)
                    findings.append(
                        _make_finding(
                            rule, rule["reason"], sentence, clause.seq, span[0], span[1]
                        )
                    )
    return findings


def _pattern_without(rule, text, clauses, labels):
    """Flag a matching sentence only when none of the unless-regexes
    match the SAME clause."""
    findings = []
    seen = set()
    patterns = [re.compile(p, re.IGNORECASE) for p in rule["patterns"]]
    unless = [re.compile(p, re.IGNORECASE) for p in rule.get("unless", [])]
    allowed_labels = set(rule.get("labels", []))

    for clause, label in zip(clauses, labels):
        if allowed_labels and label not in allowed_labels:
            continue
        clause_text = text[clause.char_start : clause.char_end]
        # Skip the whole clause when any unless-regex matches it.
        if any(u.search(clause_text) for u in unless):
            continue
        for span in sentence_spans(text, clause.char_start, clause.char_end):
            sentence = text[span[0] : span[1]]
            if any(p.search(sentence) for p in patterns):
                if span not in seen:
                    seen.add(span)
                    findings.append(
                        _make_finding(
                            rule, rule["reason"], sentence, clause.seq, span[0], span[1]
                        )
                    )
    return findings


def _label_absent(rule, text, clauses, labels):
    """Flag when no clause has the given label."""
    if rule["label"] not in labels:
        return [_make_finding(rule, rule["reason"])]
    return []


def _label_without(rule, text, clauses, labels):
    """Flag when clauses with the label exist but none matches must_match."""
    target = rule["label"]
    must_match = [re.compile(p, re.IGNORECASE) for p in rule["must_match"]]
    matching = [c for c, lab in zip(clauses, labels) if lab == target]
    if not matching:
        return []
    # Check whether any matching clause satisfies must_match.
    for clause in matching:
        clause_text = text[clause.char_start : clause.char_end]
        if any(m.search(clause_text) for m in must_match):
            return []
    # None satisfied: pick a representative excerpt for the finding.
    # WHY: a clause's first sentence may be only its heading line (e.g.
    # "Clause 8: GOVERNING LAW"), which is a useless excerpt. Prefer the
    # first sentence that matches r"govern|laws? of" without being the
    # heading itself; fall back to the first non-heading sentence.
    substantive = re.compile(r"govern|laws? of", re.IGNORECASE)

    def _is_heading(sentence, clause):
        return (
            clause.heading is not None
            and sentence.strip().lower().endswith(clause.heading.lower())
        )

    for clause in matching:
        for span in sentence_spans(text, clause.char_start, clause.char_end):
            sentence = text[span[0] : span[1]]
            if substantive.search(sentence) and not _is_heading(sentence, clause):
                return [
                    _make_finding(
                        rule, rule["reason"], sentence, clause.seq, span[0], span[1]
                    )
                ]
    # Fallback: first sentence of the first clause that is more than a heading.
    for clause in matching:
        for span in sentence_spans(text, clause.char_start, clause.char_end):
            sentence = text[span[0] : span[1]]
            if not _is_heading(sentence, clause):
                return [
                    _make_finding(
                        rule, rule["reason"], sentence, clause.seq, span[0], span[1]
                    )
                ]
    # Last resort: first sentence of the first matching clause.
    first = matching[0]
    spans = sentence_spans(text, first.char_start, first.char_end)
    if spans:
        s = spans[0]
        return [
            _make_finding(rule, rule["reason"], text[s[0] : s[1]], first.seq, s[0], s[1])
        ]
    return [_make_finding(rule, rule["reason"])]


def _text_without_label(rule, text, clauses, labels):
    """Flag when patterns occur anywhere in the text but no clause has label."""
    if rule["label"] in labels:
        return []
    patterns = [re.compile(p, re.IGNORECASE) for p in rule["patterns"]]
    for clause in clauses:
        for span in sentence_spans(text, clause.char_start, clause.char_end):
            sentence = text[span[0] : span[1]]
            if any(p.search(sentence) for p in patterns):
                return [
                    _make_finding(
                        rule, rule["reason"], sentence, clause.seq, span[0], span[1]
                    )
                ]
    return []


# WHY: Nigerian drafting writes rates as "ten per cent (10%) per month" or
# "10 per cent per month", so allow "per cent" and a closing bracket
# between the number and the period.
_RATE = r"(\d+(?:\.\d+)?)\s*(?:%|per\s?cent)\)?\s*"
_MONTH_RE = re.compile(_RATE + r"(?:per month|a month|monthly)", re.IGNORECASE)
_ANNUM_RE = re.compile(
    _RATE + r"(?:per annum|a year|per year|annually)", re.IGNORECASE
)


def _rate_threshold(rule, text, clauses, labels):
    """Flag sentences whose interest rate exceeds the configured max."""
    findings = []
    per_month_max = rule["per_month_max"]
    per_annum_max = rule["per_annum_max"]

    for clause in clauses:
        for span in sentence_spans(text, clause.char_start, clause.char_end):
            sentence = text[span[0] : span[1]]
            exceeded = False
            reason = rule["reason"]
            for m in _MONTH_RE.finditer(sentence):
                rate = float(m.group(1))
                if rate > per_month_max:
                    exceeded = True
                    reason = f"The interest rate of {rate}% per month exceeds the recommended maximum of {per_month_max}% per month."
                    break
            if not exceeded:
                for m in _ANNUM_RE.finditer(sentence):
                    rate = float(m.group(1))
                    if rate > per_annum_max:
                        exceeded = True
                        reason = f"The interest rate of {rate}% per annum exceeds the recommended maximum of {per_annum_max}% per annum."
                        break
            if exceeded:
                findings.append(
                    _make_finding(rule, reason, sentence, clause.seq, span[0], span[1])
                )
    return findings


def _party_balance(rule, text, clauses, labels):
    """Generic one-sided-right check across ALL sentences in clauses with
    the given labels. Collect subjects before the verb; if a mutual phrase
    appears, or no subject found: no finding. If exactly one distinct
    subject: flag. If several subjects and one may act "without notice"
    while another must give notice: flag (only meaningful for termination).
    """
    findings = []
    verb_re = re.compile(rule["verb"], re.IGNORECASE)
    mutual_res = [re.compile(p, re.IGNORECASE) for p in rule.get("mutual", [])]
    allowed_labels = set(rule.get("labels", []))

    subjects = {}  # subject -> list of (sentence, span, clause_seq, without_notice)
    mutual_found = False

    for clause, label in zip(clauses, labels):
        if allowed_labels and label not in allowed_labels:
            continue
        for span in sentence_spans(text, clause.char_start, clause.char_end):
            sentence = text[span[0] : span[1]]
            if not verb_re.search(sentence):
                continue
            if any(m.search(sentence) for m in mutual_res):
                mutual_found = True
                break
            # WHY: capture the capitalised subject right before the verb so
            # we can compare who holds the right across the whole document.
            m = re.search(
                r"([A-Z][\w]*(?:\s+[A-Z][\w]*)*)\s+" + rule["verb"], sentence
            )
            if m:
                subject = m.group(1)
                without_notice = bool(
                    re.search(
                        r"without\s+(any\s+|prior\s+)?notice",
                        sentence,
                        re.IGNORECASE,
                    )
                )
                subjects.setdefault(subject, []).append(
                    (sentence, span, clause.seq, without_notice)
                )
        if mutual_found:
            break

    if mutual_found or len(subjects) == 0:
        return findings

    # (b) only one distinct subject holds the right
    if len(subjects) == 1:
        subject, entries = next(iter(subjects.items()))
        sentence, span, seq, _ = entries[0]
        # WHY: strip "The "/"the " so the rule's sentence template reads
        # naturally ("Only the Lender ..." not "Only the The Lender ...").
        subject = re.sub(r"^(?:[Tt]he )", "", subject)
        template = rule.get(
            "reason_one_subject",
            "Only the {subject} has the right. The right should be balanced.",
        )
        findings.append(
            _make_finding(
                rule,
                template.format(subject=subject),
                sentence,
                seq,
                span[0],
                span[1],
            )
        )
        return findings

    # (c) one subject may act without notice while another must give notice
    notice_map = {s: any(e[3] for e in entries) for s, entries in subjects.items()}
    if any(notice_map.values()) and not all(notice_map.values()):
        for subject, entries in subjects.items():
            if notice_map[subject]:
                sentence, span, seq, _ = entries[0]
                findings.append(
                    _make_finding(
                        rule,
                        f"{subject} may act without notice while another party must give notice.",
                        sentence,
                        seq,
                        span[0],
                        span[1],
                    )
                )
                break
    return findings


# Dispatch table: rule type -> implementation function.
_DISPATCH = {
    "pattern": _pattern,
    "pattern_without": _pattern_without,
    "label_absent": _label_absent,
    "label_without": _label_without,
    "text_without_label": _text_without_label,
    "rate_threshold": _rate_threshold,
    "party_balance": _party_balance,
}


def assess(text: str, clauses, labels) -> list[dict]:
    """Run every rule from load_rules("risk_rules") and return findings
    sorted High, Medium, Low then by char_start (None last)."""
    rules = load_rules("risk_rules")["rules"]
    findings = []
    for rule in rules:
        handler = _DISPATCH.get(rule["type"])
        if handler:
            rule_findings = handler(rule, text, clauses, labels)
            # WHY: some rules should only ever report once per document.
            if rule.get("once") and rule_findings:
                rule_findings = rule_findings[:1]
            findings.extend(rule_findings)

    findings.sort(
        key=lambda f: (
            _SEVERITY_ORDER.get(f["severity"], 3),
            f["char_start"] if f["char_start"] is not None else float("inf"),
        )
    )
    return findings
