"""SQLite store for app-side data that does not live in Zotero or FAISS.

Holds the passage text behind every vector (so search results, the document
viewer and fact-check evidence can show the actual sentences), cached AI
highlights, starred papers, fact-check history, the metadata of PDFs that
were imported directly into the app, and the folders of the library (the
user's own folders plus a mirror of the Zotero collections).

A fresh connection is opened per operation, which keeps the class safe to use
from the GUI's worker threads.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    key TEXT NOT NULL, idx INTEGER NOT NULL, page INTEGER NOT NULL DEFAULT 1,
    text TEXT NOT NULL, PRIMARY KEY (key, idx));
CREATE TABLE IF NOT EXISTS highlights (
    key TEXT NOT NULL, idx INTEGER NOT NULL, sentence TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '', score REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS highlights_key ON highlights (key);
CREATE TABLE IF NOT EXISTS stars (key TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS factchecks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
    manuscript TEXT NOT NULL, results TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS local_docs (
    key TEXT PRIMARY KEY, title TEXT NOT NULL, authors TEXT NOT NULL DEFAULT '[]',
    year TEXT NOT NULL DEFAULT '', venue TEXT NOT NULL DEFAULT '',
    doi TEXT NOT NULL DEFAULT '', abstract TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]', pdf_path TEXT NOT NULL DEFAULT '',
    fulltext TEXT NOT NULL DEFAULT '', date_added TEXT NOT NULL,
    date_modified TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS folder_items (
    folder_id INTEGER NOT NULL, key TEXT NOT NULL,
    PRIMARY KEY (folder_id, key));
CREATE TABLE IF NOT EXISTS zotero_collections (
    key TEXT PRIMARY KEY, name TEXT NOT NULL, parent TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS zotero_collection_items (
    collection_key TEXT NOT NULL, key TEXT NOT NULL,
    PRIMARY KEY (collection_key, key));
"""

ZOTERO = "zotero"   # folder mirrored from a Zotero collection (read-only)
APP = "app"         # folder created in this app


def _folder_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("フォルダ名を入力してください。")
    return name


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True)
class ChunkRow:
    key: str
    idx: int
    page: int
    text: str


@dataclass(frozen=True)
class HighlightRow:
    key: str
    idx: int
    sentence: str
    reason: str
    score: float


@dataclass(frozen=True)
class FactCheckRun:
    id: int
    title: str
    manuscript: str
    results: list[dict]
    created_at: str


@dataclass(frozen=True)
class FolderRow:
    """A folder of the library and the papers filed directly in it."""
    source: str                 # ZOTERO or APP
    ref: str                    # Zotero collection key, or the app folder id
    name: str
    parent: str = ""            # ``id`` of the parent folder ("" = top level)
    keys: frozenset[str] = frozenset()

    @property
    def id(self) -> str:
        return f"{self.source}:{self.ref}"


class LibraryDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- passages ----------------------------------------------------------- #
    def replace_chunks(self, key: str, chunks: Sequence[tuple[int, str]]) -> None:
        """Store ``(page, text)`` passages for a paper; drops stale highlights."""
        with self._conn() as c:
            c.execute("DELETE FROM chunks WHERE key = ?", (key,))
            c.execute("DELETE FROM highlights WHERE key = ?", (key,))
            c.executemany(
                "INSERT INTO chunks (key, idx, page, text) VALUES (?, ?, ?, ?)",
                [(key, i, page, text) for i, (page, text) in enumerate(chunks)])

    def delete_document(self, key: str, keep_star: bool = False) -> None:
        """Drop a paper's passages and highlights (and its star, unless the
        paper may come back, e.g. when it vanished during a Zotero sync; its
        place in the user's folders is kept in that case too)."""
        tables = ("chunks", "highlights") if keep_star else (
            "chunks", "highlights", "stars", "folder_items")
        with self._conn() as c:
            for table in tables:
                c.execute(f"DELETE FROM {table} WHERE key = ?", (key,))

    def get_chunks(self, key: str) -> list[ChunkRow]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT key, idx, page, text FROM chunks WHERE key = ? ORDER BY idx",
                (key,)).fetchall()
        return [ChunkRow(**dict(r)) for r in rows]

    def get_chunk(self, key: str, idx: int) -> ChunkRow | None:
        with self._conn() as c:
            r = c.execute(
                "SELECT key, idx, page, text FROM chunks WHERE key = ? AND idx = ?",
                (key, idx)).fetchone()
        return ChunkRow(**dict(r)) if r else None

    def chunk_counts(self) -> dict[str, int]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT key, COUNT(*) AS n FROM chunks GROUP BY key").fetchall()
        return {r["key"]: r["n"] for r in rows}

    # -- AI highlights ------------------------------------------------------ #
    def get_highlights(self, key: str) -> list[HighlightRow]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT key, idx, sentence, reason, score FROM highlights "
                "WHERE key = ? ORDER BY idx", (key,)).fetchall()
        return [HighlightRow(**dict(r)) for r in rows]

    def set_highlights(self, key: str, rows: Sequence[HighlightRow]) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM highlights WHERE key = ?", (key,))
            c.executemany(
                "INSERT INTO highlights (key, idx, sentence, reason, score) "
                "VALUES (?, ?, ?, ?, ?)",
                [(key, r.idx, r.sentence, r.reason, r.score) for r in rows])

    # -- stars -------------------------------------------------------------- #
    def starred(self) -> set[str]:
        with self._conn() as c:
            return {r["key"] for r in c.execute("SELECT key FROM stars")}

    def toggle_star(self, key: str) -> bool:
        """Flip the star; returns the new state."""
        with self._conn() as c:
            if c.execute("SELECT 1 FROM stars WHERE key = ?", (key,)).fetchone():
                c.execute("DELETE FROM stars WHERE key = ?", (key,))
                return False
            c.execute("INSERT INTO stars (key) VALUES (?)", (key,))
            return True

    # -- folders ------------------------------------------------------------ #
    def add_folder(self, name: str) -> int:
        """Create one of the user's own folders; returns its id."""
        name = _folder_name(name)
        try:
            with self._conn() as c:
                cur = c.execute(
                    "INSERT INTO folders (name, created_at) VALUES (?, ?)",
                    (name, now_iso()))
                return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            raise ValueError(f"「{name}」という名前のフォルダは既にあります。") from None

    def rename_folder(self, folder_id: int, name: str) -> None:
        name = _folder_name(name)
        try:
            with self._conn() as c:
                c.execute("UPDATE folders SET name = ? WHERE id = ?",
                          (name, folder_id))
        except sqlite3.IntegrityError:
            raise ValueError(f"「{name}」という名前のフォルダは既にあります。") from None

    def delete_folder(self, folder_id: int) -> None:
        """Remove a folder; the papers in it stay in the library."""
        with self._conn() as c:
            c.execute("DELETE FROM folder_items WHERE folder_id = ?", (folder_id,))
            c.execute("DELETE FROM folders WHERE id = ?", (folder_id,))

    def set_in_folder(self, folder_id: int, key: str, member: bool) -> None:
        """File a paper in one of the user's folders, or take it out."""
        with self._conn() as c:
            if member:
                c.execute("INSERT OR IGNORE INTO folder_items (folder_id, key) "
                          "SELECT id, ? FROM folders WHERE id = ?",
                          (key, folder_id))
            else:
                c.execute("DELETE FROM folder_items WHERE folder_id = ? AND key = ?",
                          (folder_id, key))

    def folders(self) -> list[FolderRow]:
        """Zotero collections first, then the user's folders, each by name."""
        with self._conn() as c:
            zotero = c.execute("SELECT key, name, parent FROM zotero_collections "
                               "ORDER BY name COLLATE NOCASE").fetchall()
            own = c.execute("SELECT id, name FROM folders "
                            "ORDER BY name COLLATE NOCASE").fetchall()
            members: dict[str, set[str]] = {}
            for r in c.execute(
                    "SELECT collection_key, key FROM zotero_collection_items"):
                members.setdefault(f"{ZOTERO}:{r['collection_key']}", set()).add(r["key"])
            for r in c.execute("SELECT folder_id, key FROM folder_items"):
                members.setdefault(f"{APP}:{r['folder_id']}", set()).add(r["key"])
        rows = [FolderRow(ZOTERO, r["key"], r["name"],
                          f"{ZOTERO}:{r['parent']}" if r["parent"] else "")
                for r in zotero]
        rows += [FolderRow(APP, str(r["id"]), r["name"]) for r in own]
        return [FolderRow(f.source, f.ref, f.name, f.parent,
                          frozenset(members.get(f.id, ())))
                for f in rows]

    def replace_zotero_collections(
            self, collections: Iterable[tuple[str, str, str, Iterable[str]]]) -> bool:
        """Mirror the Zotero collections, given as ``(key, name, parent key,
        item keys)``; returns whether anything changed."""
        new = {key: (name, parent or "", frozenset(items))
               for key, name, parent, items in collections}
        old = {f.ref: (f.name, f.parent.partition(":")[2], f.keys)
               for f in self.folders() if f.source == ZOTERO}
        if new == old:
            return False
        with self._conn() as c:
            c.execute("DELETE FROM zotero_collections")
            c.execute("DELETE FROM zotero_collection_items")
            c.executemany(
                "INSERT INTO zotero_collections (key, name, parent) VALUES (?, ?, ?)",
                [(key, name, parent) for key, (name, parent, _) in new.items()])
            c.executemany(
                "INSERT INTO zotero_collection_items (collection_key, key) "
                "VALUES (?, ?)",
                [(key, item) for key, (_, _, items) in new.items()
                 for item in sorted(items)])
        return True

    # -- fact-check history ------------------------------------------------- #
    def add_factcheck(self, title: str, manuscript: str,
                      results: list[dict]) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO factchecks (title, manuscript, results, created_at) "
                "VALUES (?, ?, ?, ?)",
                (title, manuscript, json.dumps(results, ensure_ascii=False),
                 now_iso()))
            return int(cur.lastrowid)

    def list_factchecks(self, limit: int = 20) -> list[FactCheckRun]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM factchecks ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [FactCheckRun(r["id"], r["title"], r["manuscript"],
                             json.loads(r["results"]), r["created_at"])
                for r in rows]

    # -- locally imported PDFs ---------------------------------------------- #
    def upsert_local_doc(self, doc: dict) -> None:
        row = dict(doc)
        row["authors"] = json.dumps(row.get("authors", []), ensure_ascii=False)
        row["tags"] = json.dumps(row.get("tags", []), ensure_ascii=False)
        cols = ("key", "title", "authors", "year", "venue", "doi", "abstract",
                "tags", "pdf_path", "fulltext", "date_added", "date_modified")
        with self._conn() as c:
            c.execute(
                f"INSERT OR REPLACE INTO local_docs ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' for _ in cols)})",
                [row.get(col, "") for col in cols])

    def local_docs(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM local_docs").fetchall()
        return [self._local_row(r) for r in rows]

    def local_doc(self, key: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM local_docs WHERE key = ?",
                          (key,)).fetchone()
        return self._local_row(r) if r else None

    def delete_local_doc(self, key: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM local_docs WHERE key = ?", (key,))

    @staticmethod
    def _local_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["authors"] = json.loads(d["authors"])
        d["tags"] = json.loads(d["tags"])
        return d
