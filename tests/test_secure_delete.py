"""Deleted contract text must not stay readable inside the database file."""

from core.pipeline import analyse
from storage import models
from storage.db import connect

SECRET = "Zyxwvutsrq"  # a word that appears nowhere else


def _store(conn, word):
    text = (open("data/samples/nda.txt", encoding="utf-8").read()
            .replace("LAGOS DIGITAL MEDIA PARTNERS LIMITED", f"{word.upper()} HOLDINGS LIMITED"))
    return models.save_analysis(conn, analyse(text), "nda.txt", title="NDA")[0]


def test_delete_contract_leaves_no_trace_in_file(tmp_path):
    path = tmp_path / "t.db"
    conn = connect(path)
    contract_id = _store(conn, SECRET)
    assert models.search(conn, SECRET)
    models.delete_contract(conn, contract_id)
    conn.close()
    raw = path.read_bytes().lower()
    assert SECRET.lower().encode() not in raw


def test_delete_all_data_leaves_no_trace_in_file(tmp_path):
    path = tmp_path / "t.db"
    conn = connect(path)
    _store(conn, SECRET)
    models.delete_all_data(conn)
    conn.close()
    assert SECRET.lower().encode() not in path.read_bytes().lower()
