"""Deadlines: the 30/60/90 day windows list exactly the stored obligations due in them."""

from datetime import date

import pytest

from e2e.conftest import expect, open_page, wait_idle


def _expected_count(db_path, days: int) -> int:
    from storage.db import connect
    from storage.models import upcoming_obligations

    conn = connect(db_path)
    count = len(upcoming_obligations(conn, date.today(), days))
    conn.close()
    return count


def _expect_window(page, db_path, label: str, days: int) -> int:
    """Pick a window and check the page lists exactly what the database says is due."""
    page.get_by_role("radio", name=label).click()
    wait_idle(page)
    expected = _expected_count(db_path, days)
    main = page.get_by_test_id("stMain")
    # Each listed deadline has its own "Open contract" button; an empty window shows the empty state.
    expect(main.get_by_role("button", name="Open contract")).to_have_count(expected)
    expect(main.get_by_text("No deadlines in this window.")).to_have_count(1 if expected == 0 else 0)
    return expected


@pytest.mark.cell("deadlines.view_filter", "owner")
def test_deadlines_window_counts_match_the_database(page, fresh_server):
    open_page(page, fresh_server.url, "deadlines")
    n30 = _expect_window(page, fresh_server.db, "30 days", 30)
    n60 = _expect_window(page, fresh_server.db, "60 days", 60)
    n90 = _expect_window(page, fresh_server.db, "90 days", 90)
    assert n30 <= n60 <= n90
    # The samples carry deadlines in late 2026, so the widest window is never empty in the demo period.
    assert n90 > 0
    expect(page.get_by_test_id("stMain").get_by_text("Loan Agreement").first).to_be_visible()
