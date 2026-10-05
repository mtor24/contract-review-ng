"""Contract Register: list and filters, status change, version diff, delete."""

import pytest

from e2e.conftest import expect, open_page, unique, wait_idle

SUPPLY = "data/samples/supply_agreement.txt"
SUPPLY_V2 = "data/samples/versions/supply_agreement_v2.txt"
NDA = "data/samples/nda.txt"


def _analyse_upload(page, base_url: str, path: str, title: str, parent: str | None = None) -> None:
    """Upload a contract through the Review page; optionally as a new version."""
    open_page(page, base_url, "review")
    page.get_by_test_id("stFileUploaderDropzoneInput").set_input_files(path)
    expect(page.get_by_role("button", name="Analyse contract")).to_be_visible()
    wait_idle(page)
    if parent is not None:
        page.get_by_role("combobox", name="Save as a new version of an existing contract (optional)").click()
        page.get_by_role("option", name=parent).click()
        wait_idle(page)
    page.get_by_label("Title", exact=True).fill(title)
    page.get_by_role("button", name="Analyse contract").click()
    expect(page.get_by_role("tab", name="Summary")).to_be_visible()
    wait_idle(page)


def _open_from_register(page, base_url: str, title: str) -> None:
    open_page(page, base_url, "register")
    page.get_by_role("button", name=title).click()
    expect(page.get_by_role("button", name="Delete contract")).to_be_visible()
    wait_idle(page)


@pytest.mark.cell("register.list_filter", "owner")
def test_register_lists_filters_and_empty_state(page, fresh_server):
    open_page(page, fresh_server.url, "register")
    main = page.get_by_test_id("stMain")

    # Seven seeded rows, each with an Under Review badge.
    expect(main.get_by_text("7 contracts", exact=True)).to_be_visible()
    expect(main.get_by_text("Under Review", exact=True)).to_have_count(7)

    # Title search narrows to the lease. Streamlit applies a text input on Enter.
    page.get_by_label("Search titles").fill("lease")
    page.get_by_label("Search titles").press("Enter")
    wait_idle(page)
    expect(main.get_by_text("1 contract", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Lease Agreement")).to_be_visible()
    page.get_by_label("Search titles").fill("")
    page.get_by_label("Search titles").press("Enter")
    wait_idle(page)

    # Type filter. Escape closes the list, Tab moves focus on so the next click is not
    # swallowed by the field losing focus.
    page.get_by_role("combobox", name="Type").click()
    page.get_by_role("option", name="Lease / Tenancy Agreement").click()
    page.keyboard.press("Escape")
    page.keyboard.press("Tab")
    wait_idle(page)
    expect(main.get_by_text("1 contract", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Lease Agreement")).to_be_visible()
    # Clear the type selection again: a picked option leaves the list and becomes a removable tag.
    page.get_by_role("button", name="Remove Lease / Tenancy Agreement").click()
    wait_idle(page)
    expect(main.get_by_text("7 contracts", exact=True)).to_be_visible()

    # Status filter.
    page.get_by_role("combobox", name="Status").click()
    page.get_by_role("option", name="Under Review").click()
    page.keyboard.press("Escape")
    page.keyboard.press("Tab")
    wait_idle(page)
    expect(main.get_by_text("7 contracts", exact=True)).to_be_visible()
    page.get_by_role("button", name="Remove Under Review").click()
    wait_idle(page)
    # A status no seeded contract has proves the filter really excludes rows.
    page.get_by_role("combobox", name="Status").click()
    page.get_by_role("option", name="Draft").click()
    page.keyboard.press("Escape")
    page.keyboard.press("Tab")
    wait_idle(page)
    expect(main.get_by_text("0 contracts", exact=True)).to_be_visible()
    page.get_by_role("button", name="Remove Draft").click()
    wait_idle(page)
    expect(main.get_by_text("7 contracts", exact=True)).to_be_visible()

    # Party filter.
    page.get_by_label("Party").fill("Mainland")
    page.get_by_label("Party").press("Enter")
    wait_idle(page)
    expect(main.get_by_text("1 contract", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Supply Agreement")).to_be_visible()
    count = main.get_by_text("Under Review", exact=True)
    expect(count.first).to_be_visible()
    page.get_by_label("Party").fill("")
    page.get_by_label("Party").press("Enter")
    wait_idle(page)

    # A filter combination with no match shows the empty state.
    page.get_by_label("Search titles").fill("no such contract zzz")
    page.get_by_label("Search titles").press("Enter")
    wait_idle(page)
    expect(main.get_by_text("No contracts match these filters.")).to_be_visible()


@pytest.mark.cell("register.status_change", "owner")
def test_status_change_persists_after_reload(page, owner_server):
    title = unique("NDA")
    _analyse_upload(page, owner_server.url, NDA, title)
    _open_from_register(page, owner_server.url, title)

    # Change status to Active and save.
    page.get_by_role("combobox", name="Status").click()
    page.get_by_role("option", name="Active").click()
    page.get_by_role("button", name="Save").click()
    wait_idle(page)

    # Reload the same URL: Active persists.
    page.reload()
    wait_idle(page)
    expect(page.get_by_test_id("stMain").get_by_text("Active", exact=True)).to_be_visible()

    # The register row shows the new status too.
    open_page(page, owner_server.url, "register")
    # Each register row is one horizontal block of columns; pick the one holding this title.
    row = page.get_by_test_id("stHorizontalBlock").filter(has=page.get_by_role("button", name=title))
    expect(row.get_by_text("Active", exact=True)).to_be_visible()


@pytest.mark.cell("register.versions_diff", "owner")
def test_two_versions_and_clause_diff(page, owner_server):
    title = unique("Supply")
    _analyse_upload(page, owner_server.url, SUPPLY, title)
    _analyse_upload(page, owner_server.url, SUPPLY_V2, title, parent=title)
    _open_from_register(page, owner_server.url, title)

    main = page.get_by_test_id("stMain")
    # Two versions are listed.
    expect(main.get_by_text("v1", exact=True)).to_be_visible()
    expect(main.get_by_text("v2", exact=True)).to_be_visible()

    # The comparison shows Added/Removed/Changed counts.
    expect(main.get_by_role("heading", name="Compare versions")).to_be_visible()
    expect(main.get_by_text("Added:", exact=False)).to_be_visible()
    expect(main.get_by_text("Removed:", exact=False)).to_be_visible()
    expect(main.get_by_text("Changed:", exact=False)).to_be_visible()

    # At least one changed row carries an ins or del highlight.
    highlights = page.locator(".diff-changed ins, .diff-changed del")
    expect(highlights.first).to_be_visible()


@pytest.mark.cell("register.delete", "owner")
def test_delete_contract_after_confirming(page, owner_server):
    title = unique("NDA")
    _analyse_upload(page, owner_server.url, NDA, title)
    _open_from_register(page, owner_server.url, title)

    # First click Cancel: the contract is still there.
    page.get_by_role("button", name="Delete contract").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("button", name="Delete permanently")).to_be_visible()
    dialog.get_by_role("button", name="Cancel").click()
    wait_idle(page)
    expect(page.get_by_role("button", name="Delete contract")).to_be_visible()

    # Then delete permanently.
    page.get_by_role("button", name="Delete contract").click()
    page.get_by_role("dialog").get_by_role("button", name="Delete permanently").click()
    wait_idle(page)

    # Gone from the register list.
    open_page(page, owner_server.url, "register")
    expect(page.get_by_role("button", name=title)).to_have_count(0)

    # Search for a word in its text returns no result with that title.
    open_page(page, owner_server.url, "search")
    page.get_by_placeholder("e.g. indemnify, arbitration, personal data").fill("indemnify")
    page.get_by_role("button", name="Search").click()
    wait_idle(page)
    expect(page.get_by_role("button", name=title)).to_have_count(0)
