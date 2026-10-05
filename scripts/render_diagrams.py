"""Render every diagram in docs/diagrams/*.html to a PNG next to it (developer tool only).

Run from the project root:  python scripts/render_diagrams.py
Works offline: the diagrams are plain HTML and CSS using the bundled Inter font.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

DIAGRAMS = Path(__file__).resolve().parent.parent / "docs" / "diagrams"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # Twice the pixel density so the text stays sharp when the image is scaled in a document.
        page = browser.new_page(viewport={"width": 1400, "height": 1000}, device_scale_factor=2)
        for source in sorted(DIAGRAMS.glob("*.html")):
            page.goto(source.as_uri())
            page.wait_for_function("document.fonts.status === 'loaded'")
            target = source.with_suffix(".png")
            page.locator("#diagram").screenshot(path=str(target))
            print("saved", target.name)
        browser.close()


if __name__ == "__main__":
    main()
