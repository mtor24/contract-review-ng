"""Tests for storage/models.py against temp databases, using real pipeline
output from the sample contracts."""

from datetime import date

import pytest

from core.pipeline import analyse
from storage import db, models


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "t.db")
    yield connection
    connection.close()


def _analyse(samples_dir, name):
    return analyse((samples_dir / name).read_text(encoding="utf-8"))


def _save_supply(conn, samples_dir):
    result = _analyse(samples_dir, "supply_agreement.txt")
    return models.save_analysis(conn, result, "supply_agreement.txt")


def test_save_analysis_creates_contract_and_version(conn, samples_dir):
    contract_id, version_id = _save_supply(conn, samples_dir)

    contract = models.get_contract(conn, contract_id)
    assert contract["title"] == "SUPPLY AGREEMENT"
    assert contract["status"] == "Under Review"
    assert isinstance(contract["parties"], list) and contract["parties"]

    version = models.get_version(conn, version_id)
    assert version["version_no"] == 1
    assert version["filename"] == "supply_agreement.txt"
    assert version["clauses"] and version["findings"] and version["obligations"]
    # Clauses come back in document order with their labels attached.
    assert [c["seq"] for c in version["clauses"]] == sorted(
        c["seq"] for c in version["clauses"]
    )
    assert all("label" in c for c in version["clauses"])
    # Findings start life as suggestions.
    assert all(f["status"] == "suggested" for f in version["findings"])

    activity = models.recent_activity(conn)
    assert activity[0]["action"] == "Uploaded supply_agreement.txt (version 1)"
    assert activity[0]["contract_title"] == "SUPPLY AGREEMENT"


def test_second_save_same_contract_makes_version_2(conn, samples_dir):
    contract_id, _ = _save_supply(conn, samples_dir)
    result = _analyse(samples_dir, "supply_agreement.txt")
    _, version2 = models.save_analysis(
        conn, result, "supply_v2.txt", contract_id=contract_id
    )

    versions = models.list_versions(conn, contract_id)
    assert [v["version_no"] for v in versions] == [1, 2]
    assert versions[1]["id"] == version2
    assert versions[1]["filename"] == "supply_v2.txt"


def test_list_contracts_filters_and_open_high(conn, samples_dir):
    supply_id, _ = _save_supply(conn, samples_dir)
    nda = _analyse(samples_dir, "nda.txt")
    models.save_analysis(conn, nda, "nda.txt")

    by_type = models.list_contracts(conn, type="supply")
    assert [c["id"] for c in by_type] == [supply_id]

    by_status = models.list_contracts(conn, status="Under Review")
    assert len(by_status) == 2
    assert models.list_contracts(conn, status="Executed") == []

    by_q = models.list_contracts(conn, q="supply")
    assert [c["id"] for c in by_q] == [supply_id]

    by_party = models.list_contracts(conn, party="Buyer")
    assert supply_id in [c["id"] for c in by_party]

    supply_row = models.get_contract(conn, supply_id)
    supply_listing = next(c for c in models.list_contracts(conn) if c["id"] == supply_id)
    assert supply_listing["versions"] == 1
    assert supply_listing["latest_version_id"]
    assert supply_listing["open_high"] > 0
    assert supply_row["type"] == "supply"


def test_set_decision_and_progress(conn, samples_dir):
    _, version_id = _save_supply(conn, samples_dir)
    version = models.get_version(conn, version_id)
    fid = version["findings"][0]["fid"]
    total = len(version["findings"])

    assert models.review_progress(conn, version_id) == (0, total)
    models.set_decision(conn, version_id, fid, "accepted", note="looks right")
    reviewed, still_total = models.review_progress(conn, version_id)
    assert (reviewed, still_total) == (1, total)

    finding = next(
        f for f in models.get_version(conn, version_id)["findings"] if f["fid"] == fid
    )
    assert finding["status"] == "accepted"
    assert finding["note"] == "looks right"
    assert finding["decided_at"]

    with pytest.raises(ValueError):
        models.set_decision(conn, version_id, fid, "maybe")


def test_update_contract_validation(conn, samples_dir):
    contract_id, _ = _save_supply(conn, samples_dir)

    with pytest.raises(ValueError):
        models.update_contract(conn, contract_id, value_kobo=5)
    with pytest.raises(ValueError):
        models.update_contract(conn, contract_id, status="Banana")

    models.update_contract(conn, contract_id, status="Active", title="New Title")
    contract = models.get_contract(conn, contract_id)
    assert contract["status"] == "Active"
    assert contract["title"] == "New Title"
    assert any(
        "Updated contract" in a["action"] for a in models.recent_activity(conn)
    )


def test_search_finds_supply_and_ignores_injection(conn, samples_dir):
    models.save_analysis(
        conn, _analyse(samples_dir, "supply_agreement.txt"), "supply_agreement.txt"
    )
    models.save_analysis(conn, _analyse(samples_dir, "nda.txt"), "nda.txt")

    hits = models.search(conn, "indemnify")
    assert hits
    assert all(h["contract_title"] for h in hits)
    assert any("SUPPLY AGREEMENT" in h["contract_title"] for h in hits)
    assert models.SNIPPET_START in hits[0]["snippet"] and models.SNIPPET_END in hits[0]["snippet"]

    injected = models.search(conn, '"; DELETE FROM contracts; --')
    assert isinstance(injected, list)
    assert conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 2


def test_upcoming_obligations_loan_first_instalment(conn, samples_dir):
    loan = _analyse(samples_dir, "loan_agreement.txt")
    models.save_analysis(conn, loan, "loan_agreement.txt")

    upcoming = models.upcoming_obligations(conn, today=date(2026, 12, 1), days=30)
    due_dates = [o["due_date"] for o in upcoming]
    assert "2026-12-15" in due_dates
    first = next(o for o in upcoming if o["due_date"] == "2026-12-15")
    assert "LOAN AGREEMENT" in first["contract_title"]
    assert first["contract_id"]
    assert due_dates == sorted(due_dates)


def test_delete_contract_cascades_everything(conn, samples_dir):
    contract_id, version_id = _save_supply(conn, samples_dir)
    models.delete_contract(conn, contract_id)

    assert models.get_contract(conn, contract_id) is None
    assert conn.execute(
        "SELECT COUNT(*) FROM versions WHERE contract_id = ?", (contract_id,)
    ).fetchone()[0] == 0
    for table in ("clauses", "findings", "obligations"):
        assert conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE version_id = ?", (version_id,)
        ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM activity WHERE contract_id = ?", (contract_id,)
    ).fetchone()[0] == 0
    assert models.search(conn, "indemnify") == []
    # The deletion itself is still logged, without a contract.
    actions = [a["action"] for a in models.recent_activity(conn)]
    assert "Deleted a contract" in actions


def test_delete_all_data_empties_every_table(conn, samples_dir):
    _save_supply(conn, samples_dir)
    models.save_analysis(conn, _analyse(samples_dir, "nda.txt"), "nda.txt")
    models.delete_all_data(conn)

    for table in (
        "contracts",
        "versions",
        "clauses",
        "findings",
        "obligations",
        "activity",
        "search_index",
    ):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_money_stored_as_integer_kobo(conn, samples_dir):
    contract_id, _ = _save_supply(conn, samples_dir)
    contract = models.get_contract(conn, contract_id)
    assert isinstance(contract["value_kobo"], int)
    assert contract["value_kobo"] == 12_000_000_000


def test_dashboard_and_risk_by_type(conn, samples_dir):
    _save_supply(conn, samples_dir)
    counts = models.dashboard_counts(conn, today=date(2026, 3, 1))
    assert counts["contracts"] == 1
    assert counts["under_review"] == 1
    assert counts["open_high"] > 0

    rows = models.risk_by_type(conn)
    assert all(set(r) == {"type", "severity", "count"} for r in rows)
    assert any(r["type"] == "supply" for r in rows)


def test_list_contracts_decodes_parties(conn, samples_dir):
    _save_supply(conn, samples_dir)
    row = models.list_contracts(conn)[0]
    assert "parties_json" not in row
    assert any(p["role"] == "Supplier" for p in row["parties"])
