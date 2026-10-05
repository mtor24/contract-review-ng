"""Optional lock screen. Off by default; switched on from Settings once a password is set."""

import time

import streamlit as st

from core.auth import MIN_LENGTH, hash_password, verify_password
from ui.state import load_config, save_config

MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 30


@st.cache_resource
def _attempts() -> dict:
    # One counter for the whole app process, not per browser tab, so opening a new tab
    # does not reset the lockout.
    return {"failures": 0, "locked_until": 0.0}


def login_enabled(cfg: dict) -> bool:
    # Fail open only when no password exists, so a half-configured lock never locks the owner out.
    return bool(cfg.get("features", {}).get("login_enabled")) and bool(cfg.get("auth"))


def require_login() -> None:
    """Stop the page here until the right password is entered."""
    cfg = load_config()
    if not login_enabled(cfg) or st.session_state.get("authenticated"):
        return

    st.html('<div class="page-title">Sign in</div>'
            '<div class="page-desc">This copy of LexReview NG is password protected.</div>')
    attempts = _attempts()
    with st.form("login", border=True):
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary", icon=":material/lock_open:")
    if submitted:
        if time.time() < attempts["locked_until"]:
            wait = int(attempts["locked_until"] - time.time()) + 1
            st.error(f"Too many attempts. Wait {wait} seconds and try again.")
        elif verify_password(password, cfg.get("auth")):
            st.session_state["authenticated"] = True
            attempts["failures"] = 0
            st.rerun()
        else:
            # A short lockout makes guessing slow without needing any server-side store.
            attempts["failures"] += 1
            if attempts["failures"] >= MAX_ATTEMPTS:
                attempts["locked_until"] = time.time() + LOCKOUT_SECONDS
                attempts["failures"] = 0
            st.error("That password is not correct.")
    st.stop()


def logout_button() -> None:
    if login_enabled(load_config()) and st.session_state.get("authenticated"):
        if st.sidebar.button("Sign out", icon=":material/logout:", type="tertiary"):
            st.session_state["authenticated"] = False
            st.rerun()


def password_settings() -> None:
    """Settings section: set or change the password and turn the lock on or off."""
    cfg = load_config()
    has_password = bool(cfg.get("auth"))
    with st.container(border=True):
        st.subheader("Sign-in")
        st.caption("Protect this copy with a password. Only a salted scrypt hash of it is stored, "
                   "in data/local_config.yaml on this computer.")
        with st.form("set_password", border=False):
            new = st.text_input("New password", type="password", help=f"At least {MIN_LENGTH} characters.")
            confirm = st.text_input("Confirm new password", type="password")
            if st.form_submit_button("Save password", icon=":material/key:"):
                if new != confirm:
                    st.error("The two passwords do not match.")
                else:
                    try:
                        cfg["auth"] = hash_password(new)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        save_config(cfg)
                        st.session_state["authenticated"] = True
                        st.toast("Password saved", icon=":material/check:")
                        has_password = True
        enabled = st.toggle("Require the password when the app opens",
                            value=login_enabled(cfg), disabled=not has_password)
        if has_password and enabled != login_enabled(cfg):
            cfg.setdefault("features", {})["login_enabled"] = enabled
            save_config(cfg)
            st.toast("Sign-in turned " + ("on" if enabled else "off"), icon=":material/check:")
