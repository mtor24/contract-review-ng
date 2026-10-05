"""Shared app state: database, config.yaml, cached analysis, sample loading."""

import streamlit as st
import yaml

from core.pipeline import analyse
from storage.db import connect
from storage.models import list_contracts, save_analysis

import os

CONFIG_PATH = "config.yaml"
SAMPLES_DIR = "data/samples"

_DEFAULT_CONFIG = {
    "firm_name": "Your Firm Name",
    "features": {"tfidf_fallback": False, "login_enabled": False},
}


def local_config_path() -> str:
    # Changes made on the Settings page (including the password hash) go to a separate,
    # git-ignored file, so the committed config.yaml only ever holds safe defaults.
    return os.environ.get("LEXREVIEW_LOCAL_CONFIG", "data/local_config.yaml")


def get_conn():
    """One SQLite connection per browser session, kept across its reruns.

    WHY: a single connection shared by every session (st.cache_resource) lets
    two users' transactions interleave on the same handle. Each session runs
    one script at a time, so its own connection is never used concurrently;
    check_same_thread=False only lets successive reruns reuse it.
    """
    conn = st.session_state.get("_db_conn")
    if conn is None:
        conn = connect()
        st.session_state["_db_conn"] = conn
    return conn


def _read_yaml(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def load_config() -> dict:
    """Defaults, then config.yaml, then the local overrides written by Settings."""
    merged = {**_DEFAULT_CONFIG, "features": dict(_DEFAULT_CONFIG["features"])}
    for layer in (_read_yaml(CONFIG_PATH), _read_yaml(local_config_path())):
        merged.update({k: v for k, v in layer.items() if k != "features"})
        merged["features"].update(layer.get("features") or {})
    return merged


def save_config(cfg: dict) -> None:
    """Persist Settings changes to the local override file."""
    path = local_config_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False)


@st.cache_data(show_spinner="Analysing contract...")
def analysis_for(
    version_id: str,
    text: str,
    contract_type: str | None = None,
    use_tfidf: bool | None = None,
) -> dict:
    """Rebuild the full analysis from stored text so the summary is derived,
    never stored separately. Keyed by version id. use_tfidf defaults to the
    config flag; it is an argument so the cache key changes with the setting."""
    if use_tfidf is None:
        use_tfidf = bool(load_config()["features"].get("tfidf_fallback", False))
    return analyse(text, contract_type, use_tfidf)


def load_samples(conn) -> int:
    """Analyse and save every data/samples/*.txt not already stored by title."""
    import pathlib

    known = {row["title"].lower() for row in list_contracts(conn)}
    use_tfidf = bool(load_config()["features"].get("tfidf_fallback", False))
    count = 0
    for path in sorted(pathlib.Path(SAMPLES_DIR).glob("*.txt")):
        result = analyse(path.read_text(encoding="utf-8"), use_tfidf=use_tfidf)
        if result["summary"]["title"].lower() in known:
            continue
        # Documents title themselves in capitals; the register reads better in title case.
        save_analysis(conn, result, path.name, title=result["summary"]["title"].title())
        count += 1
    return count
