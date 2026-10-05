"""Review a Contract: upload, analyse, then work through the findings."""

import streamlit as st
import streamlit.components.v1 as components

from core.segment import Clause
from storage import models
from ui import review_parts
from ui.components import page_header
from ui.highlight import render_contract_html
from ui.state import analysis_for, get_conn, load_config

page_header(
    "Review a Contract",
    "Upload a contract to identify clauses, risks, gaps and deadlines. "
    "Every finding is a suggestion for you to confirm.",
)

conn = get_conn()

# An analysis staged by the upload form runs before anything else renders.
if "pending_review" in st.session_state:
    review_parts.analyse_pending(conn)

version_id = review_parts.resolve_version_id(conn)

if version_id is None:
    review_parts.upload_form(conn)
    st.caption("Assists contract review. Does not give legal advice.")
    st.stop()

version = models.get_version(conn, version_id)
contract = models.get_contract(conn, version["contract_id"])
findings = version["findings"]

if st.button("Review another contract", icon=":material/upload_file:"):
    st.session_state.pop("review_version_id", None)
    st.query_params.pop("version", None)
    st.rerun()

review_parts.header_strip(conn, version, contract)

# Same TF-IDF flag as the upload used, passed explicitly so the cache key follows it.
use_tfidf = bool(load_config()["features"].get("tfidf_fallback", False))
summary = analysis_for(version_id, version["text"], contract["type"], use_tfidf)["summary"]
# .get: older analyses (and older pipelines) have no such key.
if summary.get("segmentation_warning"):
    st.warning(review_parts.SEGMENTATION_WARNING, icon=":material/warning:")

text = version["text"]
# Rebuild Clause objects from the stored rows so offsets match the stored text.
clauses = [
    Clause(
        seq=row["seq"],
        number=row["number"],
        heading=row["heading"],
        text=row["text"],
        char_start=row["char_start"],
        char_end=row["char_end"],
        level=0,
    )
    for row in version["clauses"]
]
labels = [row["label"] for row in version["clauses"]]

left, right = st.columns([11, 10])
with left:
    components.html(
        render_contract_html(
            text,
            clauses,
            labels,
            findings,
            focus_fid=st.session_state.get("focus_fid"),
        ),
        height=760,
        scrolling=True,
    )

with right:
    tabs = st.tabs(review_parts.tab_labels(findings, summary["counts"]))
    with tabs[0]:
        review_parts.summary_tab(summary)
    with tabs[1]:
        review_parts.render_findings_tab(conn, version_id, findings, "clause", "rv-clause")
    with tabs[2]:
        review_parts.render_findings_tab(conn, version_id, findings, "missing", "rv-missing")
    with tabs[3]:
        review_parts.render_findings_tab(conn, version_id, findings, "risk", "rv-risk")
    with tabs[4]:
        review_parts.render_findings_tab(conn, version_id, findings, "compliance", "rv-compl")
    with tabs[5]:
        review_parts.render_findings_tab(conn, version_id, findings, "obligation", "rv-oblig")

st.caption("Assists contract review. Does not give legal advice.")
