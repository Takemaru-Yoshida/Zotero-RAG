"""Indexing pipeline — spec steps 2, 3 and 4 with incremental sync.

``sync()`` fetches the current Zotero library, embeds any paper that is new or
whose ``dateModified`` changed since last time, drops papers that disappeared,
persists the FAISS index + metadata, and (for large libraries) builds an ANN
index for faster search. It is safe to call on every app launch / search.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

from .chunker import reference_flags
from .embedder import Embedder
from .library_db import LibraryDB
from .local_library import LocalLibrary, is_local
from .vector_store import VectorStore
from .zotero_client import ZoteroClient, Paper

ProgressCb = Optional[Callable[[str, float], None]]

# Persist the index every this many papers so an interrupted first sync does
# not lose all of its work.
SAVE_EVERY = 25

# Version of the bibliography-detection rule in ``chunker.reference_flags``.
REF_RULE = 3


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
    folders_changed: bool = False   # the Zotero collections changed


class Indexer:
    def __init__(self, config, embedder: Embedder | None = None,
                 store: VectorStore | None = None,
                 db: LibraryDB | None = None,
                 local: LocalLibrary | None = None):
        self.config = config
        self.client = ZoteroClient(config)
        self.embedder = embedder or Embedder(config)
        self.store = store or VectorStore(config)
        self.db = db or LibraryDB(config.db_path)
        self.local = local or LocalLibrary(config, self.db)
        self._loaded = False
        # A sync and a PDF import run on different worker threads. One at a
        # time: a paper imported halfway through a sync is not in the list the
        # sync fetched, and would be removed again as "gone".
        self._busy = threading.Lock()

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.store.load()
            self._loaded = True
            # An index flagged by an older bibliography rule (or none) is
            # re-flagged from the stored passage text; no re-embedding needed.
            if self.store.ref_rule != REF_RULE:
                flags = {key: reference_flags(
                             [c.text for c in self.db.get_chunks(key)])
                         for key in self.store.papers}
                self.store.set_ref_flags(flags, REF_RULE)
                self.store.save()

    def _paper_meta(self, p: Paper) -> dict:
        return {
            "key": p.key, "title": p.title, "authors": p.authors,
            "year": p.year, "item_type": p.item_type,
            "abstract": p.abstract[:1000],
            "date_modified": p.date_modified, "pdf_path": p.pdf_path,
            "has_fulltext": bool(p.fulltext),
            "tags": p.tags, "venue": p.venue, "doi": p.doi,
            "date_added": p.date_added, "source": p.source, "pages": p.pages,
        }

    def index_paper(self, p: Paper) -> int:
        """Chunk, embed and store one paper; returns its passage count."""
        chunks = self.embedder.chunk_document(p.embedding_text())
        if not chunks:
            # No usable text (e.g. metadata-only entry): index the title so the
            # paper is still listed and is not retried on every run.
            chunks = self.embedder.chunk_document(p.title or p.key)
        vectors = self.embedder.embed_passages([c.text for c in chunks])
        # Text first, vectors second: a search that runs in between then finds
        # the new text behind every row it can see. If the app dies in
        # between, the paper is simply re-indexed on the next sync.
        self.db.replace_chunks(p.key, [(c.page, c.text) for c in chunks])
        self.store.add_paper(self._paper_meta(p), vectors,
                             reference_flags([c.text for c in chunks]))
        return len(chunks)

    def add_local_pdf(self, pdf_path: str) -> Paper:
        """Import a PDF into the app's own library and index it right away."""
        self.ensure_loaded()
        with self._busy:
            paper = self.local.import_pdf(pdf_path)
            self.index_paper(paper)
            self.store.save()
        return paper

    def remove_local(self, key: str) -> None:
        """Delete an imported PDF from the library and the index."""
        self.ensure_loaded()
        self.local.remove(key)
        self.store.remove_paper(key)
        self.db.delete_document(key)
        self.store.save()

    def sync(self, progress: ProgressCb = None) -> SyncResult:
        """Detect changes and (re)embed only what is necessary."""
        self.ensure_loaded()
        with self._busy:
            return self._sync(progress)

    def _sync(self, progress: ProgressCb) -> SyncResult:

        def report(msg: str, frac: float = 0.0):
            if progress:
                progress(msg, frac)

        report("Connecting to Zotero ...", 0.02)
        papers = self.client.fetch_papers() + self.local.fetch_papers()
        backend = self.client.backend_name()
        report(f"Found {len(papers)} items via {backend}", 0.05)

        current_keys = {p.key for p in papers}
        existing_keys = self.store.indexed_keys()

        # Papers removed from Zotero since last sync.
        removed = 0
        gone = existing_keys - current_keys
        # Safety net: a wrong data folder or a different library would look
        # like "most papers were deleted". Refuse instead of wiping the index.
        indexed_zotero = [k for k in existing_keys if not is_local(k)]
        gone_zotero = [k for k in gone if not is_local(k)]
        if len(indexed_zotero) >= 10 and len(gone_zotero) > len(indexed_zotero) / 2:
            raise RuntimeError(
                f"{len(gone_zotero)} of {len(indexed_zotero)} indexed papers are "
                "missing from Zotero. Sync was stopped to protect the index; "
                "check the Zotero data folder in Settings.")
        # Collections are mirrored on every sync: moving a paper between
        # them does not change the paper, so it is not seen as an update.
        # (After the check above, so a wrong library cannot replace them.)
        collections = self.client.fetch_collections()
        folders_changed = (collections is not None
                           and self.db.replace_zotero_collections(collections))

        for key in gone:
            self.store.remove_paper(key)
            self.db.delete_document(key, keep_star=True)
            removed += 1

        # Papers that are new or changed.
        to_process = [p for p in papers
                      if self.store.needs_update(p.key, p.date_modified)]
        skipped = len(papers) - len(to_process)

        added = updated = 0
        total = len(to_process)
        for i, p in enumerate(to_process):
            frac = 0.05 + 0.9 * (i / total) if total else 0.95
            report(f"Embedding [{i+1}/{total}] {p.title[:60]}", frac)
            self.index_paper(p)
            if p.key in existing_keys:
                updated += 1
            else:
                added += 1
            if (i + 1) % SAVE_EVERY == 0:
                self.store.save()

        if added or updated or removed:
            report("Optimising vector index ...", 0.96)
            index_kind = self.store.optimize()
            report("Saving index ...", 0.98)
            self.store.save()
        else:
            index_kind = self.store.index_kind()

        report("Up to date.", 1.0)
        return SyncResult(
            added=added, updated=updated, removed=removed, skipped=skipped,
            total_papers=self.store.n_papers, total_vectors=self.store.n_vectors,
            backend=backend, index_kind=index_kind,
            folders_changed=folders_changed,
        )
