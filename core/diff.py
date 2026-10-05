"""Clause-level version diff: align two clause lists and mark added, removed,
changed and same clauses, with word-level highlight HTML for changed rows.

Contract text is untrusted input, so every character that reaches the HTML
output passes through html.escape first; the <del>/<ins> wrappers are added
after escaping.
"""

import difflib
import html
import re

_WS_RE = re.compile(r"\s+")


def _normalise(s: str) -> str:
    return _WS_RE.sub(" ", s.lower()).strip()


def _key(clause: dict) -> str:
    """Alignment key: clause number, else heading, else first 40 chars."""
    number = (clause.get("number") or "").strip()
    if number:
        return "n:" + _normalise(number)
    heading = (clause.get("heading") or "").strip()
    if heading:
        return "h:" + _normalise(heading)
    return "t:" + _normalise(clause.get("text") or "")[:40]


def _highlight(old_text: str, new_text: str) -> tuple[str, str]:
    """Word-level diff HTML for one changed pair.

    Tokens are escaped before wrapping, so markup in the contract text can
    never become real HTML.
    """
    old_tokens = old_text.split()
    new_tokens = new_text.split()
    matcher = difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
    old_parts: list[str] = []
    new_parts: list[str] = []
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        old_chunk = " ".join(html.escape(t) for t in old_tokens[a0:a1])
        new_chunk = " ".join(html.escape(t) for t in new_tokens[b0:b1])
        if tag == "equal":
            if old_chunk:
                old_parts.append(old_chunk)
            if new_chunk:
                new_parts.append(new_chunk)
        elif tag == "delete":
            if old_chunk:
                old_parts.append(f'<del class="diff-del">{old_chunk}</del>')
        elif tag == "insert":
            if new_chunk:
                new_parts.append(f'<ins class="diff-ins">{new_chunk}</ins>')
        else:  # replace
            if old_chunk:
                old_parts.append(f'<del class="diff-del">{old_chunk}</del>')
            if new_chunk:
                new_parts.append(f'<ins class="diff-ins">{new_chunk}</ins>')
    return " ".join(old_parts), " ".join(new_parts)


def _row(status: str, old: dict | None, new: dict | None) -> dict:
    old_html, new_html = "", ""
    if status == "changed":
        old_html, new_html = _highlight(old["text"] or "", new["text"] or "")
    elif status == "same":
        old_html = new_html = html.escape(new["text"] or "")
    elif status == "removed":
        old_html = html.escape(old["text"] or "")
    elif status == "added":
        new_html = html.escape(new["text"] or "")
    return {
        "status": status,
        "old": old,
        "new": new,
        "old_html": old_html,
        "new_html": new_html,
    }


def diff_clauses(old: list[dict], new: list[dict]) -> list[dict]:
    """Align two clause lists (as returned by get_version()["clauses"]) and
    return one row per aligned pair or unmatched clause."""
    old_keys = [_key(c) for c in old]
    new_keys = [_key(c) for c in new]
    matcher = difflib.SequenceMatcher(None, old_keys, new_keys, autojunk=False)

    rows: list[dict] = []
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(a0, a1), range(b0, b1)):
                if (old[i].get("text") or "") == (new[j].get("text") or ""):
                    rows.append(_row("same", old[i], new[j]))
                else:
                    rows.append(_row("changed", old[i], new[j]))
        elif tag == "delete":
            for i in range(a0, a1):
                rows.append(_row("removed", old[i], None))
        elif tag == "insert":
            for j in range(b0, b1):
                rows.append(_row("added", None, new[j]))
        else:  # replace: pair clauses one to one in order, extras fall out
            old_span = list(range(a0, a1))
            new_span = list(range(b0, b1))
            for i, j in zip(old_span, new_span):
                if (old[i].get("text") or "") == (new[j].get("text") or ""):
                    rows.append(_row("same", old[i], new[j]))
                else:
                    rows.append(_row("changed", old[i], new[j]))
            for i in old_span[len(new_span):]:
                rows.append(_row("removed", old[i], None))
            for j in new_span[len(old_span):]:
                rows.append(_row("added", None, new[j]))
    return rows


def diff_stats(rows: list[dict]) -> dict:
    """Count rows by status."""
    stats = {"added": 0, "removed": 0, "changed": 0, "same": 0}
    for row in rows:
        stats[row["status"]] += 1
    return stats
