"""Shared UI components: page header, badges, empty state, finding card."""

import base64
import functools
import html
import re
from datetime import date
from pathlib import Path

import streamlit as st

from core.classify import LABEL_NAMES
from core.money import format_kobo
from storage import models

_INSTITUTIONS_DIR = Path(__file__).resolve().parent.parent / "static" / "institutions"


@functools.lru_cache
def _data_uri(name: str) -> str:
    # Embedded as data URIs so the band renders the same offline, in tests and in screenshots.
    raw = (_INSTITUTIONS_DIR / name).read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def institution_band() -> None:
    """Logos of the two institutions that run the Master's programme this prototype was built for."""
    st.html(
        '<div class="institution-band">'
        '<div class="institution-tile institution-tile--dark">'
        f'<img src="{_data_uri("eu_global.png")}" '
        'alt="European Global Institute of Innovation and Technology"></div>'
        '<div class="institution-tile">'
        f'<img src="{_data_uri("docenti.png")}" alt="Docenti Global Business School"></div>'
        "<p class=\"institution-caption\">Master's capstone prototype, European Global Institute of "
        "Innovation and Technology and Docenti Global Business School</p>"
        "</div>"
    )


# Characters Streamlit's Markdown (CommonMark, GFM, remark-math) treats as syntax.
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|$<>~])")


def md_escape(text) -> str:
    """Backslash-escape Markdown syntax so contract text shows literally.

    WHY: titles, parties and excerpts come from uploaded files. Rendered as
    Markdown, "![](https://...)" would load a remote image and "$" would start
    LaTeX. Use for anything contract-derived going into st.markdown, st.caption,
    st.write, st.warning or a widget label.
    """
    return _MD_SPECIAL.sub(r"\\\1", str(text or ""))


def html_text(text) -> str:
    """Escape text for HTML inside st.markdown(unsafe_allow_html=True).

    WHY: a blank line ends a Markdown HTML block, after which the rest would be
    parsed as Markdown again; <br> keeps the line breaks without a newline.
    """
    return html.escape(str(text or "")).replace("\n", "<br>")


def contract_options(contracts: list[dict]) -> dict[str, str]:
    """{contract id: "Title - First party - 4 Oct 2026"} for contract pickers.

    WHY: contracts can share a title, so pickers are keyed by id and the label
    adds the first party and the created date to tell them apart. Labels that
    still collide get a running number.
    """
    options: dict[str, str] = {}
    seen: dict[str, int] = {}
    for c in contracts:
        parties = c.get("parties") or []
        parts = [c["title"]]
        if parties and parties[0].get("name"):
            parts.append(parties[0]["name"])
        parts.append(fmt_date(c.get("created_at")))
        label = " - ".join(parts)
        seen[label] = seen.get(label, 0) + 1
        options[c["id"]] = label if seen[label] == 1 else f"{label} ({seen[label]})"
    return options


# Severity: always pair the colour with the text label (accessibility).
SEVERITY_COLORS = {
    "High": "red",
    "Medium": "orange",
    "Low": "blue",
    "Pass": "green",
    "Info": "gray",
}
SEVERITY_ICONS = {
    "High": ":material/error:",
    "Medium": ":material/warning:",
    "Low": ":material/info:",
    "Pass": ":material/check_circle:",
    "Info": ":material/label:",
}

STATUS_COLORS = {
    "Draft": "gray",
    "Under Review": "blue",
    "Executed": "violet",
    "Active": "green",
    "Expiring": "orange",
    "Terminated": "red",
}

# Hex mirror of SEVERITY_COLORS for HTML (excerpt borders, highlighter).
SEVERITY_HEX = {
    "High": "#C0392B",
    "Medium": "#D68910",
    "Low": "#2E86C1",
    "Pass": "#1E8449",
    "Info": "#6B7280",
}


def severity_badge(sev: str) -> None:
    st.badge(
        sev,
        icon=SEVERITY_ICONS.get(sev, ":material/label:"),
        color=SEVERITY_COLORS.get(sev, "gray"),
    )


def status_badge(status: str) -> None:
    st.badge(status, color=STATUS_COLORS.get(status, "gray"))


def decision_badge(status: str) -> None:
    """How the reviewer has treated this finding so far."""
    if status == "accepted":
        st.badge("Accepted", icon=":material/check_circle:", color="green")
    elif status == "rejected":
        st.badge("Rejected", icon=":material/cancel:", color="red")
    elif status == "edited":
        st.badge("Edited", icon=":material/edit:", color="blue")
    else:
        st.badge("Suggestion", icon=":material/lightbulb:", color="gray")


def page_header(
    title: str,
    description: str,
    action_label: str | None = None,
    action_icon: str | None = None,
    key: str | None = None,
) -> bool:
    """Title + description left, optional primary action right. Returns True
    when the action button was clicked."""
    left, right = st.columns([1, 0.3], vertical_alignment="center")
    with left:
        st.markdown(
            f'<h1 class="page-title">{html.escape(title)}</h1>'
            f'<p class="page-desc">{html.escape(description)}</p>',
            unsafe_allow_html=True,
        )
    clicked = False
    if action_label:
        with right:
            clicked = st.button(
                action_label,
                icon=action_icon,
                type="primary",
                key=key or f"action-{title}",
                width="stretch",
            )
    st.divider()
    return clicked


def empty_state(message: str, sub: str = "") -> None:
    sub_html = f'<p class="empty-sub">{html.escape(sub)}</p>' if sub else ""
    st.markdown(
        '<div class="empty">'
        '<svg width="40" height="40" viewBox="0 0 24 24">'
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/>'
        '<line x1="9" y1="13" x2="15" y2="13"/>'
        '<line x1="9" y1="17" x2="13" y2="17"/>'
        "</svg>"
        f"<p>{html.escape(message)}</p>{sub_html}</div>",
        unsafe_allow_html=True,
    )


def fmt_date(iso_or_date) -> str:
    """'2026-03-17' -> '17 Mar 2026'; None -> 'Not stated'."""
    if iso_or_date is None:
        return "Not stated"
    if isinstance(iso_or_date, str):
        try:
            d = date.fromisoformat(iso_or_date[:10])
        except ValueError:
            return "Not stated"
    else:
        d = iso_or_date
    return d.strftime("%d %b %Y").lstrip("0")


def fmt_money(kobo) -> str:
    if kobo is None:
        return "Not stated"
    return format_kobo(kobo)


def _decide(
    conn, version_id: str, fid: str, status: str, note: str, edited_text: str | None = None
) -> None:
    """Persist one decision, then confirm and refresh. Only Edit passes
    edited_text, so Accept or Reject after an edit keeps the edited wording."""
    models.set_decision(conn, version_id, fid, status, note=note, edited_text=edited_text)
    st.toast("Decision saved", icon=":material/check:")
    st.rerun()


def finding_card(finding: dict, version_id: str, conn, key_prefix: str, on_focus=None) -> None:
    """One finding with accept / reject / edit / show-in-text actions.

    Every finding is a suggestion; the lawyer decides. Decisions persist via
    models.set_decision so the register and reports see the same state.
    """
    fid = finding["fid"]
    sev = finding["severity"]
    name = finding.get("name") or LABEL_NAMES.get(finding["label"], finding["label"])
    border = SEVERITY_HEX.get(sev, SEVERITY_HEX["Info"])

    with st.container(border=True):
        st.markdown(f'<p class="finding-head">{html.escape(name)}</p>', unsafe_allow_html=True)
        # Flex rows size to their content, so badges and buttons never truncate in a narrow pane.
        with st.container(horizontal=True, gap="small"):
            severity_badge(sev)
            decision_badge(finding.get("status", "suggested"))

        st.markdown(
            f'<p class="finding-reason">{html_text(finding["reason"])}</p>',
            unsafe_allow_html=True,
        )

        if finding.get("excerpt"):
            st.markdown(
                f'<div class="finding-excerpt" style="border-left-color:{border}">'
                f'{html_text(finding["excerpt"])}</div>',
                unsafe_allow_html=True,
            )

        if finding["kind"] == "obligation":
            if finding.get("party"):
                st.caption(f"Party: {md_escape(finding['party'])}")
            st.caption(f"Due: {fmt_date(finding.get('due_date'))}")

        note_key = f"{key_prefix}-{fid}-note"
        note = st.text_input(
            "Note",
            value=finding.get("note", ""),
            placeholder="Add a note for the file",
            label_visibility="collapsed",
            key=note_key,
        )

        show_jump = finding.get("char_start") is not None
        with st.container(horizontal=True, gap="small"):
            if st.button("Accept", icon=":material/check:", key=f"{key_prefix}-{fid}-ok"):
                _decide(conn, version_id, fid, "accepted", note)
            if st.button("Reject", icon=":material/close:", key=f"{key_prefix}-{fid}-no"):
                _decide(conn, version_id, fid, "rejected", note)
            with st.popover("Edit", icon=":material/edit:"):
                edited = st.text_area(
                    "Your corrected text",
                    value=finding.get("edited_text") or finding.get("excerpt", ""),
                    key=f"{key_prefix}-{fid}-edit",
                )
                if st.button("Save edit", icon=":material/save:", key=f"{key_prefix}-{fid}-save"):
                    _decide(conn, version_id, fid, "edited", note, edited)
            if show_jump and st.button(
                "Show in text",
                icon=":material/my_location:",
                type="tertiary",
                key=f"{key_prefix}-{fid}-jump",
            ):
                st.session_state["focus_fid"] = fid
                if on_focus is not None:
                    on_focus(fid)
                st.rerun()
