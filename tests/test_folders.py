"""Folder tree: display order, papers of a folder, unfiled papers."""
from __future__ import annotations

import pytest

from src.folders import filed, members, tree
from src.library_db import APP, ZOTERO, FolderRow

pytestmark = pytest.mark.unit


def _folder(ref, parent="", keys=(), source=ZOTERO):
    return FolderRow(source, ref, ref.lower(),
                     f"{source}:{parent}" if parent else "", frozenset(keys))


FOLDERS = [
    _folder("A", keys={"K1"}),
    _folder("A1", parent="A", keys={"K2"}),
    _folder("A1X", parent="A1", keys={"K3"}),
    _folder("B", keys={"K1", "K4"}),
    _folder("7", keys={"K5"}, source=APP),
]


def test_sub_folders_follow_their_parent():
    assert [(f.ref, depth) for f, depth in tree(FOLDERS)] == [
        ("A", 0), ("A1", 1), ("A1X", 2), ("B", 0), ("7", 0)]


def test_a_folder_contains_the_papers_of_its_sub_folders():
    assert members(FOLDERS, "zotero:A") == {"K1", "K2", "K3"}
    assert members(FOLDERS, "zotero:A1") == {"K2", "K3"}
    assert members(FOLDERS, "app:7") == {"K5"}
    assert members(FOLDERS, "zotero:GONE") == set()


def test_filed_papers():
    assert filed(FOLDERS) == {"K1", "K2", "K3", "K4", "K5"}
    assert filed([]) == set()


def test_missing_parent_and_parent_loop_do_not_lose_folders():
    orphan = _folder("O", parent="MISSING", keys={"K1"})
    loop = [_folder("X", parent="Y", keys={"K2"}), _folder("Y", parent="X", keys={"K3"})]
    assert [(f.ref, d) for f, d in tree([orphan])] == [("O", 0)]
    assert sorted(f.ref for f, _ in tree(loop)) == ["X", "Y"]
    assert members(loop, "zotero:X") == {"K2", "K3"}
