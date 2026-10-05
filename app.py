"""LexReview NG entry point: page chrome, sidebar, navigation.

Run with: streamlit run app.py
"""

from pathlib import Path

import streamlit as st

from ui.login import logout_button, require_login

st.set_page_config(
    page_title="LexReview NG",
    page_icon="static/logo_icon.svg",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Single stylesheet for the whole app (st.html accepts a Path to a .css file).
st.html(Path("assets/styles.css"))
st.logo("static/logo.svg", icon_image="static/logo_icon.svg", size="large")

pg = st.navigation(
    [
        st.Page("ui/pages/dashboard.py", title="Dashboard", icon=":material/space_dashboard:", default=True),
        st.Page("ui/pages/review.py", title="Review a Contract", icon=":material/plagiarism:"),
        st.Page("ui/pages/register.py", title="Contract Register", icon=":material/folder_open:"),
        st.Page("ui/pages/deadlines.py", title="Deadlines", icon=":material/event:"),
        st.Page("ui/pages/search.py", title="Search", icon=":material/search:"),
        st.Page("ui/pages/reports.py", title="Reports", icon=":material/description:"),
        st.Page("ui/pages/settings.py", title="Settings", icon=":material/settings:"),
    ]
)

with st.sidebar:
    # Everything runs on this machine; the badge reassures the lawyer of that.
    st.markdown(
        '<div class="local-badge">'
        '<svg width="14" height="14" viewBox="0 0 24 24">'
        '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'
        '<polyline points="9 12 11 14 15 10"/>'
        "</svg>"
        "<span>Runs locally. Your documents never leave this computer.</span>"
        "</div>"
        '<p class="sidebar-disclaimer">Assists contract review. '
        "Does not give legal advice.</p>",
        unsafe_allow_html=True,
    )

# Optional lock screen; does nothing unless a password is set and switched on in Settings.
require_login()
logout_button()

pg.run()
