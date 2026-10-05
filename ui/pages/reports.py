"""Reports: preview a review report and export it as PDF or Word."""

import html
import re

import streamlit as st

from core import report as report_lib
from storage import models
from ui.components import contract_options, empty_state, md_escape, page_header
from ui.state import analysis_for, get_conn, load_config

page_header(
    "Reports",
    "Preview and export a review report with your decisions.",
)

conn = get_conn()

contracts = models.list_contracts(conn)
if not contracts:
    empty_state("No contracts yet. Review a contract to build its report.")
    st.stop()

# Keyed by id: two contracts can share a title and both must stay exportable.
options = contract_options(contracts)
pick = st.columns(2)
with pick[0]:
    contract_id = st.selectbox("Contract", list(options), format_func=options.get)
contract = models.get_contract(conn, contract_id)
versions = models.list_versions(conn, contract["id"])
with pick[1]:
    version_no = st.selectbox(
        "Version", [v["version_no"] for v in versions], index=len(versions) - 1
    )
version_row = next(v for v in versions if v["version_no"] == version_no)
version = models.get_version(conn, version_row["id"])

summary = analysis_for(version["id"], version["text"], contract["type"])["summary"]
data = report_lib.build_report_data(
    contract, version, summary, load_config().get("firm_name", "")
)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    """Compact HTML table; every cell is escaped contract text."""
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return (
        '<table style="width:100%;border-collapse:collapse;font-size:13px">'
        f'<thead><tr style="text-align:left;border-bottom:1px solid #E5E7EB">{head}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def _section(name: str) -> None:
    st.markdown(f"**{name}**")


with st.container(border=True):
    cover = data["cover"]
    st.markdown(f"### {md_escape(cover['firm_name'] or 'Firm')}")
    st.markdown(f"## {md_escape(cover['title'])}")
    st.caption(
        f"Contract Review Report - {md_escape(cover['contract_type'])} - "
        f"Version {cover['version_no']} - generated {cover['generated']}"
    )
    if cover["parties"]:
        st.caption(f"Parties: {md_escape(cover['parties'])}")
    if cover["value_text"]:
        st.caption(f"Contract value: {md_escape(cover['value_text'])}")
    st.info(data["disclaimer"])

    s = data["summary"]
    _section("Summary")
    summary_rows = [
        (label, s[key])
        for label, key in (
            ("Agreement date", "agreement_date"),
            ("Effective date", "effective_date"),
            ("Expiry date", "expiry_date"),
            ("Contract value", "value_text"),
            ("Term", "term_text"),
        )
        if s.get(key)
    ]
    if summary_rows:
        st.html(_table(["Field", "Value"], summary_rows))
    if s.get("key_terms"):
        st.html(_table(["Key term", "Sentence"],
                       [(t["name"], t["sentence"]) for t in s["key_terms"]]))

    _section("Clauses identified")
    if data["clauses"]:
        st.html(_table(["No.", "Heading", "Type"],
                       [(c["number"], c["heading"], c["label_name"]) for c in data["clauses"]]))
    else:
        st.caption("No clauses identified.")

    _section("Missing clauses")
    if data["missing"]:
        st.html(_table(["Clause", "Severity", "Reason"],
                       [(f.get("name") or f["label"], f["severity"], f["reason"])
                        for f in data["missing"]]))
    else:
        st.caption("No missing clauses detected.")

    _section("Risks")
    if data["risks"]:
        st.html(_table(["Severity", "Risk", "Why it matters", "Status"],
                       [(f["severity"], f.get("name") or f["label"], f["reason"], f["status"])
                        for f in data["risks"]]))
    else:
        st.caption("No risks detected.")

    _section("Nigerian compliance (indicative)")
    if data["compliance"]:
        st.html(_table(["Check", "Result", "Detail"],
                       [(f.get("name") or f["label"], f["severity"], f["reason"])
                        for f in data["compliance"]]))
    else:
        st.caption("No compliance checks applied.")

    _section("Obligations and deadlines")
    if data["obligations"]:
        st.html(_table(["Party", "Period", "Due date", "Obligation"],
                       [(o["party"], o["period"], o["due_date"], o["excerpt"])
                        for o in data["obligations"]]))
    else:
        st.caption("No obligations detected.")

    _section("Lawyer decisions")
    counts = data["decision_counts"]
    st.caption(
        f"{counts['reviewed']} of {counts['total']} findings reviewed. "
        f"{counts['awaiting']} still awaiting review."
    )
    if data["decisions"]:
        st.html(_table(["Type", "Finding", "Severity", "Decision", "Note / edited text"],
                       [(d["kind"], d["name"], d["severity"], d["status"],
                         (d["note"] + " " + d["edited_text"]).strip())
                        for d in data["decisions"]]))
    else:
        st.caption("No decisions recorded yet.")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _exported(kind: str, contract_id: str) -> None:
    st.toast("Report exported", icon=":material/download:")
    models.log(conn, f"Exported {kind} report", contract_id)
    conn.commit()


base = f"{_slug(contract['title'])}-v{version['version_no']}-review"
cols = st.columns(2)
with cols[0]:
    st.download_button(
        "Export PDF",
        data=report_lib.to_pdf(data),
        file_name=f"{base}.pdf",
        mime="application/pdf",
        icon=":material/picture_as_pdf:",
        on_click=_exported,
        args=("PDF", contract["id"]),
        width="stretch",
    )
with cols[1]:
    st.download_button(
        "Export Word",
        data=report_lib.to_docx(data),
        file_name=f"{base}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        icon=":material/article:",
        on_click=_exported,
        args=("Word", contract["id"]),
        width="stretch",
    )
