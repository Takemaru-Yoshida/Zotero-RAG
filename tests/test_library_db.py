"""SQLite store: passages, highlights, stars, fact-check history, local docs."""
from __future__ import annotations

import pytest

from src.library_db import HighlightRow, LibraryDB
from src.local_library import is_local

pytestmark = pytest.mark.unit


@pytest.fixture
def db(tmp_path):
    return LibraryDB(tmp_path / "library.db")


def test_chunks_round_trip_in_order(db):
    db.replace_chunks("K1", [(1, "first"), (1, "second"), (2, "third")])
    rows = db.get_chunks("K1")
    assert [(r.idx, r.page, r.text) for r in rows] == [
        (0, 1, "first"), (1, 1, "second"), (2, 2, "third")]
    assert db.get_chunk("K1", 2).text == "third"
    assert db.get_chunk("K1", 9) is None
    assert db.chunk_counts() == {"K1": 3}


def test_reindexing_a_paper_drops_its_stale_highlights(db):
    db.replace_chunks("K1", [(1, "old text")])
    db.set_highlights("K1", [HighlightRow("K1", 0, "old text", "reason", 0.9)])
    assert len(db.get_highlights("K1")) == 1
    db.replace_chunks("K1", [(1, "new text")])
    assert db.get_highlights("K1") == []


def test_delete_document_removes_everything(db):
    db.replace_chunks("K1", [(1, "text")])
    db.toggle_star("K1")
    db.delete_document("K1")
    assert db.get_chunks("K1") == []
    assert db.starred() == set()


def test_star_survives_when_a_paper_vanishes_during_sync(db):
    db.replace_chunks("K1", [(1, "text")])
    db.toggle_star("K1")
    db.delete_document("K1", keep_star=True)
    assert db.get_chunks("K1") == []
    assert db.starred() == {"K1"}


def test_star_toggle(db):
    assert db.toggle_star("K1") is True
    assert db.starred() == {"K1"}
    assert db.toggle_star("K1") is False
    assert db.starred() == set()


def test_factcheck_history_newest_first(db):
    db.add_factcheck("first", "text one", [{"verdict": "supported"}])
    db.add_factcheck("second", "text two",
                     [{"verdict": "refuted"}, {"verdict": "not_found"}])
    runs = db.list_factchecks()
    assert [r.title for r in runs] == ["second", "first"]
    assert [x["verdict"] for x in runs[0].results] == ["refuted", "not_found"]
    assert len(runs[0].created_at) == 19   # "YYYY-MM-DD HH:MM:SS"


def test_local_docs_round_trip(db):
    doc = {"key": "LOCAL-ABC", "title": "論文タイトル", "authors": ["太郎 田中"],
           "year": "2021", "tags": ["注意"], "pdf_path": "/tmp/x.pdf",
           "fulltext": "body", "date_added": "2026-01-01 00:00:00",
           "date_modified": "2026-01-01 00:00:00"}
    db.upsert_local_doc(doc)
    stored = db.local_doc("LOCAL-ABC")
    assert stored["authors"] == ["太郎 田中"] and stored["tags"] == ["注意"]
    assert stored["venue"] == ""            # unset fields default to empty
    stored["year"] = "2022"
    db.upsert_local_doc(stored)
    assert [d["year"] for d in db.local_docs()] == ["2022"]
    db.delete_local_doc("LOCAL-ABC")
    assert db.local_doc("LOCAL-ABC") is None


def test_local_key_prefix():
    assert is_local("LOCAL-ABC") and not is_local("A55VM9XZ")
