"""Capture every main screen into docs/screenshots/ for the write-up (developer tool only).

Run from the project root:  python scripts/screenshots.py
Needs the dev requirements and a browser: python -m playwright install chromium

It starts its own server on a throwaway database seeded with the sample contracts,
adds version 2 of the supply agreement so the comparison has something to show, and
makes a few review decisions so the progress bar and report are not empty.
"""

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from core.pipeline import analyse  # noqa: E402
from e2e.conftest import Server, expect, open_page, wait_idle  # noqa: E402
from storage import models  # noqa: E402
from storage.db import connect  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
WIDTH, HEIGHT = 1440, 900


def prepare(server: Server) -> dict:
    conn = connect(server.db)
    supply = next(c for c in models.list_contracts(conn) if c["title"] == "Supply Agreement")
    v1 = supply["latest_version_id"]
    findings = models.get_version(conn, v1)["findings"]
    risks = [f for f in findings if f["kind"] == "risk"]
    models.set_decision(conn, v1, risks[0]["fid"], "accepted", note="Ask for 1.5% per month at most.")
    models.set_decision(conn, v1, risks[1]["fid"], "edited", note="Propose a cap.",
                        edited_text="Liability capped at the Contract Value.")
    v2_text = (ROOT / "data" / "samples" / "versions" / "supply_agreement_v2.txt").read_text(encoding="utf-8")
    models.save_analysis(conn, analyse(v2_text), "supply_agreement_v2.txt", contract_id=supply["id"])
    conn.close()
    return {"supply_id": supply["id"], "v1": v1}


def shot(page, name: str, full: bool = False) -> None:
    wait_idle(page)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
    print("saved", name)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        server = Server(Path(tmp))
        try:
            ids = prepare(server)
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
                url = server.url

                open_page(page, url)
                expect(page.get_by_text("Contracts stored")).to_be_visible()
                shot(page, "01-dashboard")

                open_page(page, url, "review")
                shot(page, "02-review-upload")

                open_page(page, url, f"review?version={ids['v1']}")
                expect(page.get_by_role("tab", name="Summary")).to_be_visible()
                shot(page, "03-review-summary")
                for i, tab in enumerate(["Clauses", "Missing clauses", "Risks", "Nigerian compliance",
                                         "Obligations"], start=4):
                    page.get_by_role("tab", name=re.compile(f"^{tab}")).click()
                    if tab == "Risks":
                        page.get_by_role("button", name="Show in text").first.click()
                    shot(page, f"{i:02d}-review-{tab.lower().replace(' ', '-')}")

                open_page(page, url, "register")
                shot(page, "09-register")
                open_page(page, url, f"register?contract={ids['supply_id']}")
                expect(page.get_by_role("heading", name="Compare versions")).to_be_visible()
                shot(page, "10-register-detail")
                page.get_by_role("heading", name="Compare versions").evaluate("e => e.scrollIntoView({block: 'start'})")
                shot(page, "11-version-comparison")
                page.get_by_role("button", name="Delete contract").click()
                shot(page, "12-delete-confirmation")

                open_page(page, url, "deadlines")
                page.get_by_text("90 days", exact=True).click()
                shot(page, "13-deadlines")

                open_page(page, url, "search")
                page.get_by_placeholder("e.g. indemnify, arbitration, personal data").fill("indemnify")
                page.get_by_role("button", name="Search").click()
                shot(page, "14-search")

                open_page(page, url, "reports")
                shot(page, "15-reports")

                open_page(page, url, "settings")
                shot(page, "16-settings")
                browser.close()
        finally:
            server.stop()


if __name__ == "__main__":
    main()
