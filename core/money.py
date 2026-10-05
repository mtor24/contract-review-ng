"""Naira money handling: money is INTEGER kobo plus currency "NGN".

Floats are never used for money; "N18,000,000" is 1_800_000_000 kobo.
"""

import re

_MULTIPLIERS = {"million": 10**6, "billion": 10**9, "bn": 10**9}

# "N18,000,000", "NGN 5,000", "N1,250.50", "₦18,000,000", "N2.5 billion".
# WHY the lookbehind: the N must not end a word, so registration numbers
# such as "TIN12345678" or "BN 1234567" are not read as amounts.
_AMOUNT_RE = re.compile(
    r"(?<![A-Za-z])(?:NGN\s?|N|₦\s?)"
    r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?"
    r"(?:\s?((?i:million|billion|bn))\b)?"
)


def _to_kobo(m: re.Match) -> int:
    """Integer-only conversion: "2.5" billion is 25 * 10**9 / 10, never a float."""
    whole = m.group(1).replace(",", "")
    frac = m.group(2) or ""
    mult = _MULTIPLIERS[m.group(3).lower()] if m.group(3) else 1
    # ponytail: fractions of a kobo (e.g. "N1.255") are truncated.
    return int(whole + frac) * 100 * mult // 10 ** len(frac)


def parse_naira(s: str) -> int:
    """Parse a naira string like "N18,000,000" or "N1,250.50" into kobo."""
    m = _AMOUNT_RE.search(s)
    if not m:
        raise ValueError(f"Not a naira amount: {s!r}")
    return _to_kobo(m)


def find_amounts(text: str) -> list[tuple[int, int, int]]:
    """Return (kobo, char_start, char_end) for every naira amount in text."""
    return [(_to_kobo(m), m.start(), m.end()) for m in _AMOUNT_RE.finditer(text)]


def format_kobo(kobo: int) -> str:
    """Format kobo as "N18,000,000.00"."""
    naira, rem = divmod(kobo, 100)
    return f"N{naira:,}.{rem:02d}"
