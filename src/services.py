"""Service facade — the desktop counterpart of the web app's ``lib/api.ts``.

The GUI and the CLI talk to this single object instead of wiring the
embedder, vector store, database, indexer, search engine, highlighter and
fact-checker together themselves.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from .config import Config
from .embedder import Embedder
from .factcheck import FactChecker
from .graph import Graph, build_graph, related
from .highlights import Highlighter
from .indexer import Indexer, SyncResult
from .library_db import FolderRow, LibraryDB
from .local_library import LocalLibrary, is_local
from .nli import NliModel
from .search import SearchEngine
from .vector_store import SCHEMA_VERSION, VectorStore

ProgressCb = Optional[Callable[[str, float], None]]


@dataclass(frozen=True)
class Doc:
    """A paper as shown in the UI (Zotero item or imported PDF)."""
    key: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: str = ""
    venue: str = ""
    doi: str = ""
    abstract: str = ""
    tags: list[str] = field(default_factory=list)
    starred: bool = False
    source: str = "zotero"
    item_type: str = ""
    pages: int = 0
    n_chunks: int = 0
    date_added: str = ""
    pdf_path: str = ""

    @property
    def is_local(self) -> bool:
        return is_local(self.key)

    @property
    def author_line(self) -> str:
        if not self.authors:
            names = "著者不明"
        elif len(self.authors) > 2:
            names = f"{self.authors[0]} ほか"
        else:
            names = ", ".join(self.authors)
        return f"{names} ({self.year})" if self.year else names

    @property
    def short_label(self) -> str:
        """Graph node label, e.g. ``Kriegeskorte 2008``."""
        surname = self.authors[0].split()[-1] if self.authors else self.title[:14]
        return f"{surname} {self.year}".strip()

    @property
    def zotero_uri(self) -> str:
        return f"zotero://select/library/items/{self.key}"


class Services:
    def __init__(self, config: Config | None = None):
        self.config = config or Config.load()
        self.db = LibraryDB(self.config.db_path)
        self.embedder = Embedder(self.config)
        self.store = VectorStore(self.config)
        self.local = LocalLibrary(self.config, self.db)
        self.indexer = Indexer(self.config, embedder=self.embedder,
                               store=self.store, db=self.db, local=self.local)
        self.engine = SearchEngine(self.config, self.embedder, self.store, self.db)
        self.highlighter = Highlighter(self.config, self.embedder, self.store,
                                       self.db)
        self.nli = NliModel(self.config)
        self.factchecker = FactChecker(self.config, self.embedder, self.store,
                                       self.db, self.nli)
        self._graph: Graph | None = None

    def load(self) -> None:
        self.indexer.ensure_loaded()

    # -- library ------------------------------------------------------------ #
    def _doc(self, key: str, meta: dict, starred: set[str]) -> Doc:
        return Doc(
            key=key, title=meta.get("title") or "(untitled)",
            authors=list(meta.get("authors") or []),
            year=str(meta.get("year") or ""), venue=meta.get("venue", ""),
            doi=meta.get("doi", ""), abstract=meta.get("abstract", ""),
            tags=list(meta.get("tags") or []), starred=key in starred,
            source=meta.get("source", "zotero"),
            item_type=meta.get("item_type", ""), pages=int(meta.get("pages") or 0),
            n_chunks=int(meta.get("n_chunks") or 0),
            date_added=meta.get("date_added", ""),
            pdf_path=meta.get("pdf_path", ""))

    def documents(self) -> list[Doc]:
        """All indexed papers, most recently added first."""
        starred = self.db.starred()
        docs = [self._doc(k, m, starred)
                for k, m in self.store.papers_snapshot().items()]
        return sorted(docs, key=lambda d: (d.date_added, d.title), reverse=True)

    def document(self, key: str) -> Doc | None:
        meta = self.store.papers_snapshot().get(key)
        return self._doc(key, meta, self.db.starred()) if meta else None

    def toggle_star(self, key: str) -> bool:
        return self.db.toggle_star(key)

    # -- folders ------------------------------------------------------------ #
    def folders(self) -> list[FolderRow]:
        """Zotero collections (read-only mirror) and the user's own folders."""
        return self.db.folders()

    def add_folder(self, name: str) -> int:
        return self.db.add_folder(name)

    def rename_folder(self, folder_id: int, name: str) -> None:
        self.db.rename_folder(folder_id, name)

    def delete_folder(self, folder_id: int) -> None:
        self.db.delete_folder(folder_id)

    def set_in_folder(self, folder_id: int, key: str, member: bool) -> None:
        self.db.set_in_folder(folder_id, key, member)

    def needs_reindex(self) -> int:
        """Number of papers indexed by an older version of the app."""
        return sum(1 for m in self.store.papers_snapshot().values()
                   if m.get("schema") != SCHEMA_VERSION)

    # -- indexing ----------------------------------------------------------- #
    def sync(self, progress: ProgressCb = None) -> SyncResult:
        result = self.indexer.sync(progress=progress)
        self._graph = None
        return result

    def add_pdf(self, path: str) -> Doc:
        paper = self.indexer.add_local_pdf(path)
        self._graph = None
        return self.document(paper.key)

    def update_local(self, key: str, fields: dict) -> Doc:
        """Edit the metadata of an imported PDF (no re-embedding needed)."""
        row = self.local.update_metadata(key, fields)
        self.store.update_meta(key, {f: row[f] for f in (
            "title", "authors", "year", "venue", "doi", "abstract", "tags")})
        self.store.save()
        self._graph = None
        return self.document(key)

    def remove_local(self, key: str) -> None:
        self.indexer.remove_local(key)
        self._graph = None

    # -- graph -------------------------------------------------------------- #
    def invalidate_graph(self) -> None:
        self._graph = None

    def graph(self) -> Graph:
        if self._graph is None:
            self._graph = build_graph(self.store, self.db,
                                      self.config.graph_neighbors)
        return self._graph

    def related(self, key: str, n: int = 4) -> list[Doc]:
        starred = self.db.starred()
        papers = self.store.papers_snapshot()
        return [self._doc(k, papers[k], starred)
                for k, _ in related(self.store, key, n) if k in papers]

    # -- fact-check --------------------------------------------------------- #
    def sample_manuscript(self, n: int = 3) -> str:
        """A demo manuscript built from the user's own library.

        Real key sentences of recent papers are cited to their sources (these
        should come out as supported), followed by one fabricated citation
        (which should come out as "not found").
        """
        lines: list[str] = []
        for doc in self.documents():
            if len(lines) >= n:
                break
            if not doc.authors or not doc.year or doc.n_chunks < 4:
                continue
            sentence = next(
                (m.sentence for m in self.highlighter.key_sentences(doc.key)
                 if 60 <= len(m.sentence) <= 300
                 and not re.search(r"\d{4}|[()]", m.sentence)), None)
            if sentence is None:
                continue
            surnames = [a.split()[-1] for a in doc.authors]
            if len(surnames) == 1:
                cite = f"{surnames[0]}, {doc.year}"
            elif len(surnames) == 2:
                cite = f"{surnames[0]} & {surnames[1]}, {doc.year}"
            else:
                cite = f"{surnames[0]} et al., {doc.year}"
            lines.append(f"{sentence.rstrip('.。 ')} ({cite}).")
        lines.append("Object-based attention in ventral cortex is fully "
                     "explained by spatial attention (Tanaka et al., 2021).")
        return "\n".join(lines)

    # -- dashboard ---------------------------------------------------------- #
    def needs_review(self, verdict: str) -> bool:
        if verdict in ("refuted", "not_found"):
            return True
        return verdict == "partial" and self.config.strict_partial

    def stats(self) -> dict[str, int]:
        runs = self.db.list_factchecks(limit=1000)
        results = [r for run in runs for r in run.results]
        return {
            "documents": self.store.n_papers,
            "checked": len(results),
            "needs_review": sum(1 for r in results
                                if self.needs_review(r.get("verdict", ""))),
        }
