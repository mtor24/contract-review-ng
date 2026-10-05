"""Dashboard: KPIs, deadlines, risk chart, activity and the institution band."""

import pytest

from e2e.conftest import expect, open_page, unique, wait_idle


def _analyse_upload(page, base_url: str, path, title: str) -> None:
    """Upload a contract through the Review page so the activity trail records it."""
    open_page(page, base_url, "review")
    page.get_by_test_id("stFileUploaderDropzoneInput").set_input_files(str(path))
    expect(page.get_by_role("button", name="Analyse contract")).to_be_visible()
    wait_idle(page)
    page.get_by_label("Title", exact=True).fill(title)
    page.get_by_role("button", name="Analyse contract").click()
    expect(page.get_by_role("tab", name="Summary")).to_be_visible()
    wait_idle(page)


@pytest.mark.cell("dashboard.view", "owner")
def test_dashboard_kpis_sections_logos_and_activity(page, owner_server):
    title = unique("NDA")
    _analyse_upload(page, owner_server.url, "data/samples/nda.txt", title)

    open_page(page, owner_server.url)
    main = page.get_by_test_id("stMain")

    # Four KPI metrics with their labels and numbers.
    metrics = main.get_by_test_id("stMetric")
    expect(metrics).to_have_count(4)
    for label in (
        "Contracts stored",
        "Under review",
        "High-risk flags open",
        "Deadlines in next 30 days",
    ):
        expect(main.get_by_test_id("stMetric").filter(has_text=label)).to_be_visible()

    # Sections and the institution band.
    expect(main.get_by_role("heading", name="Upcoming deadlines")).to_be_visible()
    expect(main.get_by_role("heading", name="Risks by contract type")).to_be_visible()
    expect(main.get_by_role("heading", name="Recent activity")).to_be_visible()
    expect(
        main.get_by_role(
            "img", name="European Global Institute of Innovation and Technology"
        )
    ).to_be_visible()
    expect(
        main.get_by_role("img", name="Docenti Global Business School")
    ).to_be_visible()

    # The upload this test just made appears in Recent activity.
    activity = main.get_by_text(f"Uploaded nda.txt (version 1) - {title}")
    expect(activity.first).to_be_visible()


@pytest.mark.cell("dashboard.view", "owner")
def test_dashboard_contracts_stored_shows_seven(page, fresh_server):
    open_page(page, fresh_server.url)
    metric = page.get_by_test_id("stMain").get_by_test_id("stMetric").filter(
        has_text="Contracts stored"
    )
    expect(metric).to_be_visible()
    expect(metric.get_by_test_id("stMetricValue")).to_have_text("7")
