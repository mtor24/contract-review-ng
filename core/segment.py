"""Clause segmentation: split contract text into Clause objects by line patterns."""

import re
from dataclasses import dataclass

# "1." starts a top-level clause; "1.1" must not match here (it is level 2).
L1_NUMBERED_RE = re.compile(r"^(\d{1,2})\.\s+(.*)")
# "Clause 3: TERMINATION" and similar keyword-prefixed numbers.
L1_KEYWORD_RE = re.compile(
    r"^(?:Clause|CLAUSE|Article|ARTICLE|Section|SECTION)\s+(\d{1,2})[\s:.\-]+(.*)"
)
L2_RE = re.compile(r"^(\d{1,2}\.\d{1,2})\.?\s+(.*)")
# "(a)", "(i)" etc are list items inside a clause, never clause starts.
LIST_ITEM_RE = re.compile(r"^\([a-zA-Z0-9]+\)")
# Signature blocks and witness lines look like headings but are not clauses.
# Compared against the upper-cased line, so "Signed" and "SIGNED" both match.
SKIP_PREFIXES = (
    "SIGNED",
    "IN WITNESS",
    "THIS AGREEMENT",
    "FOR AND ON BEHALF",
    "NAME:",
    "SIGNATURE",
    "WITNESS",
    "DATE:",
)
# Company-name suffixes appear in signature blocks, not in real headings.
SKIP_SUFFIXES = ("LIMITED", "LTD", "PLC", "NIGERIA")
# Short lower-case words allowed inside a Title Case heading ("Law of the Contract").
TITLE_JOINERS = {"of", "and", "the", "to", "for", "in", "on", "by"}


@dataclass
class Clause:
    seq: int
    number: str | None
    heading: str | None
    text: str
    char_start: int
    char_end: int
    level: int


def _is_party_or_signature_line(line: str) -> bool:
    """Signature-block and party-name lines ("Name: ...", "ACME LIMITED")."""
    upper = line.upper()
    if upper.startswith(SKIP_PREFIXES):
        return True
    # Strip trailing punctuation so "Acme Ltd." still counts as a company name.
    last_word = upper.split()[-1].rstrip(".,;)")
    return last_word.endswith(SKIP_SUFFIXES)


def _is_caps_heading(line: str) -> bool:
    """Detect standalone ALL-CAPS heading lines like "GOVERNING LAW" or "TERM"."""
    # A trailing ":" or "," marks a lead-in line (e.g. "BETWEEN:"), not a heading.
    if not line or len(line) > 60 or line.endswith((",", ":")):
        return False
    words = line.split()
    if not 1 <= len(words) <= 8:
        return False
    letters = [ch for ch in line if ch.isalpha()]
    # One-word headings need >=4 letters so short words like "AND" do not qualify.
    min_letters = 4 if len(words) == 1 else 3
    if len(letters) < min_letters or not all(ch.isupper() for ch in letters):
        return False
    return not _is_party_or_signature_line(line)


def _looks_title_case(line: str) -> bool:
    """Shape test only: "Governing Law", "Payment", "Limitation of Liability"."""
    if not line or len(line) > 50 or line.endswith((".", ":", ",")):
        return False
    words = line.split()
    if not 1 <= len(words) <= 6:
        return False
    letters = [ch for ch in line if ch.isalpha()]
    # ALL CAPS lines belong to _is_caps_heading; if that rule rejected one
    # (e.g. "AND"), this rule must not quietly accept it instead.
    if not letters or all(ch.isupper() for ch in letters):
        return False
    for index, word in enumerate(words):
        first_letter = next((ch for ch in word if ch.isalpha()), None)
        if first_letter is None or first_letter.isupper():
            continue  # numbers and capitalised words are fine
        # A joiner may sit inside a heading but never start it ("and the Buyer").
        if index == 0 or word not in TITLE_JOINERS:
            return False
    return True


def _is_title_case_heading(lines: list[str], i: int) -> bool:
    """Detect un-numbered Title Case headings such as "Dispute Resolution".

    Shape alone is not enough (a person's name is also Title Case), so the
    line must also stand alone: a blank line (or the start of the text)
    before it, and a line of ordinary body text after it.
    """
    line = lines[i].strip()
    if not _looks_title_case(line) or _is_party_or_signature_line(line):
        return False
    if i > 0 and lines[i - 1].strip():
        return False
    following = next((ln.strip() for ln in lines[i + 1 :] if ln.strip()), None)
    if following is None:
        return False
    # Body text reads as prose: another heading-shaped line means this one is
    # part of a block such as an address or a signature, not a heading.
    return not (_looks_title_case(following) or _is_caps_heading(following))


def _heading_candidate(rest: str) -> str | None:
    """Treat the rest of a numbered/keyword line as a heading when it reads like one."""
    rest = rest.strip()
    if not rest or len(rest) > 60:
        return None
    letters = [ch for ch in rest if ch.isalpha()]
    all_caps = letters and all(ch.isupper() for ch in letters)
    # Short lines without a final full stop are headings, not sentences.
    if all_caps or not rest.endswith("."):
        return rest
    return None


def segment(text: str) -> list[Clause]:
    """Split contract text into ordered clauses, tracking character offsets."""
    lines = text.split("\n")
    starts = []  # (line_index, level, number, heading)
    current_l1_heading = None
    # A heading-like first line is the document title ("LEASE AGREEMENT" or
    # "Lease Agreement"), not a clause, so it stays inside the preamble. Only the very first line counts,
    # otherwise a short document's first real heading would be swallowed.
    non_blank_seen = 0

    for i, raw_line in enumerate(lines):
        line = raw_line.lstrip()
        if not line or LIST_ITEM_RE.match(line):
            continue
        non_blank_seen += 1
        m = L2_RE.match(line)
        if m:
            # Level 2 clauses inherit the heading of their enclosing level 1.
            starts.append((i, 2, m.group(1), current_l1_heading))
            continue
        m = L1_NUMBERED_RE.match(line)
        if m:
            heading = _heading_candidate(m.group(2))
            current_l1_heading = heading
            starts.append((i, 1, m.group(1), heading))
            continue
        m = L1_KEYWORD_RE.match(line)
        if m:
            heading = _heading_candidate(m.group(2))
            current_l1_heading = heading
            starts.append((i, 1, m.group(1), heading))
            continue
        if _is_caps_heading(line) or _is_title_case_heading(lines, i):
            if non_blank_seen == 1:
                continue
            heading = line.rstrip()
            current_l1_heading = heading
            starts.append((i, 1, None, heading))

    # Compute each line's offset once so char_start/char_end satisfy the invariant.
    offsets = []
    pos = 0
    for raw_line in lines:
        offsets.append(pos)
        pos += len(raw_line) + 1  # +1 for the "\n" that split() removed

    clauses = []
    # Anything before the first heading is the preamble (seq 0) if it has content.
    first_start = starts[0][0] if starts else len(lines)
    preamble_text = "\n".join(lines[:first_start]).strip()
    if preamble_text:
        # Derive offsets from the line table: text.index is fragile because the
        # same text can appear twice in a document.
        leading_ws = len(lines[0]) - len(lines[0].lstrip())
        preamble_start = offsets[0] + leading_ws
        clauses.append(
            Clause(
                seq=0,
                number=None,
                heading="PREAMBLE",
                text=preamble_text,
                char_start=preamble_start,
                char_end=preamble_start + len(preamble_text),
                level=0,
            )
        )

    for idx, (line_i, level, number, heading) in enumerate(starts):
        body_start = offsets[line_i]
        body_end = offsets[starts[idx + 1][0]] if idx + 1 < len(starts) else len(text)
        body = text[body_start:body_end].rstrip()
        if not body:
            continue
        clauses.append(
            Clause(
                seq=len(clauses),
                number=number,
                heading=heading,
                text=body,
                char_start=body_start,
                char_end=body_start + len(body),
                level=level,
            )
        )

    # seq must be dense 0..n-1 even when empty clauses were skipped.
    for new_seq, clause in enumerate(clauses):
        clause.seq = new_seq
    return clauses
