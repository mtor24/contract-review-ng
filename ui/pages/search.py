"""Search: full-text search across every stored contract version."""

import html

import streamlit as st

from storage import models
from ui.components import empty_state, md_escape, page_header
from ui.state import get_conn

page_header(
    "Search",
    "Find words and phrases across every stored contract.",
)

conn = get_conn()

query = st.text_input(
    "Search",
    placeholder="e.g. indemnify, arbitration, personal data",
    label_visibility="collapsed",
)
submitted = st.button("Search", icon=":material/search:", type="primary", key="search-btn")

if not submitted or not query.strip():
    st.stop()

results = models.search(conn, query)
if not results:
    empty_state("No matches. Try a shorter word or a different spelling.")
    st.stop()

st.caption(f"{len(results)} result{'s' if len(results) != 1 else ''}")
for r in results:
    with st.container(border=True):
        top, badge = st.columns([0.85, 0.15], vertical_alignment="center")
        with top:
            if st.button(md_escape(r["contract_title"]), key=f"s-{r['version_id']}", type="tertiary"):
                st.switch_page(
                    "ui/pages/register.py", query_params={"contract": r["contract_id"]}
                )
        with badge:
            st.badge(f"v{r['version_no']}", color="gray")
        # FTS marks hits with control characters that never occur in a contract; escape the
        # text first, then turn only those markers into <mark>, so literal brackets such as
        # "[insert date]" stay text and contract text can never become markup.
        snippet = (
            html.escape(r["snippet"])
            .replace(models.SNIPPET_START, "<mark>")
            .replace(models.SNIPPET_END, "</mark>")
        )
        st.html(f'<p class="finding-excerpt">{snippet}</p>')
