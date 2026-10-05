"""Lock screen: the locked visitor sees only the sign-in form; the owner gets in with the password."""

import pytest

from e2e.conftest import expect, open_page, sign_in


@pytest.mark.cell("auth.sign_in", "owner")
def test_owner_signs_in_with_right_password_only(page, locked_server, locked_password):
    open_page(page, locked_server.url)
    page.get_by_label("Password", exact=True).fill("not-the-password")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_text("That password is not correct.")).to_be_visible()
    expect(page.get_by_role("heading", name="Dashboard")).to_have_count(0)

    sign_in(page, locked_server.url, locked_password)
    expect(page.get_by_text("Contracts stored")).to_be_visible()
    # The session stays signed in across a page change.
    page.get_by_role("link", name="Contract Register").click()
    expect(page.get_by_role("button", name="Supply Agreement")).to_be_visible()


@pytest.mark.cell("auth.sign_in", "locked")
def test_locked_visitor_sees_only_sign_in(page, locked_server):
    open_page(page, locked_server.url)
    expect(page.get_by_role("button", name="Sign in")).to_be_visible()
    expect(page.get_by_text("Contracts stored")).to_have_count(0)
