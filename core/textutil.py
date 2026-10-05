"""Sentence boundary detection for contract text.

Splits text into sentences while protecting legal abbreviations and
monetary amounts from false splits.
"""

import re

# Pre-compiled patterns for efficiency and clarity.
# Protect decimal numbers (e.g., "N1,000.00") from splitting.
_DECIMAL_RE = re.compile(r"\d,\d{3}\.\d{2}|\d\.\d{2}")
# Protect common legal abbreviations from splitting.
_ABBREV_RE = re.compile(r"\b(?:No|Ltd|Cl)\.\s", re.IGNORECASE)
# Sentence terminators: period followed by space, semicolon+space,
# period at end of line, or blank line.
_SPLIT_RE = re.compile(r"(?<=[.;])\s+|(?<=\.)\n|\n\s*\n")


def sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split text[start:end] into sentence spans with absolute offsets.

    Splits after ". ", "; ", ".\n", or a blank line.
    Never splits inside "N1,000.00" or after "No." / "Ltd." / "Cl.".
    Returns spans with leading/trailing whitespace trimmed.
    """
    region = text[start:end]

    # Mask protected sequences so the splitter does not see them.
    protected = _DECIMAL_RE.sub(lambda m: m.group().replace(".", "\x00"), region)
    protected = _ABBREV_RE.sub(
        lambda m: m.group().replace(".", "\x00").replace(" ", "\x01"), protected
    )

    spans = []
    pos = 0
    for match in _SPLIT_RE.finditer(protected):
        span_end = match.start()
        # Include the terminator character in the sentence.
        if span_end < len(protected) and protected[span_end] in ".;":
            span_end += 1
        seg_start, seg_end = pos, span_end
        # Trim whitespace from the edges.
        while seg_start < seg_end and protected[seg_start].isspace():
            seg_start += 1
        while seg_end > seg_start and protected[seg_end - 1].isspace():
            seg_end -= 1
        if seg_start < seg_end:
            spans.append((start + seg_start, start + seg_end))
        pos = match.end()

    # Handle the final segment after the last split point.
    seg_start, seg_end = pos, len(protected)
    while seg_start < seg_end and protected[seg_start].isspace():
        seg_start += 1
    while seg_end > seg_start and protected[seg_end - 1].isspace():
        seg_end -= 1
    if seg_start < seg_end:
        spans.append((start + seg_start, start + seg_end))

    return spans


def sentence_at(text: str, pos: int, clause) -> tuple[int, int]:
    """Return the span of the sentence in clause containing absolute offset pos."""
    spans = sentence_spans(text, clause.char_start, clause.char_end)
    for span in spans:
        if span[0] <= pos < span[1]:
            return span
    # Fallback: return the last span (should not happen in practice).
    return spans[-1] if spans else (clause.char_start, clause.char_end)
