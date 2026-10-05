"""Render contract text with clauses, severity outlines and finding marks.

Returns a full HTML document for streamlit.components.v1.html. Every
contract-derived string is html.escape()d before it reaches the page.
"""

import html

from core.classify import LABEL_NAMES

# Severity hex colours mirror the design palette; severity is always paired
# with a text label in the legend.
SEVERITY_HEX = {
    "High": "#C0392B",
    "Medium": "#D68910",
    "Low": "#2E86C1",
    "Pass": "#1E8449",
    "Info": "#6B7280",
}
_SEVERITY_RANK = {"High": 3, "Medium": 2, "Low": 1}

# Soft tint per clause label for the 4px left border. Labels not listed fall
# back to "other". Tints are decorative only; meaning is carried by the chip.
LABEL_TINTS = {
    "parties": "#94A3B8",
    "definitions": "#8E7CC3",
    "purpose": "#7BA6C9",
    "scope_of_work": "#5B8DB8",
    "supply": "#5B8DB8",
    "term": "#6B9E8F",
    "payment": "#B8963E",
    "rent": "#B8963E",
    "interest": "#C9A25E",
    "repayment": "#C9A25E",
    "delivery": "#7BA6C9",
    "warranties": "#7C93B8",
    "indemnity": "#C9827A",
    "liability": "#C9827A",
    "termination": "#C0392B",
    "confidentiality": "#8E7CC3",
    "non_compete": "#A98BC0",
    "intellectual_property": "#9E8BC0",
    "data_protection": "#6B9EB8",
    "governing_law": "#1E2A44",
    "dispute_resolution": "#55617E",
    "force_majeure": "#8FA3B8",
    "notices": "#A3B1C6",
    "general": "#B9C2D0",
    "other": "#D3D9E2",
}


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _segments(char_start: int, char_end: int, marks: list[dict]):
    """Split [char_start, char_end) at every mark boundary; each piece gets
    the worst severity covering it. Returns (offset, end, sev, first_fids)."""
    boundaries = {char_start, char_end}
    for mark in marks:
        boundaries.add(max(mark["char_start"], char_start))
        boundaries.add(min(mark["char_end"], char_end))
    points = sorted(boundaries)
    out = []
    for a, b in zip(points, points[1:]):
        if a >= b:
            continue
        covering = [
            m for m in marks
            if m["char_start"] <= a and m["char_end"] >= b
        ]
        sev = None
        fids = []
        if covering:
            worst = max(covering, key=lambda m: _SEVERITY_RANK.get(m["severity"], 0))
            sev = worst["severity"]
            # Anchors whose mark starts inside this piece (worst first, so the
            # scroll target of a finding always exists exactly once overall).
            fids = [m["fid"] for m in sorted(
                (m for m in covering if m["char_start"] == a or (a == char_start and m["char_start"] <= a)),
                key=lambda m: -_SEVERITY_RANK.get(m["severity"], 0),
            )]
        out.append((a, b, sev, fids))
    return out


def render_contract_html(text, clauses, labels, findings, focus_fid=None, height_px=720) -> str:
    """Full HTML document: legend, tinted clauses, severity marks, anchors."""
    # Marks are findings with real offsets; everything else stays card-only.
    located = [f for f in findings if f.get("char_start") is not None]
    marks_by_fid = {f["fid"]: f for f in located}
    # A clause finding covers its whole clause; painting it would tint every line, so it
    # only gets an anchor at the clause start (the clause border already shows its type).
    all_marks = [f for f in located if f["kind"] != "clause"]
    clause_anchors = {f["clause_seq"]: f["fid"] for f in located if f["kind"] == "clause"}
    focus = focus_fid if focus_fid in marks_by_fid else None

    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>",
        "body{font-family:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;",
        "font-size:14px;line-height:1.7;color:#1F2937;background:#FFFFFF;padding:24px;margin:0;}",
        ".legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:#6B7280;",
        "border-bottom:1px solid #E5E7EB;padding-bottom:12px;margin-bottom:16px;}",
        ".legend span{display:inline-flex;align-items:center;gap:6px;}",
        ".dot{width:10px;height:10px;border-radius:50%;display:inline-block;}",
        "section.clause{border-left:4px solid #E5E7EB;border-radius:0 6px 6px 0;",
        "padding:10px 14px;margin:0 0 12px 0;white-space:pre-wrap;position:relative;}",
        ".chip{float:right;font-size:11px;color:#6B7280;background:#F7F8FA;",
        "border:1px solid #E5E7EB;border-radius:999px;padding:1px 10px;margin-left:8px;}",
        "mark{border-radius:3px;padding:0 1px;color:inherit;}",
        "mark.soft{background:transparent;border-bottom:1.5px dotted #6B7280;border-radius:0;}",
        "section.focus{animation:pulse 2s ease-out 1;}",
        "@keyframes pulse{0%{outline:2px solid #B8963E}100%{outline:2px solid transparent}}",
        "mark.focus{animation:pulse 2s ease-out 1;outline:2px solid transparent}",
        "@media (prefers-reduced-motion: reduce){mark.focus{animation:none;outline:2px solid #B8963E}}",
        "</style></head><body>",
        # Legend: colour AND text label together.
        "<div class='legend'>" + "".join(
            f"<span><i class='dot' style='background:{SEVERITY_HEX[s]}'></i>{s}</span>"
            for s in ("High", "Medium", "Low")
        ) + "<span><i class='dot' style='background:#D3D9E2'></i>Clause tint by type</span></div>",
    ]

    for clause, label in zip(clauses, labels):
        c_start, c_end = clause.char_start, clause.char_end
        # Severity outline on clauses that contain a risk/missing/compliance hit.
        outline_sev = None
        for f in findings:
            if f.get("clause_seq") == clause.seq and f["kind"] in ("risk", "missing", "compliance"):
                if _SEVERITY_RANK.get(f["severity"], 0) > _SEVERITY_RANK.get(outline_sev or "", 0):
                    outline_sev = f["severity"]
        tint = LABEL_TINTS.get(label, LABEL_TINTS["other"])
        style = f"border-left-color:{tint};"
        if outline_sev:
            style += f"outline:2px solid {SEVERITY_HEX[outline_sev]};outline-offset:1px;"
        chip = f"<span class='chip'>{_esc(LABEL_NAMES.get(label, label))}</span>"

        clause_marks = [
            m for m in all_marks
            if m["char_end"] > c_start and m["char_start"] < c_end
        ]
        body = []
        for a, b, sev, starts in _segments(c_start, c_end, clause_marks):
            anchors = "".join(f"<span id='f-{_esc(fid)}'></span>" for fid in starts)
            piece = _esc(text[a:b])
            if sev in ("High", "Medium", "Low"):
                # 2E hex suffix = about 18% opacity of the severity colour.
                body.append(f"{anchors}<mark style='background:{SEVERITY_HEX[sev]}2E'>{piece}</mark>")
            elif sev:
                # Obligations and passed checks: a quiet dotted underline, not a colour block.
                body.append(f"{anchors}<mark class='soft'>{piece}</mark>")
            else:
                body.append(anchors + piece)
        lead = ""
        if clause.seq in clause_anchors:
            lead = f"<span id='f-{_esc(clause_anchors[clause.seq])}'></span>"
        parts.append(f"<section class='clause' style='{style}'>{lead}{chip}{''.join(body)}</section>")

    if focus:
        fid = focus
        parts.append(
            "<script>"
            f"var el=document.getElementById('f-{fid}');"
            "if(el){el.scrollIntoView({block:'center'});"
            "var mk=el.nextElementSibling;"
            # Findings that start at the same offset stack their anchors before one
            # shared mark; step over the other anchors (never the clause chip).
            "while(mk&&mk.tagName==='SPAN'&&mk.id.indexOf('f-')===0){mk=mk.nextElementSibling;}"
            "if(mk&&mk.tagName==='MARK'){mk.classList.add('focus');}"
            "else{el.parentElement.classList.add('focus');}}"
            "</script>"
        )

    parts.append("</body></html>")
    return "".join(parts)
