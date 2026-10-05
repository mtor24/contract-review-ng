"""Settings: firm name persistence and the delete-all-data flow."""

import pytest

from e2e.conftest import expect, open_page, unique, wait_idle


@pytest.mark.cell("settings.firm_name", "owner")
def test_firm_name_persists_and_appears_in_report(page, fresh_server):
    firm = unique("Chambers")
    open_page(page, fresh_server.url, "settings")
    page.get_by_label("Firm name").fill(firm)
    page.get_by_role("button", name="Save").first.click()
    wait_idle(page)

    # Reload Settings: the name persists.
    open_page(page, fresh_server.url, "settings")
    expect(page.get_by_label("Firm name")).to_have_value(firm)

    # The Reports preview carries the firm name on the cover.
    open_page(page, fresh_server.url, "reports")
    expect(page.get_by_role("heading", name=firm)).to_be_visible()


@pytest.mark.cell("settings.delete_all", "owner")
def test_delete_all_data_requires_typing_delete(page, fresh_server):
    open_page(page, fresh_server.url, "settings")
    page.get_by_role("button", name="Delete all data").click()

    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_text("Type DELETE to confirm")).to_be_visible()

    # Clicking without typing DELETE deletes nothing.
    confirm = dialog.get_by_role("button", name="Delete everything")
    confirm.click()
    wait_idle(page)
    expect(dialog.get_by_text("Nothing was deleted. Type DELETE in the box to confirm.")).to_be_visible()
    from storage.db import connect
    from storage.models import list_contracts
    assert len(list_contracts(connect(fresh_server.db))) == 7

    # Typing DELETE and clicking once is enough (no Enter needed).
    dialog.get_by_label("Type DELETE to confirm").fill("DELETE")
    confirm.click()
    wait_idle(page)

    # Dashboard and register show their empty states.
    open_page(page, fresh_server.url)
    expect(
        page.get_by_text("No contracts yet. Upload your first contract to begin.")
    ).to_be_visible()
    open_page(page, fresh_server.url, "register")
    expect(
        page.get_by_text("No contracts yet. Upload your first contract to begin.")
    ).to_be_visible()
