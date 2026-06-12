"""Zotero integration layer.

Two interchangeable backends expose the same interface:

* ``LocalApiBackend`` talks to the Zotero local HTTP server
  (http://127.0.0.1:23119) which Zotero 7 exposes by default. This is the
  "official" integration path requested in the spec.
* ``SqliteBackend`` reads a *copy* of ``zotero.sqlite`` and the
  ``.zotero-ft-cache`` full-text files directly, so the app keeps working when
  Zotero is closed or the API is disabled.

``ZoteroClient`` picks the API when reachable and otherwise falls back to
SQLite, transparently. All access is strictly read-only — the app never writes
to the Zotero database (it copies the file first to avoid lock contention).

A ``Paper`` is the normalised unit handed to the rest of the pipeline.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests


@dataclass
class Paper:
    key: str                      # Zotero item key (stable id)
    title: str
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""
    item_type: str = ""
    date_modified: str = ""       # used for incremental re-indexing
    fulltext: str = ""            # extracted body text (may be empty)
    pdf_path: str = ""

    @property
    def display_authors(self) -> str:
        if not self.authors:
            return ""
        if len(self.authors) <= 3:
            return ", ".join(self.authors)
        return f"{self.authors[0]} et al."

    def embedding_text(self) -> str:
        """Concatenate the fields that describe the paper for embedding."""
        parts = [self.title, self.abstract, self.fulltext]
        return "\n\n".join(p for p in parts if p).strip()


# --------------------------------------------------------------------------- #
# SQLite backend (read-only fallback)
# --------------------------------------------------------------------------- #
class SqliteBackend:
    """Read papers and full text directly from the Zotero data directory."""

    def __init__(self, data_dir: Path, item_types: tuple[str, ...]):
        self.data_dir = Path(data_dir)
        self.db_src = self.data_dir / "zotero.sqlite"
        self.storage = self.data_dir / "storage"
        self.item_types = item_types

    def available(self) -> bool:
        return self.db_src.exists()

    def _connect(self) -> sqlite3.Connection:
        # Copy the DB so we never lock or mutate Zotero's live database.
        tmp = Path(tempfile.gettempdir()) / "zotero_rag_readonly.sqlite"
        shutil.copy2(self.db_src, tmp)
        # Also copy the WAL if present so we see the latest committed data.
        wal = self.db_src.with_suffix(".sqlite-wal")
        if wal.exists():
            shutil.copy2(wal, tmp.with_suffix(".sqlite-wal"))
        conn = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def fetch_papers(self) -> list[Paper]:
        conn = self._connect()
        try:
            placeholders = ",".join("?" for _ in self.item_types)
            rows = conn.execute(
                f"""
                SELECT i.itemID, i.key, i.dateModified, it.typeName
                FROM items i
                JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
                WHERE it.typeName IN ({placeholders})
                  AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
                """,
                self.item_types,
            ).fetchall()

            papers: list[Paper] = []
            for r in rows:
                item_id = r["itemID"]
                fields = self._item_fields(conn, item_id)
                authors = self._item_authors(conn, item_id)
                pdf_key, pdf_path = self._best_pdf(conn, item_id)
                fulltext = self._fulltext(pdf_key) if pdf_key else ""
                papers.append(Paper(
                    key=r["key"],
                    title=fields.get("title", "(untitled)"),
                    abstract=fields.get("abstractNote", ""),
                    authors=authors,
                    year=(fields.get("date", "")[:4]),
                    item_type=r["typeName"],
                    date_modified=r["dateModified"],
                    fulltext=fulltext,
                    pdf_path=pdf_path,
                ))
            return papers
        finally:
            conn.close()

    @staticmethod
    def _item_fields(conn: sqlite3.Connection, item_id: int) -> dict[str, str]:
        rows = conn.execute(
            """
            SELECT f.fieldName, v.value
            FROM itemData d
            JOIN fields f ON d.fieldID = f.fieldID
            JOIN itemDataValues v ON d.valueID = v.valueID
            WHERE d.itemID = ?
            """,
            (item_id,),
        ).fetchall()
        return {row["fieldName"]: str(row["value"]) for row in rows}

    @staticmethod
    def _item_authors(conn: sqlite3.Connection, item_id: int) -> list[str]:
        rows = conn.execute(
            """
            SELECT c.firstName, c.lastName
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
            """,
            (item_id,),
        ).fetchall()
        names = []
        for row in rows:
            name = " ".join(p for p in (row["firstName"], row["lastName"]) if p)
            if name:
                names.append(name)
        return names

    @staticmethod
    def _best_pdf(conn: sqlite3.Connection, item_id: int) -> tuple[str, str]:
        """Return (storage_key, path) of a PDF attachment, if any."""
        row = conn.execute(
            """
            SELECT i.key, ia.path
            FROM itemAttachments ia
            JOIN items i ON ia.itemID = i.itemID
            WHERE ia.parentItemID = ? AND ia.contentType = 'application/pdf'
            ORDER BY ia.itemID LIMIT 1
            """,
            (item_id,),
        ).fetchone()
        if not row:
            return "", ""
        return row["key"], (row["path"] or "")

    def _fulltext(self, storage_key: str) -> str:
        """Read Zotero's extracted full-text cache for an attachment.

        Zotero writes the indexed plain text of each PDF to
        ``storage/<KEY>/.zotero-ft-cache``. If absent, fall back to extracting
        the PDF directly.
        """
        cache = self.storage / storage_key / ".zotero-ft-cache"
        if cache.exists():
            try:
                return cache.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                pass
        # Fall back to direct PDF extraction.
        folder = self.storage / storage_key
        if folder.is_dir():
            for pdf in folder.glob("*.pdf"):
                return _extract_pdf_text(pdf)
        return ""


# --------------------------------------------------------------------------- #
# Local HTTP API backend
# --------------------------------------------------------------------------- #
class LocalApiBackend:
    """Talk to the Zotero local API server (read endpoints only)."""

    def __init__(self, base: str, library_type: str, library_id: int,
                 sqlite_fallback: Optional[SqliteBackend] = None):
        self.base = base.rstrip("/")
        self.prefix = (f"/api/users/{library_id}" if library_type == "user"
                       else f"/api/groups/{library_id}")
        # The local API does not serve attachment full text reliably for local
        # libraries, so we read body text from the on-disk cache via SQLite.
        self.sqlite_fallback = sqlite_fallback

    def available(self) -> bool:
        try:
            r = requests.get(f"{self.base}/api/", timeout=1.5)
            return r.status_code < 500
        except requests.RequestException:
            return False

    def fetch_papers(self) -> list[Paper]:
        # Build a map of full text from the local cache (fast, offline).
        ft_map: dict[str, str] = {}
        if self.sqlite_fallback and self.sqlite_fallback.available():
            for p in self.sqlite_fallback.fetch_papers():
                if p.fulltext:
                    ft_map[p.key] = p.fulltext

        papers: list[Paper] = []
        start, limit = 0, 100
        while True:
            r = requests.get(
                f"{self.base}{self.prefix}/items",
                params={"format": "json", "limit": limit, "start": start,
                        "itemType": "-attachment || note"},
                timeout=10,
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            for entry in batch:
                data = entry.get("data", {})
                key = data.get("key", "")
                creators = data.get("creators", [])
                authors = [
                    " ".join(p for p in (c.get("firstName"), c.get("lastName")) if p)
                    or c.get("name", "")
                    for c in creators
                ]
                papers.append(Paper(
                    key=key,
                    title=data.get("title", "(untitled)"),
                    abstract=data.get("abstractNote", ""),
                    authors=[a for a in authors if a],
                    year=str(data.get("date", ""))[:4],
                    item_type=data.get("itemType", ""),
                    date_modified=data.get("dateModified", ""),
                    fulltext=ft_map.get(key, ""),
                ))
            if len(batch) < limit:
                break
            start += limit
        return papers


def _extract_pdf_text(pdf_path: Path, max_pages: int = 60) -> str:
    """Best-effort PDF text extraction used only when no cache exists."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        out = []
        for page in reader.pages[:max_pages]:
            out.append(page.extract_text() or "")
        return "\n".join(out)
    except Exception:
        return ""


class ZoteroClient:
    """Facade that selects the best available backend."""

    def __init__(self, config):
        self.config = config
        data_dir = Path(config.zotero_data_dir)
        self.sqlite = SqliteBackend(data_dir, config.item_types)
        self.api = LocalApiBackend(
            config.zotero_api_base, config.zotero_library_type,
            config.zotero_library_id, sqlite_fallback=self.sqlite,
        )

    def backend_name(self) -> str:
        if self.api.available():
            return "Zotero Local API (live)"
        if self.sqlite.available():
            return "Zotero database (read-only)"
        return "unavailable"

    def fetch_papers(self) -> list[Paper]:
        if self.api.available():
            try:
                return self.api.fetch_papers()
            except requests.RequestException:
                pass  # fall through to SQLite
        if self.sqlite.available():
            return self.sqlite.fetch_papers()
        raise RuntimeError(
            "Cannot reach Zotero. Start Zotero (with the local API enabled) "
            "or set the correct Zotero data directory in settings."
        )
