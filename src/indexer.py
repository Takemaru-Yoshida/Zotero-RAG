"""Indexing pipeline — spec steps 2, 3 and 4 with incremental sync.

``sync()`` fetches the current Zotero library, embeds any paper that is new or
whose ``dateModified`` changed since last time, drops papers that disappeared,
persists the FAISS index + metadata, and (for large libraries) builds an ANN
index for faster search. It is safe to call on every app launch / search.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .embedder import Embedder
from .vector_store import VectorStore
from .zotero_client import ZoteroClient, Paper

ProgressCb = Optional[Callable[[str, float], None]]


@dataclass
class SyncResult:
    added: int
    updated: int
    removed: int
    skipped: int
    total_papers: int
    total_vectors: int
    backend: str
    index_kind: str


class Indexer:
    def __init__(self, config, embedder: Embedder | None = None,
                 store: VectorStore | None = None):
        self.config = config
        self.client = ZoteroClient(config)
        self.embedder = embedder or Embedder(config)
        self.store = store or VectorStore(config)
        self._loaded = False

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.store.load()
            self._loaded = True

    def _paper_meta(self, p: Paper) -> dict:
        return {
            "key": p.key, "title": p.title, "authors": p.authors,
            "year": p.year, "item_type": p.item_type,
            "abstract": p.abstract[:1000],
            "date_modified": p.date_modified, "pdf_path": p.pdf_path,
            "has_fulltext": bool(p.fulltext),
        }

    def sync(self, progress: ProgressCb = None) -> SyncResult:
        """Detect changes and (re)embed only what is necessary."""
        self.ensure_loaded()

        def report(msg: str, frac: float = 0.0):
            if progress:
                progress(msg, frac)

        report("Connecting to Zotero ...", 0.02)
        papers = self.client.fetch_papers()
        backend = self.client.backend_name()
        report(f"Found {len(papers)} items via {backend}", 0.05)

        current_keys = {p.key for p in papers}
        existing_keys = self.store.indexed_keys()

        # Papers removed from Zotero since last sync.
        removed = 0
        for key in existing_keys - current_keys:
            self.store.remove_paper(key)
            removed += 1

        # Papers that are new or changed.
        to_process = [p for p in papers
                      if self.store.needs_update(p.key, p.date_modified)]
        skipped = len(papers) - len(to_process)

        added = updated = 0
        total = len(to_process)
        for i, p in enumerate(to_process):
            text = p.embedding_text()
            frac = 0.05 + 0.9 * (i / total) if total else 0.95
            report(f"Embedding [{i+1}/{total}] {p.title[:60]}", frac)
            if not text:
                # No usable text (e.g. metadata-only entry); skip but record so
                # we don't retry it every run.
                vectors = self.embedder.embed_document(p.title or p.key)
            else:
                vectors = self.embedder.embed_document(text)
            was_present = p.key in existing_keys
            self.store.add_paper(self._paper_meta(p), vectors)
            if was_present:
                updated += 1
            else:
                added += 1

        index_kind = "flat (exact)"
        if added or updated or removed:
            report("Optimising vector index ...", 0.96)
            index_kind = self.store.optimize()
            report("Saving index ...", 0.98)
            self.store.save()
        else:
            index_kind = ("ivf" if self.store.n_vectors >= 4000
                          else "flat (exact)")

        report("Up to date.", 1.0)
        return SyncResult(
            added=added, updated=updated, removed=removed, skipped=skipped,
            total_papers=self.store.n_papers, total_vectors=self.store.n_vectors,
            backend=backend, index_kind=index_kind,
        )
