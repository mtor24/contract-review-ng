"""Search: keyword hits with highlights; injection-style input is harmless."""

import re

import pytest

from e2e.conftest import expect, open_page, wait_idle


def _search(page, base_url: str, query: str) -> None:
    open_page(page, base_url, "search")
    page.get_by_placeholder("e.g. indemnify, arbitration, personal data").fill(query)
    page.get_by_role("button", name="Search").click()
    wait_idle(page)


@pytest.mark.cell("search.query", "owner")
def test_search_highlights_matches(page, owner_server):
    _search(page, owner_server.url, "indemnify")
    main = page.get_by_test_id("stMain")
    # The three samples with indemnities are found, and the matched word itself is highlighted.
    for title in ("Supply Agreement", "Service Level Agreement", "Non-Disclosure Agreement"):
        expect(main.get_by_role("button", name=title, exact=True).first).to_be_visible()
    expect(main.locator("mark").first).to_have_text(re.compile(r"indemnif", re.IGNORECASE))


@pytest.mark.cell("search.query", "owner")
def test_injection_style_query_is_harmless(page, fresh_server):
    _search(page, fresh_server.url, '"; DELETE FROM contracts; --')
    main = page.get_by_test_id("stMain")
    expect(main.get_by_text("No matches. Try a shorter word or a different spelling.")).to_be_visible()
    expect(page.get_by_test_id("stException")).to_have_count(0)

    # The register still lists every seeded contract.
    open_page(page, fresh_server.url, "register")
    expect(main.get_by_text("7 contracts", exact=True)).to_be_visible()
