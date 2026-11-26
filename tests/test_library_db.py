"""SQLite store: passages, highlights, stars, fact-check history, local docs."""
from __future__ import annotations

import pytest

from src.library_db import APP, ZOTERO, HighlightRow, LibraryDB
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


def _own(db):
    return {f.name: f for f in db.folders() if f.source == APP}


def test_own_folders_hold_papers_and_can_be_renamed_and_deleted(db):
    reading = db.add_folder("  読む予定 ")
    db.add_folder("Attention")
    db.set_in_folder(reading, "K1", True)
    db.set_in_folder(reading, "K2", True)
    db.set_in_folder(reading, "K2", True)        # filing twice is harmless
    db.set_in_folder(reading, "K1", False)
    assert _own(db)["読む予定"].keys == {"K2"}
    assert [f.name for f in db.folders()] == ["Attention", "読む予定"]

    db.rename_folder(reading, "読了")
    assert _own(db)["読了"].keys == {"K2"}
    db.delete_folder(reading)
    assert list(_own(db)) == ["Attention"]
    db.set_in_folder(reading, "K3", True)        # folder is gone: no orphan row
    assert all(not f.keys for f in db.folders())


def test_folder_names_must_be_filled_in_and_unique(db):
    first = db.add_folder("Attention")
    other = db.add_folder("Memory")
    with pytest.raises(ValueError):
        db.add_folder("   ")
    with pytest.raises(ValueError):
        db.add_folder("Attention")
    with pytest.raises(ValueError):
        db.rename_folder(other, "Attention")
    assert {f.ref for f in db.folders()} == {str(first), str(other)}


def test_deleting_a_paper_takes_it_out_of_its_folders(db):
    folder = db.add_folder("Attention")
    db.set_in_folder(folder, "K1", True)
    db.set_in_folder(folder, "K2", True)
    db.delete_document("K1", keep_star=True)     # vanished during a sync
    assert _own(db)["Attention"].keys == {"K1", "K2"}
    db.delete_document("K1")
    assert _own(db)["Attention"].keys == {"K2"}


def test_zotero_collections_are_mirrored_with_their_nesting(db):
    mine = db.add_folder("Mine")
    db.set_in_folder(mine, "K9", True)
    cols = [("C1", "Vision", "", ["K1"]), ("C2", "Attention", "C1", ["K2", "K3"])]
    assert db.replace_zotero_collections(cols) is True
    assert db.replace_zotero_collections(cols) is False      # nothing changed
    zotero = {f.ref: f for f in db.folders() if f.source == ZOTERO}
    assert zotero["C2"].parent == zotero["C1"].id and zotero["C1"].parent == ""
    assert zotero["C2"].keys == {"K2", "K3"}

    # A paper moved and a collection removed in Zotero; own folders untouched.
    assert db.replace_zotero_collections([("C1", "Vision", "", ["K1", "K2"])])
    assert [(f.ref, f.keys) for f in db.folders() if f.source == ZOTERO] == [
        ("C1", {"K1", "K2"})]
    assert _own(db)["Mine"].keys == {"K9"}
