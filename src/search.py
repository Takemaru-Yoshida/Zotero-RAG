"""Query-time semantic search — spec steps 5, 6 and 7.

The query text is embedded with the *same* model used for indexing (with that
model's query prefix), compared against stored passage vectors by cosine
similarity (via the FAISS inner-product index), and the top papers above the
configured threshold are returned for display.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .embedder import Embedder
from .library_db import LibraryDB
from .vector_store import VectorStore


@dataclass
class SearchHit:
    key: str
    title: str
    authors: list[str]
    year: str
    item_type: str
    abstract: str
    score: float
    matched_chunks: int

    @property
    def zotero_uri(self) -> str:
        # Opens the item directly inside the Zotero app.
        return f"zotero://select/library/items/{self.key}"


@dataclass
class PassageHit:
    """One passage of one paper that matches the query."""
    key: str
    chunk_idx: int
    page: int
    text: str
    score: float
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""


class SearchEngine:
    def __init__(self, config, embedder: Embedder, store: VectorStore,
                 db: LibraryDB | None = None):
        self.config = config
        self.embedder = embedder
        self.store = store
        self.db = db

    def search_passages(self, query: str, limit: int | None = None,
                        threshold: float | None = None,
                        keys: Iterable[str] | None = None) -> list[PassageHit]:
        """Passage-level search (the web app's ``semanticSearch``).

        Returns the best-matching passages with their text and page, ranked by
        cosine similarity; ``keys`` restricts the search to some papers.
        """
        query = (query or "").strip()
        if not query or self.db is None:
            return []
        limit = limit or self.config.top_k
        threshold = self.config.similarity_threshold if threshold is None else threshold
        qvec = self.embedder.embed_query(query)
        hits: list[PassageHit] = []
        for key, idx, score in self.store.search_chunks(qvec, limit, threshold, keys):
            row = self.db.get_chunk(key, idx)
            if row is None:
                continue
            meta = self.store.papers.get(key, {})
            hits.append(PassageHit(
                key=key, chunk_idx=idx, page=row.page, text=row.text, score=score,
                title=meta.get("title", ""), authors=meta.get("authors", []),
                year=meta.get("year", "")))
        return hits

    def search(self, query: str, top_k: int | None = None,
               threshold: float | None = None) -> list[SearchHit]:
        query = (query or "").strip()
        if not query:
            return []
        top_k = top_k or self.config.top_k
        threshold = self.config.similarity_threshold if threshold is None else threshold

        qvec = self.embedder.embed_query(query)
        raw = self.store.search(qvec, top_k=top_k, threshold=threshold,
                                aggregate=self.config.score_aggregation)
        hits = []
        for r in raw:
            hits.append(SearchHit(
                key=r["key"], title=r.get("title", ""),
                authors=r.get("authors", []), year=r.get("year", ""),
                item_type=r.get("item_type", ""), abstract=r.get("abstract", ""),
                score=r["score"], matched_chunks=r.get("matched_chunks", 0),
            ))
        return hits
