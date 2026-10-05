"""Obligation and deadline extraction from contract text.

Finds sentences with modal verbs (shall/must/will/agrees to/undertakes to),
works out who owes the duty, and resolves due dates against anchor dates
found in the document.
"""

import calendar
import re
from datetime import date, timedelta

import dateparser

from core.textutil import sentence_spans

# Absolute dates like "1 March 2026" or "15th February 2026".
DATE_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{4})\b",
    re.IGNORECASE,
)

# "made on the 14th day of February 2026" starts the document clock.
_MADE_ON_RE = re.compile(
    r"made on the (\d{1,2})(?:st|nd|rd|th)? day of "
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{4})",
    re.IGNORECASE,
)

# "commence on 1 March 2026" / "commencing on 1 January 2026".
_COMMENCE_RE = re.compile(
    r"commenc(?:e|ing) on (\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{4})",
    re.IGNORECASE,
)

# "expiring on 31 December 2028" / "expire on ...".
_EXPIRE_RE = re.compile(
    r"expir(?:ing|e) on (\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{4})",
    re.IGNORECASE,
)

_DATE_TEXT = (
    r"\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{4}"
)

# A date followed shortly by a defined term: (hereinafter referred to as
# "the Drawdown Date"), ("the Review Date") or (the "Maturity Date").
# WHY the tempered gap: the gap may not contain another date, so in
# "disbursed on 1 March 2026 and repaid on 1 March 2027 (the "Maturity Date")"
# the term binds to the date nearest the bracket, not the first one.
_DEFINED_DATE_RE = re.compile(
    r"\b(" + _DATE_TEXT + r")"
    r"(?:(?!" + _DATE_TEXT + r").){0,80}?"
    r"\(\s*(?:hereinafter referred to as\s+)?(?:the\s+)?[\"'](?:the\s+)?"
    r"([A-Za-z][A-Za-z ]*?\s+Date)[\"']\s*\)",
    re.IGNORECASE | re.DOTALL,
)

# "term of three (3) years" / "continue for an initial term of two (2) years".
_TERM_RE = re.compile(
    r"(?:initial )?term of [a-z\- ]*\(?(\d+)\)?\s*(year|month)s?",
    re.IGNORECASE,
)
_CONTINUE_TERM_RE = re.compile(
    r"continue for an initial term of [a-z\- ]*\(?(\d+)\)?\s*(year|month)s?",
    re.IGNORECASE,
)

# Sentences that create duties.
_MODAL_RE = re.compile(r"\b(shall|must|will|agrees? to|undertakes? to)\b", re.IGNORECASE)

# Definitions, governing-law and disclaimer sentences are not real duties.
_SKIP_RE = re.compile(
    r"shall mean|means\b|shall be governed|shall be construed|shall not be liable",
    re.IGNORECASE,
)

# Defined party roles: (hereinafter referred to as "the Employer") and
# ("the X") / (the "X") variants. Roles appear in the preamble, so only
# the first 40 lines are scanned.
_ROLE_RE = re.compile(
    r"\(\s*(?:hereinafter referred to as\s+)?(?:the\s+[\"']|[\"']the\s+)"
    r"([A-Za-z][A-Za-z ]*?)[\"']\s*\)",
    re.IGNORECASE,
)

# Generic subjects that always owe duties whoever the named parties are.
_GENERIC_PARTIES = (
    "Each party",
    "Either party",
    "Neither party",
    "The parties",
    "Each partner",
    "Any partner",
    "partners",
)

# The definition line of a true party names a person or company; defined
# terms like "the Loan" or "the Services" do not.
_PARTY_HINT_RE = re.compile(
    r"\b(?:LIMITED|LTD|PLC|INC|LLP|RC Number)\b|\b(?:MR|MRS|MS|MISS|DR)\."
)

# Capitalised subject immediately before the modal verb.
_PARTY_RE = re.compile(
    r"((?:[Tt]he |[Ee]ach |[Ee]ither |[Nn]either |[Aa]ny )?(?:[A-Z][a-z]+ ){0,2}"
    r"(?:[A-Z][a-z]+|party|partner|partners))\s+"
    r"(?:shall|must|will|agrees?|undertakes?)"
)

# "within 30 days of the Drawdown Date" / "within five (5) business days from ...".
_PERIOD_RE = re.compile(
    r"within\s+(?:[a-z\-]+\s+)?\(?(\d+)\)?\s+(business\s+)?(day|week|month|year)s?"
    r"\s+(?:of|from|after)\s+(?:the\s+)?([^,.;]+)",
    re.IGNORECASE,
)

# Absolute deadline: "on 1 March 2026" / "by ..." / "before ..." / "not later than ...".
_ABS_DEADLINE_RE = re.compile(
    r"((?:on|by|before|not later than)\s+\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{4})",
    re.IGNORECASE,
)


def _parse_date(text: str) -> date | None:
    """Parse an absolute date string with dateparser (DMY, never search)."""
    parsed = dateparser.parse(
        text, settings={"DATE_ORDER": "DMY", "PREFER_DAY_OF_MONTH": "first"}
    )
    return parsed.date() if parsed else None


def add_months(d: date, months: int) -> date:
    """Add calendar months, clamping the day to the target month's last day."""
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _add_period(d: date, n: int, unit: str, business: bool) -> date:
    """Add a period to a date; business days skip Saturday/Sunday."""
    unit = unit.lower()
    if business or unit == "day":
        if not business:
            return d + timedelta(days=n)
        result, remaining = d, n
        while remaining > 0:
            result += timedelta(days=1)
            if result.weekday() < 5:
                remaining -= 1
        return result
    if unit == "week":
        return d + timedelta(weeks=n)
    if unit == "month":
        return add_months(d, n)
    return add_months(d, n * 12)


def find_anchor_dates(text: str) -> dict[str, date]:
    """Find named dates in the document: agreement date, commencement,
    effective date, expiry and any defined "... Date" terms."""
    anchors: dict[str, date] = {}

    m = _MADE_ON_RE.search(text)
    if m:
        d = _parse_date(f"{m.group(1)} {m.group(2)} {m.group(3)}")
        if d:
            anchors["date of this agreement"] = d

    for m in _DEFINED_DATE_RE.finditer(text):
        d = _parse_date(m.group(1))
        if d:
            anchors[m.group(2).strip().lower()] = d

    m = _COMMENCE_RE.search(text)
    if m:
        d = _parse_date(m.group(1))
        if d:
            anchors["commencement date"] = d
            anchors["effective date"] = d
    # Without an explicit commencement, the agreement date is the fallback.
    if "commencement date" not in anchors and "date of this agreement" in anchors:
        anchors["commencement date"] = anchors["date of this agreement"]
        anchors["effective date"] = anchors["date of this agreement"]

    m = _EXPIRE_RE.search(text)
    if m:
        d = _parse_date(m.group(1))
        if d:
            anchors["expiry date"] = d

    return anchors


def key_dates(text: str) -> dict:
    """Return the effective and expiry dates; derive expiry from the term
    length when no explicit expiry date is stated."""
    anchors = find_anchor_dates(text)
    effective = anchors.get("effective date")
    expiry = anchors.get("expiry date")

    if expiry is None and effective is not None:
        m = _TERM_RE.search(text) or _CONTINUE_TERM_RE.search(text)
        if m:
            n, unit = int(m.group(1)), m.group(2).lower()
            # WHY: the end date is the anniversary; some drafters use the day before.
            expiry = add_months(effective, n if unit == "month" else n * 12)

    return {"effective_date": effective, "expiry_date": expiry}


# Aliases that all mean the agreement signing date.
_ANCHOR_ALIASES = {
    "execution of this agreement": "date of this agreement",
    "signing of this agreement": "date of this agreement",
    "date hereof": "date of this agreement",
}


def _lookup_anchor(phrase: str, anchors: dict[str, date]) -> tuple[str | None, date | None]:
    """Resolve an anchor phrase like "the Drawdown Date" against found anchors:
    exact key first, then any key contained in the phrase."""
    key = phrase.strip().lower()
    # Aliases like "execution of this agreement" share the signing date.
    for alias, target in _ANCHOR_ALIASES.items():
        if alias in key and target in anchors:
            return target, anchors[target]
    if key in anchors:
        return key, anchors[key]
    for name, d in anchors.items():
        # "the effective date of termination" contains "effective date" but means a
        # different, unknown date. Only accept the key when nothing follows it except
        # a reference back to this Agreement.
        if key.startswith(name) and key[len(name):].strip() in ("", "of this agreement", "hereof"):
            return name, d
    return None, None


def party_roles(text: str) -> list[str]:
    """Defined party roles from the preamble (first 40 lines), plus the
    generic subjects ("Each party", "partners", ...)."""
    head = "\n".join(text.splitlines()[:40])
    roles = []
    for m in _ROLE_RE.finditer(head):
        role = m.group(1).strip()
        # Skip non-party defined terms: dates, and terms whose definition
        # line names no person or company.
        if role.lower().endswith(" date"):
            continue
        line_start = head.rfind("\n", 0, m.start()) + 1
        line_end = head.find("\n", m.end())
        line = head[line_start : line_end if line_end != -1 else len(head)]
        if not (_PARTY_HINT_RE.search(line) or role.lower().endswith("partner")):
            continue
        roles.append(role)
    seen = set()
    unique = [r for r in roles if not (r.lower() in seen or seen.add(r.lower()))]
    return unique + [g for g in _GENERIC_PARTIES]


def _party_for(sentence: str, roles: list[str]) -> str:
    """Party owing the duty: the subject before the modal if it is a known
    role, else the first role mentioned anywhere in the sentence."""
    m = _PARTY_RE.search(sentence)
    if m:
        subject = m.group(1).strip()
        for prefix in ("The ", "the "):
            if subject.startswith(prefix):
                subject = subject[len(prefix) :]
                break
        for role in roles:
            if subject.lower() == role.strip().lower().removeprefix("the "):
                return subject
    # Subject was not a role: fall back to the first role named in the sentence.
    best_pos, best_role = None, None
    for role in roles:
        # Word boundaries keep "partners" from matching "partnership".
        m = re.search(r"\b" + re.escape(role) + r"\b", sentence, re.IGNORECASE)
        if m and (best_pos is None or m.start() < best_pos):
            best_pos, best_role = m.start(), role
    return best_role if best_role else "Unspecified"


def _deadline(sentence: str, anchors: dict[str, date]) -> tuple[str, str | None, date | None]:
    """Return (period_text, anchor_key, due_date) for a sentence."""
    m = _PERIOD_RE.search(sentence)
    if m:
        n = int(m.group(1))
        business = bool(m.group(2))
        unit = m.group(3)
        anchor_key, anchor_date = _lookup_anchor(m.group(4), anchors)
        due = _add_period(anchor_date, n, unit, business) if anchor_date else None
        return m.group(0), anchor_key, due
    m = _ABS_DEADLINE_RE.search(sentence)
    if m:
        return m.group(1), None, _parse_date(m.group(1))
    return "", None, None


def extract(text: str, clauses) -> list[dict]:
    """Extract obligation findings from every clause's duty sentences."""
    anchors = find_anchor_dates(text)
    roles = party_roles(text)
    obligations = []

    for clause in clauses:
        for span in sentence_spans(text, clause.char_start, clause.char_end):
            sentence = text[span[0] : span[1]]
            if not _MODAL_RE.search(sentence):
                continue
            if _SKIP_RE.search(sentence):
                continue
            party = _party_for(sentence, roles)
            period_text, anchor, due_date = _deadline(sentence, anchors)
            # No duty-holder and no deadline: not an actionable obligation.
            # A bare date with no named party ("This Agreement shall commence on
            # 1 November 2026") is a key date, not somebody's deadline.
            if party == "Unspecified" and not period_text.lower().startswith("within"):
                continue
            reason = f"Obligation on {party}"
            if period_text:
                reason += f", due {period_text}"
            obligations.append(
                {
                    "kind": "obligation",
                    "label": "obligation",
                    "severity": "Info",
                    "party": party,
                    "excerpt": sentence,
                    "period_text": period_text,
                    "anchor": anchor,
                    "due_date": due_date,
                    "reason": reason,
                    "clause_seq": clause.seq,
                    "char_start": span[0],
                    "char_end": span[1],
                }
            )
    return obligations


def upcoming(obligations: list[dict], today: date, days: int) -> list[dict]:
    """Obligations due between today and today+days inclusive, by due date."""
    horizon = today + timedelta(days=days)
    due = [
        o
        for o in obligations
        if o.get("due_date") is not None and today <= o["due_date"] <= horizon
    ]
    return sorted(due, key=lambda o: o["due_date"])
