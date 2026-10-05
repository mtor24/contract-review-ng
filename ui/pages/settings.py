"""Settings: firm details, analysis options, privacy and data controls."""

import streamlit as st

from storage import models
from storage.db import db_path
from ui.components import page_header
from ui.login import password_settings
from ui.state import get_conn, load_config, load_samples, save_config

page_header("Settings", "Firm details, privacy and data controls.")

cfg = load_config()
conn = get_conn()

with st.container(border=True):
    st.subheader("Firm")
    firm = st.text_input("Firm name", value=cfg["firm_name"])
    if st.button("Save", icon=":material/save:", key="save-firm"):
        cfg["firm_name"] = firm
        save_config(cfg)
        st.toast("Settings saved", icon=":material/check:")

with st.container(border=True):
    st.subheader("Analysis")
    tfidf = st.toggle(
        "Use the optional TF-IDF fallback for clauses the rules cannot label",
        value=cfg["features"]["tfidf_fallback"],
    )
    st.caption(
        "Off by default. When on, a statistical model suggests labels for "
        "clauses no rule matches; it still runs entirely on this computer."
    )
    if tfidf != cfg["features"]["tfidf_fallback"]:
        cfg["features"]["tfidf_fallback"] = tfidf
        save_config(cfg)
        st.toast("Settings saved", icon=":material/check:")

password_settings()

with st.container(border=True):
    st.subheader("Privacy and data")
    st.code(str(db_path()), language=None)
    st.caption(
        "Everything is stored in this one local file. Nothing is sent over "
        "the network and telemetry is off."
    )
    if st.button("Load sample contracts", icon=":material/download:"):
        n = load_samples(conn)
        st.toast(f"Loaded {n} sample contracts", icon=":material/check:")

    st.markdown("**Danger zone**")

    @st.dialog("Delete all data")
    def _confirm_delete():
        st.warning(
            "This permanently deletes every contract, version, finding and "
            "activity record. This cannot be undone."
        )
        typed = st.text_input("Type DELETE to confirm")
        # Checked on click rather than by disabling the button: a text box only commits its
        # value when it loses focus, so a disabled button would need a second click.
        if st.button("Delete everything", type="primary"):
            if typed.strip() != "DELETE":
                st.error("Nothing was deleted. Type DELETE in the box to confirm.")
                return
            models.delete_all_data(conn)
            st.cache_data.clear()
            st.toast("All data deleted", icon=":material/check:")
            st.rerun()

    if st.button("Delete all data", icon=":material/delete_forever:"):
        _confirm_delete()

with st.container(border=True):
    st.subheader("About")
    st.write(
        "LexReview NG reads a contract with rule-based and spaCy pattern "
        "matching: it labels clauses, checks for expected clauses, flags "
        "risky wording, checks Nigerian compliance points and lists dated "
        "obligations. Every finding is a suggestion for a lawyer to accept, "
        "reject or edit. Nothing is decided for you. Assists contract "
        "review. Does not give legal advice."
    )
