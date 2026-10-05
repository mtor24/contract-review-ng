"""CRUD, versions, review decisions, search and reporting over the schema
in storage/db.py. Every function takes an open connection first so tests
can use a temp database.

Conventions:
- Ids are str(uuid.uuid4()); timestamps are UTC ISO strings.
- Dates are stored as ISO "YYYY-MM-DD" strings; money stays integer kobo.
- All SQL is parameterised; user text never reaches a query string.
"""

import json
import re
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone

from storage.db import DECISIONS, STATUSES

# update_contract may only touch these columns.
_EDITABLE_FIELDS = ("title", "status", "type", "effective_date", "expiry_date")

# search() wraps each hit in these; they match char(2) and char(3) in its SQL.
SNIPPET_START = "\x02"
SNIPPET_END = "\x03"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso(d) -> str | None:
    """date -> 'YYYY-MM-DD'; pass strings and None through unchanged."""
    if isinstance(d, date):
        return d.isoformat()
    return d


def _row_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def log(conn: sqlite3.Connection, action: str, contract_id: str | None = None) -> None:
    """Append one row to the activity trail."""
    conn.execute(
        "INSERT INTO activity (id, ts, contract_id, action) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), _now(), contract_id, action),
    )


def save_analysis(
    conn: sqlite3.Connection,
    result: dict,
    filename: str,
    contract_id: str | None = None,
    title: str | None = None,
) -> tuple[str, str]:
    """Store one analyse() result as a new version; returns (contract_id, version_id)."""
    summary = result["summary"]
    now = _now()

    with conn:  # one transaction: contract, version, clauses, findings, obligations
        if contract_id is None:
            contract_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO contracts (id, title, type, parties_json, status,
                    effective_date, expiry_date, value_kobo, currency,
                    created_at, updated_at)
                VALUES (?, ?, ?, ?, 'Under Review', ?, ?, ?, ?, ?, ?)
                """,
                (
                    contract_id,
                    title or summary["title"],
                    result["contract_type"],
                    json.dumps(summary["parties"]),
                    _iso(summary["effective_date"]),
                    _iso(summary["expiry_date"]),
                    summary["value_kobo"],
                    summary["currency"],
                    now,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE contracts SET type = ?, effective_date = ?, expiry_date = ?,
                    value_kobo = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    result["contract_type"],
                    _iso(summary["effective_date"]),
                    _iso(summary["expiry_date"]),
                    summary["value_kobo"],
                    now,
                    contract_id,
                ),
            )

        previous = conn.execute(
            "SELECT MAX(version_no) FROM versions WHERE contract_id = ?",
            (contract_id,),
        ).fetchone()[0]
        version_no = (previous or 0) + 1

        version_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO versions (id, contract_id, version_no, filename, text, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (version_id, contract_id, version_no, filename, result["text"], now),
        )

        for clause, label in zip(result["clauses"], result["labels"]):
            conn.execute(
                """
                INSERT INTO clauses (id, version_id, seq, number, heading, text,
                    label, char_start, char_end)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    version_id,
                    clause.seq,
                    clause.number,
                    clause.heading,
                    clause.text,
                    label,
                    clause.char_start,
                    clause.char_end,
                ),
            )

        for finding in result["findings"]:
            conn.execute(
                """
                INSERT INTO findings (id, version_id, fid, kind, label, name,
                    severity, reason, excerpt, clause_seq, char_start, char_end,
                    status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'suggested')
                """,
                (
                    str(uuid.uuid4()),
                    version_id,
                    finding["fid"],
                    finding["kind"],
                    finding["label"],
                    finding.get("name"),
                    finding["severity"],
                    finding["reason"],
                    finding.get("excerpt", ""),
                    finding.get("clause_seq"),
                    finding.get("char_start"),
                    finding.get("char_end"),
                ),
            )

        for obligation in result["obligations"]:
            conn.execute(
                """
                INSERT INTO obligations (id, version_id, party, text, period_text,
                    due_date, clause_seq)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    version_id,
                    obligation["party"],
                    obligation["excerpt"],
                    obligation.get("period_text", ""),
                    _iso(obligation.get("due_date")),
                    obligation.get("clause_seq"),
                ),
            )

        log(conn, f"Uploaded {filename} (version {version_no})", contract_id)

    return contract_id, version_id


def list_contracts(
    conn: sqlite3.Connection,
    q: str = "",
    type: str | None = None,
    status: str | None = None,
    party: str | None = None,
    expiring_within_days: int | None = None,
    today: date | None = None,
) -> list[dict]:
    """Contracts matching every given filter, with per-contract aggregates."""
    clauses = []
    params: list = []
    if q:
        clauses.append("c.title LIKE ? COLLATE NOCASE")
        params.append(f"%{q}%")
    if type is not None:
        clauses.append("c.type = ?")
        params.append(type)
    if status is not None:
        clauses.append("c.status = ?")
        params.append(status)
    if party:
        clauses.append("c.parties_json LIKE ? COLLATE NOCASE")
        params.append(f"%{party}%")
    if expiring_within_days is not None:
        today = today or date.today()
        clauses.append("c.expiry_date IS NOT NULL AND c.expiry_date <= ?")
        params.append((today + timedelta(days=expiring_within_days)).isoformat())
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    rows = conn.execute(
        f"""
        SELECT c.*,
            (SELECT COUNT(*) FROM versions v WHERE v.contract_id = c.id) AS versions,
            (SELECT v.id FROM versions v WHERE v.contract_id = c.id
             ORDER BY v.version_no DESC LIMIT 1) AS latest_version_id
        FROM contracts c
        {where}
        ORDER BY c.title
        """,
        params,
    ).fetchall()

    result = [_row_dict(r) for r in rows]
    for row in result:
        # Same shape as get_contract(): callers get a list, never raw JSON.
        row["parties"] = json.loads(row.pop("parties_json"))
        latest = row["latest_version_id"]
        if latest is None:
            row["open_high"] = 0
        else:
            row["open_high"] = conn.execute(
                """
                SELECT COUNT(*) FROM findings
                WHERE version_id = ? AND severity = 'High'
                  AND kind IN ('risk', 'missing', 'compliance')
                  AND status != 'rejected'
                """,
                (latest,),
            ).fetchone()[0]
    return result


def get_contract(conn: sqlite3.Connection, contract_id: str) -> dict | None:
    """One contract by id, with parties decoded from JSON."""
    row = conn.execute(
        "SELECT * FROM contracts WHERE id = ?", (contract_id,)
    ).fetchone()
    if row is None:
        return None
    result = _row_dict(row)
    result["parties"] = json.loads(result.pop("parties_json"))
    return result


def update_contract(conn: sqlite3.Connection, contract_id: str, **fields) -> None:
    """Update editable contract fields; logs what changed."""
    unknown = set(fields) - set(_EDITABLE_FIELDS)
    if unknown:
        raise ValueError(f"Unknown contract fields: {sorted(unknown)}")
    if "status" in fields and fields["status"] not in STATUSES:
        raise ValueError(f"Invalid status: {fields['status']}")
    if not fields:
        return

    assignments = ", ".join(f"{name} = ?" for name in fields)
    params = [fields[name] for name in fields]
    with conn:
        conn.execute(
            f"UPDATE contracts SET {assignments}, updated_at = ? WHERE id = ?",
            (*params, _now(), contract_id),
        )
        changes = ", ".join(f"{name} -> {fields[name]}" for name in fields)
        log(conn, f"Updated contract: {changes}", contract_id)


def list_versions(conn: sqlite3.Connection, contract_id: str) -> list[dict]:
    """Every version of a contract, oldest first."""
    rows = conn.execute(
        "SELECT * FROM versions WHERE contract_id = ? ORDER BY version_no",
        (contract_id,),
    ).fetchall()
    return [_row_dict(r) for r in rows]


def get_version(conn: sqlite3.Connection, version_id: str) -> dict:
    """One version with its clauses (by seq), findings and obligations."""
    row = conn.execute(
        "SELECT * FROM versions WHERE id = ?", (version_id,)
    ).fetchone()
    if row is None:
        return None
    result = _row_dict(row)
    result["clauses"] = [
        _row_dict(r)
        for r in conn.execute(
            "SELECT * FROM clauses WHERE version_id = ? ORDER BY seq", (version_id,)
        )
    ]
    result["findings"] = [
        _row_dict(r)
        for r in conn.execute(
            "SELECT * FROM findings WHERE version_id = ?", (version_id,)
        )
    ]
    result["obligations"] = [
        _row_dict(r)
        for r in conn.execute(
            "SELECT * FROM obligations WHERE version_id = ?", (version_id,)
        )
    ]
    return result


def set_decision(
    conn: sqlite3.Connection,
    version_id: str,
    fid: str,
    status: str,
    note: str = "",
    edited_text: str | None = None,
) -> None:
    """Record the reviewer's decision on one finding. edited_text is only
    written when given, so accepting an edited finding keeps the edit."""
    if status not in DECISIONS:
        raise ValueError(f"Invalid decision: {status}")
    with conn:
        conn.execute(
            """
            UPDATE findings SET status = ?, note = ?,
                edited_text = COALESCE(?, edited_text), decided_at = ?
            WHERE version_id = ? AND fid = ?
            """,
            (status, note, edited_text, _now(), version_id, fid),
        )
        contract_id = conn.execute(
            "SELECT contract_id FROM versions WHERE id = ?", (version_id,)
        ).fetchone()[0]
        log(conn, f"{status.capitalize()} finding {fid}", contract_id)


def review_progress(conn: sqlite3.Connection, version_id: str) -> tuple[int, int]:
    """(reviewed, total) findings; reviewed means status != 'suggested'."""
    reviewed, total = conn.execute(
        """
        SELECT COALESCE(SUM(status != 'suggested'), 0), COUNT(*)
        FROM findings WHERE version_id = ?
        """,
        (version_id,),
    ).fetchone()
    return reviewed, total


def _latest_versions_subquery() -> str:
    # (contract_id, id) pairs for the highest version_no of each contract.
    return """
        SELECT v.contract_id, v.id
        FROM versions v
        JOIN (SELECT contract_id, MAX(version_no) AS max_no
              FROM versions GROUP BY contract_id) latest
          ON latest.contract_id = v.contract_id AND latest.max_no = v.version_no
    """


def upcoming_obligations(
    conn: sqlite3.Connection, today: date, days: int
) -> list[dict]:
    """Obligations of each contract's latest version due within the window."""
    horizon = (today + timedelta(days=days)).isoformat()
    rows = conn.execute(
        f"""
        SELECT o.*, c.title AS contract_title, c.id AS contract_id
        FROM obligations o
        JOIN ({_latest_versions_subquery()}) latest ON latest.id = o.version_id
        JOIN contracts c ON c.id = latest.contract_id
        WHERE o.due_date IS NOT NULL
          AND o.due_date >= ? AND o.due_date <= ?
        ORDER BY o.due_date
        """,
        (today.isoformat(), horizon),
    ).fetchall()
    return [_row_dict(r) for r in rows]


def dashboard_counts(conn: sqlite3.Connection, today: date) -> dict:
    """Headline numbers for the dashboard."""
    horizon = (today + timedelta(days=30)).isoformat()
    return {
        "contracts": conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0],
        "under_review": conn.execute(
            "SELECT COUNT(*) FROM contracts WHERE status = 'Under Review'"
        ).fetchone()[0],
        "open_high": conn.execute(
            f"""
            SELECT COUNT(*) FROM findings f
            JOIN ({_latest_versions_subquery()}) latest ON latest.id = f.version_id
            WHERE f.severity = 'High'
              AND f.kind IN ('risk', 'missing', 'compliance')
              AND f.status != 'rejected'
            """
        ).fetchone()[0],
        "deadlines_30": conn.execute(
            f"""
            SELECT COUNT(*) FROM obligations o
            JOIN ({_latest_versions_subquery()}) latest ON latest.id = o.version_id
            WHERE o.due_date IS NOT NULL
              AND o.due_date >= ? AND o.due_date <= ?
            """,
            (today.isoformat(), horizon),
        ).fetchone()[0],
    }


def risk_by_type(conn: sqlite3.Connection) -> list[dict]:
    """Open risk finding counts grouped by contract type and severity."""
    rows = conn.execute(
        f"""
        SELECT c.type, f.severity, COUNT(*) AS count
        FROM findings f
        JOIN ({_latest_versions_subquery()}) latest ON latest.id = f.version_id
        JOIN contracts c ON c.id = latest.contract_id
        WHERE f.kind = 'risk' AND f.status != 'rejected'
        GROUP BY c.type, f.severity
        ORDER BY c.type, f.severity
        """
    ).fetchall()
    return [_row_dict(r) for r in rows]


def recent_activity(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """Newest activity first, with the contract title when it still exists."""
    rows = conn.execute(
        """
        SELECT a.*, c.title AS contract_title
        FROM activity a
        LEFT JOIN contracts c ON c.id = a.contract_id
        ORDER BY a.ts DESC, a.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_row_dict(r) for r in rows]


def search(conn: sqlite3.Connection, query: str, limit: int = 50) -> list[dict]:
    """FTS5 search over version text; user input is quoted token by token so
    it can never become query syntax.

    Tokens are runs of Unicode word characters, the same way the FTS
    tokenizer splits text: "non-compete" -> "non" "compete", "N5,000" ->
    "N5" "000", and accented names keep their letters. Hits in the snippet
    are wrapped in SNIPPET_START and SNIPPET_END, control characters that
    never appear in a contract, so the UI cannot confuse them with literal
    brackets in the text."""
    # \w never matches a double quote; the replace is a second guard so a
    # token can never close its own quotes.
    tokens = [t.replace('"', "") for t in re.findall(r"\w+", query, re.UNICODE)]
    if not tokens:
        return []
    match = " ".join(f'"{t}"' for t in tokens)
    rows = conn.execute(
        """
        SELECT s.contract_id, s.version_id, c.title AS contract_title,
            v.version_no,
            snippet(search_index, 2, char(2), char(3), ' ... ', 12) AS snippet
        FROM search_index s
        JOIN contracts c ON c.id = s.contract_id
        JOIN versions v ON v.id = s.version_id
        WHERE search_index MATCH ?
        ORDER BY bm25(search_index)
        LIMIT ?
        """,
        (match, limit),
    ).fetchall()
    return [_row_dict(r) for r in rows]


def delete_contract(conn: sqlite3.Connection, contract_id: str) -> None:
    """Delete one contract; ON DELETE CASCADE and the versions_ad trigger
    remove every version, clause, finding, obligation, activity and search
    row that belongs to it."""
    with conn:
        conn.execute("DELETE FROM contracts WHERE id = ?", (contract_id,))
        # The trail keeps one untitled entry; the data itself is gone.
        log(conn, "Deleted a contract")


def delete_all_data(conn: sqlite3.Connection) -> None:
    """Wipe every contract and activity row, then VACUUM so freed pages
    leave the file entirely."""
    with conn:
        conn.execute("DELETE FROM contracts")
        conn.execute("DELETE FROM activity")
    # VACUUM cannot run inside a transaction.
    conn.execute("VACUUM")
