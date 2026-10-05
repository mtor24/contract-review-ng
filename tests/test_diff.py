"""Tests for core.diff: clause alignment and word-level highlight HTML."""

from core.diff import diff_clauses, diff_stats


def _clause(number=None, heading="", text=""):
    return {"number": number, "heading": heading, "text": text}


def test_identical_lists_are_all_same():
    clauses = [
        _clause("1", "TERM", "This agreement runs for one year."),
        _clause("2", "PAYMENT", "The buyer shall pay N1,000,000."),
    ]
    rows = diff_clauses(clauses, [dict(c) for c in clauses])
    assert [r["status"] for r in rows] == ["same", "same"]
    assert diff_stats(rows) == {"added": 0, "removed": 0, "changed": 0, "same": 2}
    for row in rows:
        assert row["old_html"] == row["new_html"]


def test_changed_clause_has_del_and_ins():
    old = [_clause("1", "TERM", "The term is one year.")]
    new = [_clause("1", "TERM", "The term is two years.")]
    rows = diff_clauses(old, new)
    assert [r["status"] for r in rows] == ["changed"]
    row = rows[0]
    assert '<del class="diff-del">' in row["old_html"]
    assert '<ins class="diff-ins">' in row["new_html"]
    assert "one" in row["old_html"]
    assert "two" in row["new_html"]
    assert diff_stats(rows)["changed"] == 1


def test_added_and_removed_clauses_detected():
    old = [
        _clause("1", "TERM", "The term is one year."),
        _clause("2", "PAYMENT", "Payment is due monthly."),
        _clause("3", "TERMINATION", "Either party may terminate."),
        _clause("4", "GOVERNING LAW", "This agreement is governed by Nigerian law."),
        _clause("5", "NOTICES", "Notices must be in writing."),
    ]
    new = [
        _clause("1", "TERM", "The term is one year."),
        _clause("2", "PAYMENT", "Payment is due monthly."),
        _clause("4", "GOVERNING LAW", "This agreement is governed by Nigerian law."),
        _clause("5", "NOTICES", "Notices must be in writing."),
        _clause("6", "DISPUTES", "Disputes go to arbitration."),
    ]
    rows = diff_clauses(old, new)
    statuses = [r["status"] for r in rows]
    assert "added" in statuses
    assert "removed" in statuses
    stats = diff_stats(rows)
    assert stats["added"] == 1
    assert stats["removed"] == 1
    assert stats["same"] == 4


def test_script_text_is_escaped_everywhere():
    evil = _clause("1", "TERM", "The <script>alert(1)</script> clause.")
    changed = _clause("1", "TERM", "The <script>alert(2)</script> clause.")
    added = _clause("9", "NEW", "<script>alert(3)</script>")

    # changed row
    rows = diff_clauses([evil], [changed])
    assert "<script>" not in rows[0]["old_html"]
    assert "<script>" not in rows[0]["new_html"]
    assert "&lt;script&gt;" in rows[0]["old_html"]

    # same row
    rows = diff_clauses([evil], [dict(evil)])
    assert "<script>" not in rows[0]["old_html"]
    assert "&lt;script&gt;" in rows[0]["old_html"]

    # removed row
    rows = diff_clauses([evil], [])
    assert "<script>" not in rows[0]["old_html"]
    assert "&lt;script&gt;" in rows[0]["old_html"]

    # added row
    rows = diff_clauses([], [added])
    assert "<script>" not in rows[0]["new_html"]
    assert "&lt;script&gt;" in rows[0]["new_html"]


def test_supply_agreement_v2_diff(samples_dir):
    """The negotiated v2 sample must diff against v1 with real changes."""
    from core.segment import segment

    old_text = (samples_dir / "supply_agreement.txt").read_text(encoding="utf-8")
    new_text = (samples_dir / "versions" / "supply_agreement_v2.txt").read_text(encoding="utf-8")

    def clause_dicts(text):
        return [
            {"number": c.number, "heading": c.heading, "text": c.text}
            for c in segment(text)
        ]

    rows = diff_clauses(clause_dicts(old_text), clause_dicts(new_text))
    stats = diff_stats(rows)
    assert stats["changed"] >= 3
    assert stats["added"] >= 1
