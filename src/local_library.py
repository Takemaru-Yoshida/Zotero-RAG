"""PDFs imported directly into the app (outside Zotero).

An imported PDF is copied into the app-data ``library/`` folder, its text is
extracted once with pypdf, and its metadata is kept in ``library.db``. The
indexer treats these papers exactly like Zotero items.
"""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
from pathlib import Path

from .library_db import LibraryDB, now_iso
from .zotero_client import Paper, _extract_pdf_text

logger = logging.getLogger(__name__)

KEY_PREFIX = "LOCAL-"
_YEAR = re.compile(r"(?:19|20)\d{2}")
EDITABLE_FIELDS = ("title", "authors", "year", "venue", "doi", "abstract", "tags")


def is_local(key: str) -> bool:
    return key.startswith(KEY_PREFIX)


def _pdf_metadata(pdf: Path) -> dict:
    """Title / authors / year from the PDF's document info, best effort."""
    try:
        from pypdf import PdfReader
        info = PdfReader(str(pdf)).metadata
    except Exception:  # noqa: BLE001 - malformed PDFs just yield no metadata
        logger.warning("Could not read PDF metadata: %s", pdf)
        return {}
    if not info:
        return {}
    authors = [a.strip() for a in re.split(r"[;,]| and ", info.author or "")
               if a.strip()]
    year = _YEAR.search(str(info.get("/CreationDate", "")))
    return {"title": (info.title or "").strip(), "authors": authors,
            "year": year.group(0) if year else ""}


class LocalLibrary:
    def __init__(self, config, db: LibraryDB):
        self.config = config
        self.db = db

    def import_pdf(self, pdf_path: str) -> Paper:
        """Copy a PDF into the app library and register it.

        Raises:
            FileNotFoundError: the path does not exist.
            ValueError: the file is not a PDF or contains no extractable text.
        """
        src = Path(pdf_path).expanduser()
        if not src.is_file():
            raise FileNotFoundError(f"PDF not found: {src}")
        if src.suffix.lower() != ".pdf":
            raise ValueError(f"Not a PDF file: {src.name}")
        digest = hashlib.sha1(src.read_bytes()).hexdigest()[:10].upper()
        key = f"{KEY_PREFIX}{digest}"
        dest = self.config.local_library_dir / f"{key}.pdf"
        copied = not dest.exists()
        if copied:
            shutil.copy2(src, dest)

        fulltext = _extract_pdf_text(dest, max_pages=200)
        if not fulltext.strip():
            if copied:   # never delete the file of an already-imported paper
                dest.unlink(missing_ok=True)
            raise ValueError(
                f"No text could be extracted from {src.name} "
                "(scanned PDFs need OCR first).")
        meta = _pdf_metadata(dest)
        year = meta.get("year") or ""
        if not year:
            m = _YEAR.search(src.stem)
            year = m.group(0) if m else ""
        existing = self.db.local_doc(key)
        now = now_iso()
        self.db.upsert_local_doc({
            "key": key,
            "title": meta.get("title") or src.stem,
            "authors": meta.get("authors", []),
            "year": year, "pdf_path": str(dest), "fulltext": fulltext,
            "date_added": existing["date_added"] if existing else now,
            "date_modified": now,
            # Keep fields the user already edited for this same file.
            **({f: existing[f] for f in EDITABLE_FIELDS} if existing else {}),
        })
        return self._paper(self.db.local_doc(key))

    def update_metadata(self, key: str, fields: dict) -> dict:
        """Edit title/authors/year/… of an imported PDF; returns the new row."""
        row = self.db.local_doc(key)
        if row is None:
            raise KeyError(key)
        row.update({k: v for k, v in fields.items() if k in EDITABLE_FIELDS})
        self.db.upsert_local_doc(row)
        return row

    def remove(self, key: str) -> None:
        row = self.db.local_doc(key)
        if row is None:
            return
        Path(row["pdf_path"]).unlink(missing_ok=True)
        self.db.delete_local_doc(key)

    def fetch_papers(self) -> list[Paper]:
        return [self._paper(row) for row in self.db.local_docs()]

    @staticmethod
    def _paper(row: dict) -> Paper:
        return Paper(
            key=row["key"], title=row["title"], abstract=row["abstract"],
            authors=row["authors"], year=row["year"], item_type="pdf",
            date_modified=row["date_modified"], fulltext=row["fulltext"],
            pdf_path=row["pdf_path"], tags=row["tags"], venue=row["venue"],
            doi=row["doi"], date_added=row["date_added"], source="local")
