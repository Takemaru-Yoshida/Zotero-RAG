"""AI markers for the document viewer.

Two kinds of marker, mirroring the web app:

* ``ai_key``   — sentences that best represent the paper. Extractive and fully
  local: the passages closest to the paper's centroid vector (blended with its
  title + abstract when available) are chosen, and inside each one the single
  closest sentence is marked. Results are cached in ``library.db``.
* ``ai_query`` — "find the sentence I'm looking for": the passages of one paper
  that are semantically closest to a free-text query.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .chunker import split_sentences
from .embedder import Embedder
from .library_db import HighlightRow, LibraryDB
from .vector_store import VectorStore

MIN_SENTENCE_CHARS = 25
MAX_SENTENCE_CHARS = 600


@dataclass(frozen=True)
class Highlight:
    key: str
    chunk_idx: int
    sentence: str      # exact substring of the passage text to mark
    kind: str          # "ai_key" | "ai_query"
    reason: str
    score: float


def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) or 1.0)


class Highlighter:
    def __init__(self, config, embedder: Embedder, store: VectorStore,
                 db: LibraryDB):
        self.config = config
        self.embedder = embedder
        self.store = store
        self.db = db

    def best_sentence(self, text: str, target: np.ndarray) -> tuple[str, float]:
        """The sentence of ``text`` closest to ``target`` and its cosine.

        Falls back to the whole passage when it cannot be split usefully.
        """
        sentences = [s.text for s in split_sentences(text)
                     if MIN_SENTENCE_CHARS <= len(s.text) <= MAX_SENTENCE_CHARS
                     and s.text in text]
        if len(sentences) < 2:
            return (sentences[0] if sentences else text), float("nan")
        scores = self.embedder.embed_passages(sentences) @ target
        best = int(np.argmax(scores))
        return sentences[best], float(scores[best])

    def key_sentences(self, key: str) -> list[Highlight]:
        """Key sentences of a paper (computed once, then served from cache)."""
        cached = self.db.get_highlights(key)
        if cached:
            return [Highlight(r.key, r.idx, r.sentence, "ai_key", r.reason, r.score)
                    for r in cached]
        vectors, ref_flags = self.store.paper_vectors(key)
        chunks = {c.idx: c for c in self.db.get_chunks(key)}
        # A sync may be replacing this paper right now: only trust vectors
        # and passages that describe the same version of it.
        if not len(vectors) or len(chunks) != len(vectors):
            return []
        rows = range(len(vectors))
        target = _unit(vectors.mean(axis=0))
        meta = self.store.papers_snapshot().get(key, {})
        if meta.get("abstract"):
            summary = f"{meta.get('title', '')}. {meta['abstract']}"
            target = _unit(target + self.embedder.embed_query(summary))

        n = min(self.config.key_sentences, max(1, len(rows) // 2))
        scores = vectors @ target
        # Never pick a key sentence out of the reference list.
        flags = np.array(ref_flags, dtype=bool)
        if len(flags) == len(scores) and not flags.all():
            scores = np.where(flags, -np.inf, scores)
        picked = sorted(int(i) for i in np.argsort(-scores)[:n]
                        if int(i) in chunks and np.isfinite(scores[int(i)]))
        out: list[HighlightRow] = []
        for idx in picked:
            sentence, s = self.best_sentence(chunks[idx].text, target)
            score = float(scores[idx]) if np.isnan(s) else s
            out.append(HighlightRow(
                key, idx, sentence, f"文献全体の主旨との関連度 {score:.2f}", score))
        self.db.set_highlights(key, out)
        return [Highlight(r.key, r.idx, r.sentence, "ai_key", r.reason, r.score)
                for r in out]

    def find(self, key: str, query: str, limit: int = 3) -> list[Highlight]:
        """Passages of one paper closest in meaning to ``query``, best first."""
        query = (query or "").strip()
        if not query:
            return []
        qvec = self.embedder.embed_query(query)
        out: list[Highlight] = []
        for _, idx, score in self.store.search_chunks(qvec, limit, keys=[key]):
            row = self.db.get_chunk(key, idx)
            if row is None:
                continue
            sentence, _ = self.best_sentence(row.text, qvec)
            out.append(Highlight(key, idx, sentence, "ai_query",
                                 f"類似度 {score:.2f}", score))
        return out
