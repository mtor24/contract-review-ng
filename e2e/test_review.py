"""Review a Contract: upload and analyse, decide on findings, show in text."""

import re

import pytest

from e2e.conftest import expect, open_page, unique, wait_idle

NDA = "data/samples/nda.txt"
# Six risk findings, so the decide journey has three distinct cards to act on.
SUPPLY = "data/samples/supply_agreement.txt"
RISKS_TAB = re.compile(r"^Risks \(\d+\)$")


def _badge(label: str) -> re.Pattern:
    # st.badge text is the icon ligature name, a space, then the label: "check_circle Accepted".
    return re.compile(rf"^(\w+ )?{label}$")


def _risk_cards(page):
    """Finding cards in the open Risks tab.

    Streamlit 1.65 renders a bordered container as a plain stVerticalBlock, and every
    enclosing block also "has" the buttons, so a card is the innermost block holding an
    Accept button. Scoping to the Risks tabpanel skips the hidden tabs' cards.
    """
    accept = page.get_by_role("button", name="Accept")
    holders = page.get_by_test_id("stVerticalBlock").filter(has=accept)
    panel = page.get_by_role("tabpanel", name=RISKS_TAB)
    return panel.get_by_test_id("stVerticalBlock").filter(has=accept).filter(has_not=holders)


def _upload_and_analyse(page, base_url: str, title: str, path: str = NDA) -> None:
    """Full upload journey on the Review page; ends on the workspace tabs."""
    open_page(page, base_url, "review")
    page.get_by_test_id("stFileUploaderDropzoneInput").set_input_files(path)
    expect(page.get_by_role("button", name="Analyse contract")).to_be_visible()
    wait_idle(page)
    page.get_by_label("Title", exact=True).fill(title)
    page.get_by_role("button", name="Analyse contract").click()
    expect(page.get_by_role("tab", name="Summary")).to_be_visible()
    wait_idle(page)


@pytest.mark.cell("review.analyse", "owner")
def test_upload_analyse_and_find_in_register(page, owner_server):
    title = unique("NDA")
    open_page(page, owner_server.url, "review")
    page.get_by_test_id("stFileUploaderDropzoneInput").set_input_files(NDA)
    expect(page.get_by_role("button", name="Analyse contract")).to_be_visible()
    wait_idle(page)

    # Auto-detected type, then a unique title.
    expect(
        page.get_by_role("combobox", name="Contract type (auto-detected, you can change it)")
    ).to_have_value("Non-Disclosure Agreement")
    page.get_by_label("Title", exact=True).fill(title)
    page.get_by_role("button", name="Analyse contract").click()

    # The workspace: six tabs, one of them "Risks (...)".
    tabs = page.get_by_role("tab")
    expect(tabs).to_have_count(6)
    expect(page.get_by_role("tab", name=re.compile(r"^Risks \(\d+\)$"))).to_be_visible()
    wait_idle(page)

    # After a full reload the contract sits in the register under the unique title.
    open_page(page, owner_server.url, "register")
    expect(page.get_by_role("button", name=title)).to_be_visible()


@pytest.mark.cell("review.analyse", "owner")
def test_unsupported_file_shows_plain_english_error(page, owner_server, tmp_path):
    bad = tmp_path / "spreadsheet.csv"
    bad.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    open_page(page, owner_server.url, "review")
    page.get_by_test_id("stFileUploaderDropzoneInput").set_input_files(str(bad))
    # Streamlit itself refuses the file with a plain-English alert; no workspace opens.
    expect(page.get_by_role("alert").filter(has_text="files are not allowed")).to_be_visible()
    expect(page.get_by_role("tab", name="Summary")).to_have_count(0)


@pytest.mark.cell("review.analyse", "owner")
def test_damaged_supported_file_shows_plain_english_error(page, owner_server, tmp_path):
    bad = tmp_path / "damaged.pdf"
    bad.write_bytes(b"not a real pdf at all")
    open_page(page, owner_server.url, "review")
    page.get_by_test_id("stFileUploaderDropzoneInput").set_input_files(str(bad))
    expect(page.get_by_text("This file could not be read.")).to_be_visible()
    wait_idle(page)
    expect(page.get_by_role("tab", name="Summary")).to_have_count(0)


@pytest.mark.cell("review.decide", "owner")
def test_accept_reject_edit_persist_and_filter(page, owner_server):
    title = unique("Supply")
    _upload_and_analyse(page, owner_server.url, title, SUPPLY)

    page.get_by_role("tab", name=RISKS_TAB).click()
    wait_idle(page)
    cards = _risk_cards(page)
    expect(cards.first).to_be_visible()

    # Accept the first card with a note.
    first = cards.nth(0)
    first.get_by_placeholder("Add a note for the file").fill("Checked against playbook")
    first.get_by_role("button", name="Accept").click()
    wait_idle(page)
    expect(cards.nth(0).get_by_text(_badge("Accepted"))).to_be_visible()

    # Reject the second card.
    cards.nth(1).get_by_role("button", name="Reject").click()
    wait_idle(page)
    expect(cards.nth(1).get_by_text(_badge("Rejected"))).to_be_visible()

    # Edit the third card via the popover.
    cards.nth(2).get_by_role("button", name="Edit").click()
    pop = page.get_by_test_id("stPopoverBody")
    pop.get_by_label("Your corrected text").fill("Liability is capped at the fees paid.")
    pop.get_by_role("button", name="Save edit").click()
    wait_idle(page)
    expect(cards.nth(2).get_by_text(_badge("Edited"))).to_be_visible()

    # Reload: the three decisions and the note persist and the progress text moves.
    page.reload()
    wait_idle(page)
    page.get_by_role("tab", name=RISKS_TAB).click()
    wait_idle(page)
    cards = _risk_cards(page)
    expect(cards.nth(0).get_by_text(_badge("Accepted"))).to_be_visible()
    expect(cards.nth(0).get_by_placeholder("Add a note for the file")).to_have_value("Checked against playbook")
    expect(cards.nth(1).get_by_text(_badge("Rejected"))).to_be_visible()
    expect(cards.nth(2).get_by_text(_badge("Edited"))).to_be_visible()
    expect(page.get_by_text(re.compile(r"Reviewed 3 of \d+ findings"))).to_be_visible()

    # The Decided filter shows exactly those three cards.
    # st.segmented_control renders as a radiogroup.
    page.get_by_role("tabpanel", name=RISKS_TAB).get_by_role("radio", name="Decided").click()
    wait_idle(page)
    expect(cards).to_have_count(3)
    expect(cards.get_by_text(_badge("Suggestion"))).to_have_count(0)


@pytest.mark.cell("review.show_in_text", "owner")
def test_show_in_text_focuses_excerpt_in_contract_pane(page, owner_server):
    title = unique("NDA")
    _upload_and_analyse(page, owner_server.url, title)

    page.get_by_role("tab", name=RISKS_TAB).click()
    wait_idle(page)

    # First High risk card: remember its excerpt, then jump to it.
    high_card = _risk_cards(page).filter(has_text="High").first
    expect(high_card).to_be_visible()
    excerpt = high_card.locator(".finding-excerpt").inner_text()
    high_card.get_by_role("button", name="Show in text").click()
    wait_idle(page)

    # A risk has its own highlight, so inside the contract pane iframe the one focused
    # element is that mark (not the whole clause section) and it wraps the excerpt text.
    pane = page.frame_locator('[data-testid="stIFrame"]')
    expect(pane.locator(".focus")).to_have_count(1)
    focus = pane.locator("mark.focus")
    expect(focus).to_be_visible()
    expect(focus).to_contain_text(excerpt[:60])


@pytest.mark.cell("review.show_in_text", "owner")
def test_show_in_text_keeps_the_risks_tab_open_for_decisions(page, owner_server):
    # The real lawyer flow: check a finding in the text, then decide on it straight away.
    # "Show in text" reruns the page, so this proves the Risks tab stays open across it.
    _upload_and_analyse(page, owner_server.url, unique("Supply"), SUPPLY)
    page.get_by_role("tab", name=RISKS_TAB).click()
    wait_idle(page)
    page.get_by_role("button", name="Show in text").first.click()
    wait_idle(page)
    expect(page.get_by_role("tab", selected=True)).to_have_text(RISKS_TAB)
    page.get_by_role("button", name="Accept").first.click()
    wait_idle(page)
    expect(page.get_by_role("tab", selected=True)).to_have_text(RISKS_TAB)
    expect(page.get_by_text(re.compile(r"Reviewed 1 of \d+"))).to_be_visible()
