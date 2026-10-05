"""SQLite connection and schema. Everything lives in one local file (data/lexreview.db).

Design notes for the thesis:
- Public ids are random UUIDs, never auto-increment numbers, so ids reveal nothing about volume.
- Money is stored as integer kobo plus an ISO currency code; floats are never used for money.
- Deleting a contract cascades to every version, clause, finding, obligation and activity row,
  secure_delete overwrites the freed pages, and the search index is told to forget deleted
  words too, so deleted text does not linger in the file.
"""

import os
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "lexreview.db"

STATUSES = ("Draft", "Under Review", "Executed", "Active", "Expiring", "Terminated")
DECISIONS = ("suggested", "accepted", "rejected", "edited")

SCHEMA = """
CREATE TABLE IF NOT EXISTS contracts (
    id             TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    type           TEXT NOT NULL,
    parties_json   TEXT NOT NULL DEFAULT '[]',
    status         TEXT NOT NULL DEFAULT 'Under Review'
                   CHECK (status IN ('Draft','Under Review','Executed','Active','Expiring','Terminated')),
    effective_date TEXT,
    expiry_date    TEXT,
    value_kobo     INTEGER CHECK (value_kobo IS NULL OR value_kobo >= 0),
    currency       TEXT NOT NULL DEFAULT 'NGN',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
    id          TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    version_no  INTEGER NOT NULL,
    filename    TEXT NOT NULL,
    text        TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    UNIQUE (contract_id, version_no)
);

CREATE TABLE IF NOT EXISTS clauses (
    id         TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    seq        INTEGER NOT NULL,
    number     TEXT,
    heading    TEXT,
    text       TEXT NOT NULL,
    label      TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    id          TEXT PRIMARY KEY,
    version_id  TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    fid         TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('clause','missing','risk','compliance','obligation')),
    label       TEXT NOT NULL,
    name        TEXT,
    severity    TEXT NOT NULL,
    reason      TEXT NOT NULL,
    excerpt     TEXT NOT NULL DEFAULT '',
    clause_seq  INTEGER,
    char_start  INTEGER,
    char_end    INTEGER,
    status      TEXT NOT NULL DEFAULT 'suggested'
                CHECK (status IN ('suggested','accepted','rejected','edited')),
    note        TEXT NOT NULL DEFAULT '',
    edited_text TEXT NOT NULL DEFAULT '',
    decided_at  TEXT,
    UNIQUE (version_id, fid)
);

CREATE TABLE IF NOT EXISTS obligations (
    id          TEXT PRIMARY KEY,
    version_id  TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    party       TEXT NOT NULL,
    text        TEXT NOT NULL,
    period_text TEXT NOT NULL DEFAULT '',
    due_date    TEXT,
    clause_seq  INTEGER
);

CREATE TABLE IF NOT EXISTS activity (
    id          TEXT PRIMARY KEY,
    ts          TEXT NOT NULL,
    contract_id TEXT REFERENCES contracts(id) ON DELETE CASCADE,
    action      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_versions_contract ON versions(contract_id);
CREATE INDEX IF NOT EXISTS idx_findings_version ON findings(version_id);
CREATE INDEX IF NOT EXISTS idx_obligations_due ON obligations(due_date);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(ts);

-- Keyword search index over every stored version. Kept in sync by triggers so a cascaded
-- delete of a contract also removes its text from the index.
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    version_id UNINDEXED,
    contract_id UNINDEXED,
    text,
    tokenize = 'porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS versions_ai AFTER INSERT ON versions BEGIN
    INSERT INTO search_index (version_id, contract_id, text) VALUES (new.id, new.contract_id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS versions_ad AFTER DELETE ON versions BEGIN
    DELETE FROM search_index WHERE version_id = old.id;
END;
"""


def db_path() -> Path:
    # LEXREVIEW_DB lets tests point at a throwaway file instead of the real register.
    return Path(os.environ.get("LEXREVIEW_DB", DEFAULT_DB))


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the database with foreign keys and secure delete on, creating the schema if needed."""
    path = Path(path) if path else db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # SQLite leaves foreign keys off by default; cascades depend on this.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA secure_delete = ON")
    conn.executescript(SCHEMA)
    _purge_deleted_search_terms(conn)
    return conn


def _purge_deleted_search_terms(conn: sqlite3.Connection) -> None:
    """Make sure deleted contract text does not survive inside the search index.

    PRAGMA secure_delete wipes freed pages, but FTS5 keeps a deleted row's words in its
    index segments until they are merged. FTS5's own secure-delete option (SQLite 3.44+)
    removes them at delete time. On older SQLite we fall back to merging the segments
    after every contract delete, which drops the deleted entries.
    """
    try:
        conn.execute("INSERT INTO search_index(search_index, rank) VALUES ('secure-delete', 1)")
    except sqlite3.OperationalError:
        conn.execute(
            "CREATE TRIGGER IF NOT EXISTS contracts_ad_optimize AFTER DELETE ON contracts BEGIN "
            "INSERT INTO search_index(search_index) VALUES ('optimize'); END"
        )
    conn.commit()
