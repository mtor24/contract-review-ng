"""Contract text highlighter: escaping, anchors, legend."""

import html

from core.segment import segment
from ui.highlight import render_contract_html


def _finding(fid, severity, start, end, kind="risk"):
    return {
        "fid": fid,
        "kind": kind,
        "label": "other",
        "name": "Test finding",
        "severity": severity,
        "reason": "test",
        "excerpt": "",
        "clause_seq": 0,
        "char_start": start,
        "char_end": end,
    }


def test_contract_text_is_escaped():
    raw = "<script>alert(1)</script>"
    text = f"Intro.\n\n1. PAYMENT\n\nThe fee is {raw} due."
    clauses = segment(text)
    labels = ["other"] * len(clauses)
    out = render_contract_html(text, clauses, labels, [])
    assert raw not in out
    assert html.escape(raw) in out


def test_finding_offsets_get_anchors():
    text = "Intro.\n\n1. PAYMENT\n\nPay the full fee on time."
    clauses = segment(text)
    labels = ["payment"] * len(clauses)
    findings = [
        _finding("risk-0", "High", 25, 35),
        _finding("risk-1", "Low", 30, 40),  # overlapping: must not break output
    ]
    out = render_contract_html(text, clauses, labels, findings)
    assert "id='f-risk-0'" in out
    assert "id='f-risk-1'" in out
    assert out.count("<mark") >= 2


def test_legend_labels_present():
    text = "Only text.\n\n1. TERM\n\nOne year."
    clauses = segment(text)
    out = render_contract_html(text, clauses, ["other"] * len(clauses), [])
    legend = out.split("<div class='legend'>")[1].split("</div>")[0]
    for label in ("High", "Medium", "Low"):
        assert f">{label}<" in legend


def test_focus_fid_emits_scroll_script():
    text = "Intro.\n\n1. TERM\n\nThe term runs for one year."
    clauses = segment(text)
    findings = [_finding("risk-0", "Medium", 20, 30)]
    out = render_contract_html(text, clauses, ["other"] * len(clauses), findings, focus_fid="risk-0")
    assert "scrollIntoView" in out
    assert "f-risk-0" in out.split("<script>")[1]
