"""Contract Register: filterable list, contract detail, version diff, delete."""


import streamlit as st

from core.diff import diff_clauses, diff_stats
from core.missing import contract_types
from storage import models
from storage.db import STATUSES
from ui.components import (
    md_escape,
    empty_state,
    fmt_date,
    fmt_money,
    page_header,
    status_badge,
)
from ui.state import get_conn

if page_header(
    "Contract Register",
    "Every contract you have reviewed, with its status and key dates.",
    "Review a contract",
    ":material/add:",
):
    st.switch_page("ui/pages/review.py")

conn = get_conn()
TYPES = contract_types()


def _open_contract(contract_id: str) -> None:
    st.query_params["contract"] = contract_id


def _close_contract() -> None:
    st.query_params.pop("contract", None)


def _parties_text(contract: dict, limit: int = 60) -> str:
    names = [p["name"] for p in contract.get("parties") or []]
    text = ", ".join(names)
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + " ..."
    return text


def _diff_html(rows: list[dict]) -> str:
    """Side-by-side diff cards. old_html/new_html from core.diff are already escaped."""
    out = []
    for row in rows:
        status = row["status"]
        if status == "same":
            old_cls = new_cls = "diff-cell"
        elif status == "added":
            old_cls, new_cls = "diff-cell", "diff-cell diff-added"
        elif status == "removed":
            old_cls, new_cls = "diff-cell diff-removed", "diff-cell"
        else:
            old_cls = new_cls = "diff-cell diff-changed"
        old_body = row["old_html"] or '<span style="color:#9AA4BF">Not in this version</span>'
        new_body = row["new_html"] or '<span style="color:#9AA4BF">Not in this version</span>'
        out.append(
            '<div class="diff-row">'
            f'<div class="{old_cls}">{old_body}</div>'
            f'<div class="{new_cls}">{new_body}</div>'
            "</div>"
        )
    return "".join(out)


@st.dialog("Delete contract")
def _confirm_delete(contract_id: str, title: str) -> None:
    st.warning(
        f"This removes **{md_escape(title)}** and every version, finding and note "
        "permanently from this computer. This cannot be undone."
    )
    cancel, delete = st.columns(2)
    with cancel:
        if st.button("Cancel", width="stretch"):
            st.rerun()
    with delete:
        if st.button("Delete permanently", type="primary", width="stretch"):
            models.delete_contract(conn, contract_id)
            # Cached analyses may reference versions that no longer exist.
            st.cache_data.clear()
            _close_contract()
            st.toast("Contract deleted", icon=":material/delete:")
            st.rerun()


def _detail(contract_id: str) -> None:
    contract = models.get_contract(conn, contract_id)
    if contract is None:
        _close_contract()
        st.rerun()
    if st.button("Back to register", icon=":material/arrow_back:"):
        _close_contract()
        st.rerun()

    versions = models.list_versions(conn, contract_id)

    with st.container(border=True):
        head, badge = st.columns([1, 0.25], vertical_alignment="center")
        with head:
            st.markdown(f"### {md_escape(contract['title'])}")
            st.caption(TYPES.get(contract["type"], contract["type"]))
        with badge:
            status_badge(contract["status"])
        parties = contract.get("parties") or []
        if parties:
            st.markdown(
                "**Parties:** "
                + "; ".join(
                    md_escape(p["name"]) + (f" (*{md_escape(p['role'])}*)" if p.get("role") else "")
                    for p in parties
                ),
            )
        cols = st.columns(3)
        with cols[0]:
            st.caption(f"Effective: {fmt_date(contract['effective_date'])}")
        with cols[1]:
            st.caption(f"Expiry: {fmt_date(contract['expiry_date'])}")
        with cols[2]:
            st.caption(f"Value: {fmt_money(contract['value_kobo'])}")

        sel, save = st.columns([0.7, 0.3], vertical_alignment="bottom")
        with sel:
            new_status = st.selectbox(
                "Status", STATUSES, index=STATUSES.index(contract["status"])
            )
        with save:
            if st.button("Save", icon=":material/save:", width="stretch"):
                if new_status != contract["status"]:
                    models.update_contract(conn, contract_id, status=new_status)
                    st.toast("Status updated", icon=":material/check:")
                    st.rerun()

    st.subheader("Versions")
    for v in versions:
        reviewed, total = models.review_progress(conn, v["id"])
        with st.container(border=True):
            cols = st.columns([0.15, 0.3, 0.3, 0.25], vertical_alignment="center")
            with cols[0]:
                st.markdown(f"**v{v['version_no']}**")
            with cols[1]:
                st.caption(md_escape(v["filename"]))
            with cols[2]:
                st.caption(f"{fmt_date(v['uploaded_at'])} - {reviewed}/{total} reviewed")
            with cols[3]:
                if st.button(
                    "Open in review",
                    icon=":material/plagiarism:",
                    key=f"open-{v['id']}",
                    type="tertiary",
                ):
                    st.session_state["review_version_id"] = v["id"]
                    st.switch_page("ui/pages/review.py")

    if len(versions) >= 2:
        st.subheader("Compare versions")
        options = {f"Version {v['version_no']} ({v['filename']})": v["id"] for v in versions}
        labels = list(options.keys())
        pick = st.columns(2)
        with pick[0]:
            older = st.selectbox("Older version", labels, index=len(labels) - 2)
        with pick[1]:
            newer = st.selectbox("Newer version", labels, index=len(labels) - 1)
        show_same = st.toggle("Show unchanged clauses", value=False)

        old_version = models.get_version(conn, options[older])
        new_version = models.get_version(conn, options[newer])
        rows = diff_clauses(old_version["clauses"], new_version["clauses"])
        stats = diff_stats(rows)
        badges = st.columns(3)
        with badges[0]:
            st.badge(f"Added: {stats['added']}", color="green")
        with badges[1]:
            st.badge(f"Removed: {stats['removed']}", color="red")
        with badges[2]:
            st.badge(f"Changed: {stats['changed']}", color="orange")
        visible = [r for r in rows if show_same or r["status"] != "same"]
        if visible:
            st.html(_diff_html(visible))
        else:
            st.caption("The two versions are identical.")

    st.subheader("Danger zone")
    if st.button("Delete contract", icon=":material/delete:"):
        _confirm_delete(contract_id, contract["title"])


def _filters() -> dict:
    cols = st.columns(4)
    with cols[0]:
        q = st.text_input("Search titles", placeholder="e.g. supply")
        type_names = st.multiselect("Type", list(TYPES.values()))
    with cols[1]:
        statuses = st.multiselect("Status", list(STATUSES))
        party = st.text_input("Party", placeholder="e.g. Mainland Foods")
    with cols[2]:
        expiring = st.selectbox("Expiring within", ["Any", "30 days", "60 days", "90 days"])
    name_to_id = {v: k for k, v in TYPES.items()}
    return {
        "q": q,
        "type": [name_to_id[n] for n in type_names],
        "status": statuses,
        "party": party,
        "days": None if expiring == "Any" else int(expiring.split()[0]),
    }


def _list() -> None:
    f = _filters()
    rows = models.list_contracts(
        conn, q=f["q"], party=f["party"], expiring_within_days=f["days"]
    )
    # list_contracts matches one type and one status; the multiselects allow several,
    # so those two filters are applied here. An empty selection means "any".
    rows = [
        c
        for c in rows
        if (not f["type"] or c["type"] in f["type"])
        and (not f["status"] or c["status"] in f["status"])
    ]

    st.caption(f"{len(rows)} contract{'s' if len(rows) != 1 else ''}")
    if not rows:
        if any([f["q"], f["type"], f["status"], f["party"], f["days"]]):
            empty_state("No contracts match these filters.")
        else:
            empty_state("No contracts yet. Upload your first contract to begin.")
        return

    head = st.columns([0.24, 0.16, 0.14, 0.24, 0.1, 0.12])
    for col, label in zip(head, ("Title", "Type", "Status", "Parties", "Expiry", "Risk")):
        with col:
            st.caption(label.upper())

    for c in rows:
        with st.container(border=True):
            cols = st.columns([0.24, 0.16, 0.14, 0.24, 0.1, 0.12], vertical_alignment="center")
            with cols[0]:
                if st.button(md_escape(c["title"]), key=f"row-{c['id']}", type="tertiary"):
                    _open_contract(c["id"])
                    st.rerun()
            with cols[1]:
                st.caption(TYPES.get(c["type"], c["type"]))
            with cols[2]:
                status_badge(c["status"])
            with cols[3]:
                st.caption(md_escape(_parties_text(c)))
            with cols[4]:
                st.caption(fmt_date(c["expiry_date"]))
            with cols[5]:
                if c["open_high"] > 0:
                    st.badge(f"{c['open_high']} High", icon=":material/error:", color="red")


contract_id = st.query_params.get("contract")
if contract_id:
    _detail(contract_id)
else:
    _list()
