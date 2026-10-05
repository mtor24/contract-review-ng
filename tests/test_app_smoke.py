"""App smoke tests: dashboard, review page, register, deadlines, search, reports."""

import pathlib

import pytest
from streamlit.testing.v1 import AppTest

from core.pipeline import analyse
from storage import models
from storage.db import connect

# Relative paths resolve against this file, so go up to the project root.
ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
REVIEW_PAGE = str(ROOT / "ui" / "pages" / "review.py")
REGISTER_PAGE = str(ROOT / "ui" / "pages" / "register.py")
DEADLINES_PAGE = str(ROOT / "ui" / "pages" / "deadlines.py")
SEARCH_PAGE = str(ROOT / "ui" / "pages" / "search.py")
REPORTS_PAGE = str(ROOT / "ui" / "pages" / "reports.py")


@pytest.fixture
def app_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LEXREVIEW_DB", str(tmp_path / "test.db"))
    # st.cache_resource lives in one in-process store, so without clearing,
    # a second AppTest run would reuse the first test's database connection.
    import streamlit as st

    st.cache_resource.clear()
    st.cache_data.clear()


def test_empty_dashboard(app_db):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert len(at.metric) == 0
    texts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    assert any("No contracts yet" in t for t in texts)


def test_dashboard_metrics_after_samples(app_db):
    conn = connect()
    from ui.state import load_samples

    assert load_samples(conn) == 7
    conn.close()

    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert len(at.metric) == 4
    assert at.metric[0].label == "Contracts stored"
    assert at.metric[0].value == "7"


def _saved_version_id() -> str:
    """Analyse the supply agreement and store it; return the version id."""
    conn = connect()
    text = pathlib.Path("data/samples/supply_agreement.txt").read_text(encoding="utf-8")
    _, version_id = models.save_analysis(
        conn, analyse(text), "supply_agreement.txt", title="Supply Agreement"
    )
    conn.close()
    return version_id


def test_review_page_workspace(app_db):
    version_id = _saved_version_id()

    at = AppTest.from_file(REVIEW_PAGE, default_timeout=120)
    at.query_params["version"] = version_id
    at.run()
    assert not at.exception
    assert len(at.tabs) == 6
    assert any("Risks (" in tab.label for tab in at.tabs)

    conn = connect()
    reviewed_before, _ = models.review_progress(conn, version_id)
    conn.close()

    at.button(key="rv-risk-risk-0-ok").click().run()
    assert not at.exception

    conn = connect()
    reviewed_after, _ = models.review_progress(conn, version_id)
    conn.close()
    assert reviewed_after > reviewed_before


@pytest.fixture
def sample_db(app_db):
    """Temp database with all 7 sample contracts loaded."""
    conn = connect()
    from ui.state import load_samples

    load_samples(conn)
    conn.close()


def test_register_lists_sample_contracts(sample_db):
    at = AppTest.from_file(REGISTER_PAGE, default_timeout=120).run()
    assert not at.exception
    # One tertiary title button per contract row.
    titles = [b for b in at.button if b.label != "Review a contract"]
    assert len(titles) >= 7


def test_register_detail_view(sample_db):
    conn = connect()
    contract_id = models.list_contracts(conn)[0]["id"]
    conn.close()

    at = AppTest.from_file(REGISTER_PAGE, default_timeout=120)
    at.query_params["contract"] = contract_id
    at.run()
    assert not at.exception
    assert any(m.value and m.value.startswith("**v") for m in at.markdown)


def test_deadlines_90_days_renders(sample_db):
    at = AppTest.from_file(DEADLINES_PAGE, default_timeout=120)
    at.run()
    assert not at.exception
    seg = at.segmented_control[0]
    seg.set_value("90 days")
    seg.run()
    assert not at.exception


def test_search_finds_indemnify(sample_db):
    at = AppTest.from_file(SEARCH_PAGE, default_timeout=120).run()
    assert not at.exception
    at.text_input[0].set_value("indemnify")
    at.button(key="search-btn").click().run()
    assert not at.exception
    captions = [c.value for c in at.caption]
    assert any("result" in c for c in captions)
    assert not any("No matches" in (m.value or "") for m in at.markdown)


def test_reports_renders(sample_db):
    at = AppTest.from_file(REPORTS_PAGE, default_timeout=180).run()
    assert not at.exception
    assert len(at.download_button) == 2
