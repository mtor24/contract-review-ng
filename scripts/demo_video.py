"""Record a captioned demonstration video of LexReview NG (developer tool only).

Run from the project root:  python scripts/demo_video.py
Writes docs/video/lexreview-ng-demo.mp4 (needs ffmpeg on PATH; otherwise the .webm is kept).

The script starts its own copy of the app on a throwaway database with six of the
sample contracts, then follows docs/demo.md: it uploads the supply agreement live,
reviews it, compares a second version, and visits every page. Captions and a visible
pointer are drawn into the page so the video makes sense without narration. Pauses
here are deliberate pacing for viewers, unlike the E2E tests, which never sleep.
"""

import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from e2e.conftest import Server, expect, open_page, wait_idle  # noqa: E402
from storage import models  # noqa: E402
from storage.db import connect  # noqa: E402

OUT_DIR = ROOT / "docs" / "video"
WIDTH, HEIGHT = 1440, 900
SUPPLY = str(ROOT / "data" / "samples" / "supply_agreement.txt")
SUPPLY_V2 = str(ROOT / "data" / "samples" / "versions" / "supply_agreement_v2.txt")

# Injected into every page: a caption bar, a title card and a visible mouse pointer.
OVERLAY_JS = """
(() => {
  if (window.__lexOverlay) return; window.__lexOverlay = true;
  const css = `
    #lex-cap{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:2147483000;
      max-width:1000px;background:rgba(30,42,68,.94);color:#fff;font:500 19px/1.45 Inter,system-ui,sans-serif;
      padding:14px 24px;border-radius:10px;border-left:4px solid #B8963E;box-shadow:0 6px 24px rgba(0,0,0,.25);
      opacity:0;transition:opacity .35s ease;pointer-events:none}
    #lex-cap b{color:#E3C77E;font-weight:650}
    #lex-card{position:fixed;inset:0;z-index:2147483001;background:#1E2A44;color:#fff;display:flex;flex-direction:column;
      align-items:center;justify-content:center;text-align:center;font-family:Inter,system-ui,sans-serif;
      opacity:0;transition:opacity .5s ease;pointer-events:none}
    #lex-card h1{font-size:46px;font-weight:700;margin:0 0 12px}
    #lex-card h2{font-size:28px;font-weight:600;margin:0 0 18px;max-width:1000px;line-height:1.35}
    #lex-card .k{color:#B8963E;font-size:15px;letter-spacing:.08em;text-transform:uppercase;margin-top:18px}
    #lex-card h1 span{color:#B8963E}
    #lex-card p{font-size:20px;color:#C9D1E3;margin:6px 0;max-width:900px;line-height:1.5}
    #lex-ptr{position:fixed;z-index:2147483002;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;
      background:rgba(184,150,62,.85);border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);
      pointer-events:none;transition:transform .12s ease;left:-50px;top:-50px}
    #lex-ptr.down{transform:scale(.6)}`;
  const add = () => {
    const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s);
    for (const id of ['lex-cap','lex-card','lex-ptr']) { const d = document.createElement('div'); d.id = id; document.body.appendChild(d); }
    const p = document.getElementById('lex-ptr');
    document.addEventListener('mousemove', e => { p.style.left = e.clientX + 'px'; p.style.top = e.clientY + 'px'; }, true);
    document.addEventListener('mousedown', () => p.classList.add('down'), true);
    document.addEventListener('mouseup', () => p.classList.remove('down'), true);
  };
  if (document.body) add(); else document.addEventListener('DOMContentLoaded', add);
  window.__lexCap = (html) => { const c = document.getElementById('lex-cap'); if (!c) return;
    if (!html) { c.style.opacity = 0; return; } c.innerHTML = html; c.style.opacity = 1; };
  window.__lexCard = (html) => { const c = document.getElementById('lex-card'); if (!c) return;
    if (!html) { c.style.opacity = 0; return; } c.innerHTML = html; c.style.opacity = 1; };
})();
"""


class Director:
    """Small helpers that keep the recording smooth and readable."""

    def __init__(self, page, url):
        self.page, self.url = page, url

    def pause(self, seconds: float) -> None:
        time.sleep(seconds)

    def caption(self, html: str, hold: float = 0.0) -> None:
        self.page.evaluate("h => window.__lexCap && window.__lexCap(h)", html)
        self.pause(hold)

    def card(self, html: str, hold: float) -> None:
        self.page.evaluate("h => window.__lexCard && window.__lexCard(h)", html)
        self.pause(hold)
        self.page.evaluate("() => window.__lexCard && window.__lexCard('')")
        self.pause(0.6)

    def nav(self, name: str) -> None:
        """Go to another page from the sidebar, clearing the old caption first."""
        self.caption("")
        self.click(self.page.get_by_role("link", name=name))

    def go(self, path: str) -> None:
        open_page(self.page, self.url, path)

    def point(self, locator) -> None:
        """Glide the visible pointer to an element so viewers see what happens next."""
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        if box:
            self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=30)
            self.pause(0.35)

    def click(self, locator, after: float = 0.8) -> None:
        self.point(locator)
        locator.click()
        wait_idle(self.page)
        self.pause(after)

    def type(self, locator, text: str, submit: bool = True) -> None:
        self.point(locator)
        locator.click()
        locator.press_sequentially(text, delay=55)
        if submit:
            # Enter reruns the page. Inside a tab that resets the tab, so notes are
            # typed without it and commit when the next button is clicked.
            locator.press("Enter")
            wait_idle(self.page)

    def scroll(self, pixels: int, step: int = 120, x: int = 900, y: int = 500) -> None:
        self.page.mouse.move(x, y, steps=10)
        for _ in range(max(1, abs(pixels) // step)):
            self.page.mouse.wheel(0, step if pixels > 0 else -step)
            self.pause(0.09)
        self.pause(0.6)


def prepare(server: Server) -> None:
    # Remove the seeded supply agreement so the video can upload it live.
    conn = connect(server.db)
    for c in models.list_contracts(conn):
        if c["title"] == "Supply Agreement":
            models.delete_contract(conn, c["id"])
    # The delete above is set-up, not part of the story; keep it out of Recent activity.
    with conn:
        conn.execute("DELETE FROM activity WHERE contract_id IS NULL AND action = 'Deleted a contract'")
    conn.close()


def record(server: Server, video_dir: Path) -> tuple[Path, float]:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            record_video_dir=str(video_dir),
            record_video_size={"width": WIDTH, "height": HEIGHT},
            accept_downloads=True,
        )
        context.add_init_script(OVERLAY_JS)
        page = context.new_page()
        started = time.monotonic()
        page.set_default_timeout(60_000)
        d = Director(page, server.url)
        main = page.get_by_test_id("stMain")

        # 1. Title card and Dashboard.
        d.go("")
        # The recording starts before the app has loaded; trim that blank lead-in later.
        lead_in = max(0.0, time.monotonic() - started - 0.2)
        d.card("<h2>AI-Driven Contract Review and Management System Developed with Python NLP "
               "Libraries for Nigerian Law Firms</h2>"
               "<h1>LexReview <span>NG</span></h1>"
               "<p>A prototype that runs fully on the lawyer's own computer.</p>"
               "<p class='k'>Master's Capstone Project</p>"
               "<p>European Global Institute of Innovation and Technology and Docenti Global Business School</p>", 7)
        d.caption("<b>Dashboard.</b> Contracts stored, contracts under review, open high-risk flags and deadlines at a glance.", 4)
        d.point(page.get_by_text("Runs locally. Your documents never leave this computer."))
        d.caption("The sidebar badge and disclaimer answer the privacy and security concerns from our survey of 321 lawyers.", 4)
        d.scroll(500)
        d.caption("Open risks by contract type, and recent activity.", 3.5)

        # 2. Upload and analyse a contract live.
        d.nav("Review a Contract")
        d.caption("<b>Review a Contract.</b> We upload a commercial supply agreement (PDF, Word or text all work).", 3)
        page.get_by_test_id("stFileUploaderDropzoneInput").set_input_files(SUPPLY)
        expect(page.get_by_role("button", name="Analyse contract")).to_be_visible()
        wait_idle(page)
        d.point(page.get_by_role("combobox", name="Contract type (auto-detected, you can change it)"))
        d.caption("The contract type is detected automatically and the lawyer can change it.", 3.5)
        title = page.get_by_label("Title", exact=True)
        title.fill("")
        d.type(title, "Supply Agreement - Golden Root")
        d.caption("Everything is analysed on this computer: clauses, gaps, risks, compliance and deadlines.", 0.5)
        d.click(page.get_by_role("button", name="Analyse contract"), after=1.5)
        expect(page.get_by_role("tab", name="Summary")).to_be_visible()
        wait_idle(page)

        # 3. Summary.
        d.caption("<b>Summary.</b> Parties and roles, key dates, the contract value in Naira, and the key terms.", 3)
        d.scroll(700, x=1150)
        d.caption("Every finding stays a suggestion until a lawyer accepts it. The progress bar counts decisions.", 3.5)
        d.scroll(-700, x=1150)

        # 4. Clauses and missing clauses.
        d.click(page.get_by_role("tab", name=re.compile(r"^Clauses")))
        d.caption("<b>Clause identification.</b> Each clause is labelled, and the card shows which words produced the label.", 4)
        d.click(page.get_by_role("tab", name=re.compile(r"^Missing clauses")))
        d.caption("<b>Missing clauses.</b> Checked against the expected clauses for a supply agreement: no notices clause.", 4)

        # 5. Risks, show in text, decisions.
        d.click(page.get_by_role("tab", name=re.compile(r"^Risks")))
        d.caption("<b>Risk analysis.</b> Six risks, each with a severity, a plain-English reason and the source sentence.", 4)
        # Only the open tab's widgets are visible, so visible elements are the Risks cards.
        d.click(page.get_by_role("button", name="Show in text").first, after=1.2)
        d.caption("<b>Show in text</b> scrolls the contract to the exact sentence, so the lawyer can verify every flag.", 4)
        note = page.get_by_placeholder("Add a note for the file").filter(visible=True).first
        d.type(note, "Ask for 1.5% per month at most.", submit=False)
        d.click(page.get_by_role("button", name="Accept").first, after=1.0)
        d.caption("The lawyer accepts a finding with a note for the file...", 2.5)
        d.click(page.get_by_role("button", name="Edit").nth(1), after=0.6)
        box = page.get_by_label("Your corrected text")
        box.fill("")
        box.press_sequentially("Liability capped at the Contract Value.", delay=40)
        d.click(page.get_by_role("button", name="Save edit"), after=1.0)
        d.caption("...edits another to record the position they will negotiate...", 2.5)
        d.click(page.get_by_role("button", name="Reject").nth(2), after=1.0)
        d.caption("...and rejects one they disagree with. The badges and the progress bar update.", 3.5)

        # 6. Compliance and obligations.
        d.click(page.get_by_role("tab", name=re.compile(r"^Nigerian compliance")))
        d.caption("<b>Nigerian compliance.</b> Indicative checks: English governing law, and arbitration without the Arbitration and Mediation Act 2023.", 4.5)
        d.click(page.get_by_role("tab", name=re.compile(r"^Obligations")))
        d.caption("<b>Obligations and deadlines.</b> Who must do what, by when, with calendar dates where the contract gives an anchor date.", 4.5)

        # 7. New version and comparison.
        d.click(page.get_by_role("button", name="Review another contract"))
        d.caption("<b>Version control.</b> The counterparty sends back a revised draft; we save it as version 2.", 2)
        page.get_by_test_id("stFileUploaderDropzoneInput").set_input_files(SUPPLY_V2)
        expect(page.get_by_role("button", name="Analyse contract")).to_be_visible()
        wait_idle(page)
        d.click(page.get_by_role("combobox", name="Save as a new version of an existing contract (optional)"), after=0.5)
        d.click(page.get_by_role("option", name=re.compile(r"^Supply Agreement - Golden Root")), after=0.5)
        d.click(page.get_by_role("button", name="Analyse contract"), after=1.5)
        expect(page.get_by_role("tab", name="Summary")).to_be_visible()

        # 8. Register, detail, comparison.
        d.nav("Contract Register")
        d.caption("<b>Contract register.</b> Every contract with its type, status, parties, expiry and open high risks.", 3.5)
        d.type(page.get_by_label("Search titles"), "supply")
        d.click(main.get_by_role("button", name="Supply Agreement - Golden Root"), after=1.0)
        d.caption("The contract detail: status, key dates, value and both versions.", 3)
        d.click(page.get_by_role("combobox", name="Status"), after=0.4)
        d.click(page.get_by_role("option", name="Active"), after=0.4)
        d.click(main.get_by_role("button", name=re.compile(r"(^|\s)Save$")), after=1.0)
        d.point(page.get_by_role("heading", name="Compare versions"))
        page.get_by_role("heading", name="Compare versions").evaluate("e => e.scrollIntoView({block: 'start', behavior: 'smooth'})")
        d.pause(1.2)
        d.caption("Side-by-side clause comparison: liability now capped, interest cut to 1.5%, Nigerian law and a Lagos seat.", 5)
        d.scroll(900)
        d.pause(1.5)

        # 9. Deadlines, search, reports, settings.
        d.nav("Deadlines")
        d.click(page.get_by_role("radio", name="90 days"), after=1.0)
        d.caption("<b>Deadlines.</b> A timeline and list of upcoming obligations, with 30, 60 and 90 day views.", 4.5)
        d.nav("Search")
        d.type(page.get_by_placeholder("e.g. indemnify, arbitration, personal data"), "indemnify", submit=False)
        d.click(page.get_by_role("button", name=re.compile(r"(^|\s)Search$")), after=1.0)
        d.caption("<b>Keyword search</b> across every stored contract, with matches highlighted in context.", 4)
        d.nav("Reports")
        d.click(page.get_by_role("combobox", name="Contract"), after=0.4)
        d.click(page.get_by_role("option", name=re.compile(r"^Supply Agreement - Golden Root")), after=1.0)
        d.caption("<b>Reports.</b> A preview of the review report, including the lawyer's decisions and notes.", 3)
        d.scroll(1400)
        d.caption("One click exports the same report as PDF or Word.", 1.5)
        with page.expect_download():
            d.click(page.get_by_role("button", name="Export PDF"), after=1.5)
        d.nav("Settings")
        d.caption("<b>Settings.</b> Firm name, optional password lock, local data controls and delete-all.", 4)
        d.scroll(700)
        d.pause(1.5)

        # 10. Closing card.
        d.caption("")
        d.card("<h1>LexReview <span>NG</span></h1>"
               "<p>Rule-based and transparent. Every finding shows its source and waits for a lawyer's decision.</p>"
               "<p class='k'>Master's Capstone Project</p>"
               "<p>github.com/mtor24/contract-review-ng</p>", 6)

        video = Path(page.video.path())
        context.close()
        browser.close()
        return video, lead_in


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        server = Server(Path(tmp) / "server")
        try:
            prepare(server)
            webm, lead_in = record(server, Path(tmp) / "video")
        finally:
            server.stop()
        target = OUT_DIR / "lexreview-ng-demo.mp4"
        if shutil.which("ffmpeg"):
            # H.264 + yuv420p plays everywhere, including submission portals and PowerPoint.
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{lead_in:.2f}", "-i", str(webm), "-c:v", "libx264",
                            "-preset", "slow", "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                            str(target)], check=True)
        else:
            target = OUT_DIR / "lexreview-ng-demo.webm"
            shutil.copy(webm, target)
        print("saved", target)


if __name__ == "__main__":
    main()
