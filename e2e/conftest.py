"""End-to-end harness: real Streamlit servers driven by a real browser.

Run with:  python -m pytest e2e -q   (needs: python -m playwright install chromium)

Each server gets its own throwaway database and settings file under pytest's tmp dir,
seeded with the synthetic sample contracts, so tests never touch data/lexreview.db.
The "locked" server has the password lock switched on with a random password made
fresh for every run; it is never written into the repository.

Every test carries @pytest.mark.cell("<feature id>", "<role>"). At the end of the run
we write e2e/results.json in the shape of Playwright's JSON reporter, so the matrix
report script can map results onto the coverage matrix.
"""

import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
import yaml
from playwright.sync_api import Page, expect, sync_playwright

# Streamlit reruns the whole script per interaction; give the UI time to settle.
expect.set_options(timeout=15_000)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RESULTS_PATH = ROOT / "e2e" / "results.json"
_results: list[dict] = []


def pytest_configure(config):
    config.addinivalue_line("markers", "cell(feature, role): coverage matrix cell this test proves")


# ---------------------------------------------------------------- servers


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _seed(db_path: Path) -> None:
    from core.pipeline import analyse
    from storage.db import connect
    from storage.models import save_analysis

    conn = connect(db_path)
    for path in sorted((ROOT / "data" / "samples").glob("*.txt")):
        result = analyse(path.read_text(encoding="utf-8"))
        save_analysis(conn, result, path.name, title=result["summary"]["title"].title())
    conn.close()


class Server:
    def __init__(self, workdir: Path, locked_password: str | None = None):
        workdir.mkdir(parents=True, exist_ok=True)
        self.db = workdir / "e2e.db"
        self.local_config = workdir / "local_config.yaml"
        _seed(self.db)
        if locked_password:
            from core.auth import hash_password

            cfg = {"firm_name": "E2E Test Chambers", "auth": hash_password(locked_password),
                   "features": {"tfidf_fallback": False, "login_enabled": True}}
            self.local_config.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        self.port = _free_port()
        self.url = f"http://localhost:{self.port}"
        env = {**os.environ, "LEXREVIEW_DB": str(self.db), "LEXREVIEW_LOCAL_CONFIG": str(self.local_config)}
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(self.port),
             "--server.headless", "true", "--browser.gatherUsageStats", "false"],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                if urllib.request.urlopen(f"{self.url}/_stcore/health", timeout=2).status == 200:
                    return
            except OSError:
                time.sleep(0.5)
        self.stop()
        raise RuntimeError("Streamlit server did not start")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture(scope="session")
def owner_server(tmp_path_factory):
    server = Server(tmp_path_factory.mktemp("owner"))
    yield server
    server.stop()


@pytest.fixture(scope="session")
def locked_password() -> str:
    return secrets.token_urlsafe(16)


@pytest.fixture(scope="session")
def locked_server(tmp_path_factory, locked_password):
    server = Server(tmp_path_factory.mktemp("locked"), locked_password=locked_password)
    yield server
    server.stop()


@pytest.fixture
def fresh_server(tmp_path):
    """A private server for destructive tests (delete all), so other tests keep their data."""
    server = Server(tmp_path / "fresh")
    yield server
    server.stop()


# ---------------------------------------------------------------- browser


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser) -> Page:
    context = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
    pg = context.new_page()
    pg.set_default_timeout(30_000)
    yield pg
    context.close()


def wait_idle(page: Page) -> None:
    """Wait until Streamlit has finished rerunning and the page has stopped changing.

    A rerun may not have started when we look, and elements render progressively, so we
    require the page to be continuously idle (no running indicator, no stale elements,
    no skeleton placeholders) for half a second. The check runs in the browser, so it
    waits on real state rather than sleeping a fixed time.
    """
    page.wait_for_selector('[data-testid="stMainBlockContainer"] [data-testid="stElementContainer"]')
    page.evaluate("window.__lexIdleSince = undefined")  # forget any idle period from before the click
    page.wait_for_function(
        """() => {
            const busy = document.querySelector('[data-testid="stStatusWidget"]')
                || document.querySelector('[data-stale="true"]')
                || document.querySelector('[data-testid="stSkeleton"]');
            const now = performance.now();
            if (busy || window.__lexIdleSince === undefined) { window.__lexIdleSince = busy ? undefined : now; return false; }
            return now - window.__lexIdleSince >= 500;
        }""",
        timeout=60_000,
        polling=100,
    )


def open_page(page: Page, base_url: str, path: str = "") -> None:
    page.goto(f"{base_url}/{path.lstrip('/')}")
    wait_idle(page)


def sign_in(page: Page, base_url: str, password: str) -> None:
    open_page(page, base_url)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
    wait_idle(page)


# Re-exported for the specs.
__all__ = ["expect", "open_page", "sign_in", "wait_idle"]


# ---------------------------------------------------------------- results.json


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    marker = item.get_closest_marker("cell")
    if marker is None:
        return
    feature, role = marker.args
    title = f"{item.name} @{feature} @role:{role}"
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        status = {"passed": "expected", "failed": "unexpected", "skipped": "skipped"}[report.outcome]
        _results.append({"title": title, "tags": [f"@{feature}", f"@role:{role}"], "tests": [{"status": status}]})


def pytest_sessionfinish(session, exitstatus):
    if _results:
        RESULTS_PATH.write_text(json.dumps({"suites": [{"title": "e2e", "specs": _results}]}, indent=2), encoding="utf-8")


def unique(prefix: str) -> str:
    """Unique, readable names so tests never depend on each other's data."""
    return f"{prefix} {re.sub(r'[^0-9]', '', str(time.time_ns()))[-8:]}"
