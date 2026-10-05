"""Deny cells: with the lock on, opening any page directly shows only the sign-in form.

Hiding the navigation would be cosmetic; the real check is the direct URL, including deep
links with a contract or version id, which must not leak any contract data.
"""

import json
from pathlib import Path

import pytest

from e2e.conftest import expect, open_page

MATRIX = json.loads((Path(__file__).parent / "coverage-matrix.json").read_text(encoding="utf-8"))
CELLS = [f for f in MATRIX["features"] if f["id"] != "auth.sign_in"]


def _deep_link(feature, server):
    # Use a real stored id so a leak would actually show data.
    from storage.db import connect
    from storage.models import list_contracts

    row = next(r for r in list_contracts(connect(server.db)) if r["title"] == "Supply Agreement")
    if feature["module"] == "review":
        return f"review?version={row['latest_version_id']}"
    if feature["module"] == "register":
        return f"register?contract={row['id']}"
    return feature["route"].lstrip("/")


@pytest.mark.parametrize(
    "feature",
    [pytest.param(f, id=f["id"], marks=pytest.mark.cell(f["id"], "locked")) for f in CELLS],
)
def test_locked_visitor_cannot_reach_page(page, locked_server, feature):
    open_page(page, locked_server.url, _deep_link(feature, locked_server))
    expect(page.get_by_role("button", name="Sign in")).to_be_visible()
    main = page.get_by_test_id("stMain")
    for leaked in ("Supply Agreement", "GOLDEN ROOT", "Contracts stored", "N120,000,000"):
        expect(main.get_by_text(leaked)).to_have_count(0)
    expect(page.get_by_test_id("stFileUploader")).to_have_count(0)
    expect(page.get_by_role("button", name="Delete all data")).to_have_count(0)
