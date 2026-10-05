"""Regenerate the report hand-off screenshots and architecture.png.

Run from the project root:  python report_handoff/capture.py
Starts its own copy of the app on a throwaway database seeded with the sample contracts,
records a few lawyer decisions so the screens show real use, then saves:
  report_handoff/screenshots/01_home_or_dashboard.png ... 06_register_or_report.png
  report_handoff/architecture.png (rendered from report_handoff/architecture.html, offline)
"""

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from e2e.conftest import Server, expect, open_page, wait_idle  # noqa: E402
from storage import models  # noqa: E402
from storage.db import connect  # noqa: E402

OUT = ROOT / "report_handoff"
SHOTS = OUT / "screenshots"
VIEW = {"width": 1440, "height": 900}


def seed_decisions(server: Server) -> dict:
    conn = connect(server.db)
    supply = next(c for c in models.list_contracts(conn) if c["title"] == "Supply Agreement")
    version_id = supply["latest_version_id"]
    risks = [f for f in models.get_version(conn, version_id)["findings"] if f["kind"] == "risk"]
    models.set_decision(conn, version_id, risks[0]["fid"], "accepted", note="Ask for 1.5% per month at most.")
    models.set_decision(conn, version_id, risks[1]["fid"], "edited", note="Propose a cap.",
                        edited_text="Liability capped at the Contract Value.")
    models.set_decision(conn, version_id, risks[4]["fid"], "rejected", note="Acceptable for this client.")
    conn.close()
    return {"version_id": version_id}


def shot(page, name: str) -> None:
    wait_idle(page)
    page.screenshot(path=str(SHOTS / name))
    print("saved", name)


def screenshots(browser) -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        server = Server(Path(tmp) / "app")
        try:
            ids = seed_decisions(server)
            page = browser.new_page(viewport=VIEW)
            page.set_default_timeout(60_000)
            url = server.url

            open_page(page, url)
            expect(page.get_by_text("Contracts stored")).to_be_visible()
            shot(page, "01_home_or_dashboard.png")

            open_page(page, url, "review")
            page.get_by_test_id("stFileUploaderDropzoneInput").set_input_files(
                str(ROOT / "data" / "samples" / "lease_agreement.txt"))
            expect(page.get_by_role("button", name="Analyse contract")).to_be_visible()
            shot(page, "02_upload.png")

            open_page(page, url, f"review?version={ids['version_id']}")
            page.get_by_role("tab", name=re.compile(r"^Risks")).click()
            wait_idle(page)
            risks = page.get_by_role("tabpanel", name=re.compile(r"^Risks"))
            risks.get_by_role("button", name="Show in text").nth(1).click()
            wait_idle(page)
            page.get_by_role("tab", name=re.compile(r"^Clauses")).click()
            shot(page, "03_review_clauses.png")

            page.get_by_role("tab", name=re.compile(r"^Risks")).click()
            shot(page, "04_risks_or_missing_clauses.png")

            page.get_by_role("tab", name=re.compile(r"^Nigerian compliance")).click()
            shot(page, "05_compliance_or_deadlines.png")

            open_page(page, url, "register")
            expect(page.get_by_text("7 contracts")).to_be_visible()
            shot(page, "06_register_or_report.png")
            page.close()
        finally:
            server.stop()


def architecture(browser) -> None:
    """Render report_handoff/architecture.html (hand-laid-out, easy to read) to a PNG."""
    page = browser.new_page(viewport={"width": 1400, "height": 1000}, device_scale_factor=2)
    page.goto((OUT / "architecture.html").as_uri())
    page.wait_for_function("document.fonts.status === 'loaded'")
    page.locator("#diagram").screenshot(path=str(OUT / "architecture.png"))
    print("saved architecture.png")
    page.close()


def main() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        screenshots(browser)
        architecture(browser)
        browser.close()


if __name__ == "__main__":
    main()
