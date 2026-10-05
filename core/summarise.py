"""Extractive contract summary: parties, dates, value, key terms, top items.

Everything is pulled verbatim from the document; no generation, no LLM.
"""

import re

from core.classify import LABEL_NAMES, explain
from core.money import find_amounts, format_kobo
from core.obligations import find_anchor_dates, key_dates
from core.textutil import sentence_spans

# Preamble entries look like: (1) NAME, ... (hereinafter referred to as "the X")
_ENTRY_RE = re.compile(r"^\((\d+)\)\s+(.*)")
# Accepts ("the X") and (the "X"), with or without "hereinafter referred to as".
_ROLE_RE = re.compile(
    r"\(\s*(?:hereinafter referred to as\s+)?(?:the\s+[\"']|[\"']the\s+)"
    r"([^\"']+?)[\"']\s*\)",
    re.IGNORECASE,
)

# Labels surfaced as key terms, in display order.
_KEY_TERM_LABELS = (
    "payment",
    "rent",
    "repayment",
    "termination",
    "governing_law",
    "dispute_resolution",
)

_SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


# "1." or "Clause 3:" left over when the sentence splitter cuts after a clause number.
_NUMBER_ONLY_RE = re.compile(r"^\s*(?:(?:clause|article|section)\s+)?\d+(?:\.\d+)*[.:]?\s*$", re.IGNORECASE)
_LEADING_NUMBER_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|\([a-z0-9]+\))\s+", re.IGNORECASE)


def _first_sentence(text: str, clauses) -> str:
    """First real sentence across clauses, skipping bare heading lines.

    A level 1 clause such as "RENT" or "Clause 8: GOVERNING LAW" holds only its
    heading, which says nothing useful in a summary, so we keep looking.
    """
    for clause in clauses:
        for start, end in sentence_spans(text, clause.char_start, clause.char_end):
            sentence = text[start:end]
            if _NUMBER_ONLY_RE.match(sentence):
                continue
            if clause.heading and sentence.strip().lower().endswith(clause.heading.lower()):
                continue
            # The summary reads better without the "3.1" clause number in front.
            return _LEADING_NUMBER_RE.sub("", sentence)
    return ""


def parties(text: str, clauses) -> list[dict]:
    """Parse "(1) NAME, ..." entries from the preamble clause (seq 0)."""
    preamble = next((c for c in clauses if c.seq == 0), None)
    if preamble is None:
        return []
    result = []
    for line in preamble.text.split("\n"):
        m = _ENTRY_RE.match(line.strip())
        if not m:
            continue
        rest = m.group(2)
        # Name runs to the first ",", " of " or " (" and is kept as written.
        name = re.split(r",| of | \(", rest, maxsplit=1)[0].strip()
        role_m = _ROLE_RE.search(rest)
        result.append({"name": name, "role": role_m.group(1) if role_m else ""})
    return result


def summarise(text, clauses, labels, findings, obligations, contract_type) -> dict:
    """Build the extractive summary dict for one analysed contract."""
    anchors = find_anchor_dates(text)
    dates = key_dates(text)

    amounts = find_amounts(text)
    value_kobo = max((k for k, _, _ in amounts), default=None)

    by_label = {}
    for clause, label in zip(clauses, labels):
        by_label.setdefault(label, []).append(clause)
    # Look at the most strongly matched clause first, so a stray weak match
    # (for example a warranty that mentions "the laws of Nigeria") does not
    # stand in for the real governing law clause. sorted() is stable.
    for label, group in by_label.items():
        by_label[label] = sorted(group, key=lambda c: -explain(c, contract_type)["score"])

    term_text = (
        _first_sentence(text, by_label["term"]) if "term" in by_label else ""
    )
    key_terms = [
        {
            "label": label,
            "name": LABEL_NAMES[label],
            "sentence": _first_sentence(text, by_label[label]),
        }
        for label in _KEY_TERM_LABELS
        if label in by_label
    ]

    # Dated obligations first by due date, then undated in document order.
    dated = sorted(
        (o for o in obligations if o.get("due_date") is not None),
        key=lambda o: o["due_date"],
    )
    undated = [o for o in obligations if o.get("due_date") is None]
    top_obligations = (dated + undated)[:5]

    risks = [f for f in findings if f["kind"] == "risk"]
    risks.sort(key=lambda f: _SEVERITY_ORDER.get(f["severity"], 3))

    return {
        "title": next((ln.strip() for ln in text.split("\n") if ln.strip()), ""),
        "contract_type": contract_type,
        "parties": parties(text, clauses),
        "agreement_date": anchors.get("date of this agreement"),
        "effective_date": dates["effective_date"],
        "expiry_date": dates["expiry_date"],
        "value_kobo": value_kobo,
        "currency": "NGN",
        "value_text": format_kobo(value_kobo) if value_kobo is not None else "",
        "term_text": term_text,
        "key_terms": key_terms,
        "top_obligations": top_obligations,
        "top_risks": risks[:5],
        "counts": {
            "clauses": len(clauses),
            "risks_high": sum(
                1 for f in findings if f["kind"] == "risk" and f["severity"] == "High"
            ),
            "risks_medium": sum(
                1
                for f in findings
                if f["kind"] == "risk" and f["severity"] == "Medium"
            ),
            "risks_low": sum(
                1 for f in findings if f["kind"] == "risk" and f["severity"] == "Low"
            ),
            "missing": sum(1 for f in findings if f["kind"] == "missing"),
            "compliance_fail": sum(
                1
                for f in findings
                if f["kind"] == "compliance" and f["severity"] != "Pass"
            ),
            "obligations": len(obligations),
        },
    }
