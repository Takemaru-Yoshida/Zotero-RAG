"""FAISS-backed vector store with on-disk persistence.

Each *chunk* of each paper is one vector. A parallel metadata list maps every
vector row back to its source paper, so document-level results can be
aggregated from chunk hits. Vectors are L2-normalised and stored in an
``IndexFlatIP`` (inner product == cosine similarity).

For larger libraries the flat index is automatically swapped for an
``IndexIVFFlat`` (inverted-file ANN) which trades a tiny amount of recall for a
large speed-up — the "efficient vector search" enhancement from the spec.

The store also records, per paper, the ``date_modified`` used to detect which
papers changed and need re-indexing.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Iterable

import faiss
import numpy as np

from .embedding_models import LEGACY_MODEL

logger = logging.getLogger(__name__)

# Below this many chunks a brute-force flat index is fastest and exact
# (a flat search over 50k vectors takes a few milliseconds).
IVF_THRESHOLD = 50_000

# Bumped when the chunking / stored metadata changes so that papers indexed by
# an older version are re-embedded on the next sync.
#   1: overlapping 512-token windows, no passage text kept
#   2: sentence-aligned passages with text + page in library.db
SCHEMA_VERSION = 2


class VectorStore:
    def __init__(self, config):
        self.config = config
        self.dim = config.embedding_dim
        # Fixed for the life of the store: the settings page may change the
        # configured model while this index still holds the old model's vectors.
        self.model_name = config.embedding_model
        self.index: faiss.Index | None = None
        # Per-vector metadata: list of {key, chunk}
        self.row_meta: list[dict] = []
        # Per-paper metadata: key -> {title, authors, year, ..., date_modified, n_chunks}
        self.papers: dict[str, dict] = {}
        # Sync mutates the index while searches run on other threads.
        self._lock = threading.RLock()
        self._matrix: np.ndarray | None = None   # cached copy of all vectors
        self.ref_rule = 0    # version of the rule that set the "ref" flags
        # True when the index on disk was built by another embedding model and
        # was therefore left out; the next sync embeds every paper again.
        self.model_changed = False

    # -- lifecycle ---------------------------------------------------------- #
    def load(self) -> bool:
        ip, mp = self.config.index_path, self.config.meta_path
        with self._lock:
            if ip.exists() and mp.exists():
                data = json.loads(mp.read_text(encoding="utf-8"))
                built_with = data.get("embedding_model", LEGACY_MODEL)
                if built_with != self.model_name:
                    # Vectors of two models are not comparable (and usually
                    # differ in size): start empty and let sync rebuild.
                    logger.warning(
                        "Index was built with %s but the configured model is "
                        "%s; the next sync rebuilds the index.",
                        built_with, self.model_name)
                    self.model_changed = True
                    return False
                self.index = faiss.read_index(str(ip))
                self.row_meta = data.get("row_meta", [])
                self.papers = data.get("papers", {})
                self.ref_rule = int(data.get("ref_rule", 0))
                self._matrix = None
                if (len(self.row_meta) != self.index.ntotal
                        or self.index.d != self.dim):
                    # Vectors and metadata out of step (e.g. files from two
                    # different saves): start empty and let sync rebuild.
                    logger.error(
                        "Index has %d vectors of size %d but metadata has %d "
                        "rows and the model produces size %d; ignoring both, "
                        "the next sync rebuilds the index.",
                        self.index.ntotal, self.index.d, len(self.row_meta),
                        self.dim)
                    self.index, self.row_meta, self.papers = None, [], {}
                    return False
                return True
            return False

    def save(self) -> None:
        with self._lock:
            if self.index is None:
                return
            # Write to temporary files and swap them in, so an interrupted
            # save can never leave a truncated or mismatched pair on disk.
            ip, mp = self.config.index_path, self.config.meta_path
            tmp_index = ip.with_name(ip.name + ".tmp")
            tmp_meta = mp.with_name(mp.name + ".tmp")
            faiss.write_index(self.index, str(tmp_index))
            tmp_meta.write_text(
                json.dumps({"row_meta": self.row_meta, "papers": self.papers,
                            "ref_rule": self.ref_rule,
                            "embedding_model": self.model_name},
                           ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp_index, ip)
            os.replace(tmp_meta, mp)
            self.model_changed = False

    def _new_index(self) -> faiss.Index:
        return faiss.IndexFlatIP(self.dim)

    # -- incremental update ------------------------------------------------- #
    def indexed_keys(self) -> set[str]:
        return set(self.papers.keys())

    def needs_update(self, key: str, date_modified: str) -> bool:
        rec = self.papers.get(key)
        return (rec is None or rec.get("date_modified") != date_modified
                or rec.get("schema") != SCHEMA_VERSION)

    def remove_paper(self, key: str) -> None:
        """Drop a paper and rebuild the index without its rows."""
        with self._lock:
            if key not in self.papers:
                return
            keep_rows = [i for i, m in enumerate(self.row_meta)
                         if m["key"] != key]
            self._rebuild_from_rows(keep_rows)
            self.papers.pop(key, None)

    def _rebuild_from_rows(self, keep_rows: list[int]) -> None:
        if self.index is None or self.index.ntotal == 0:
            return
        vecs = self.matrix()
        kept = vecs[keep_rows] if keep_rows else np.zeros((0, self.dim), np.float32)
        self.index = self._new_index()
        if len(kept):
            self.index.add(kept)
        self.row_meta = [self.row_meta[i] for i in keep_rows]
        self._matrix = None

    def add_paper(self, paper_meta: dict, vectors: np.ndarray,
                  ref_flags: list[bool] | None = None) -> None:
        """Add (or replace) a paper's chunk vectors.

        ``ref_flags[i]`` marks passage ``i`` as bibliography (see
        ``chunker.is_reference_like``); such rows are skipped by
        ``search_chunks`` unless asked for.
        """
        key = paper_meta["key"]
        with self._lock:
            if key in self.papers:
                self.remove_paper(key)
            if self.index is None:
                self.index = self._new_index()
            if len(vectors):
                self.index.add(vectors)
                for c in range(len(vectors)):
                    self.row_meta.append({
                        "key": key, "chunk": c,
                        "ref": bool(ref_flags[c]) if ref_flags else False})
            paper_meta = dict(paper_meta)
            paper_meta["n_chunks"] = int(len(vectors))
            paper_meta["schema"] = SCHEMA_VERSION
            self.papers[key] = paper_meta
            self._matrix = None

    def update_meta(self, key: str, fields: dict) -> None:
        """Change display metadata of a paper without re-embedding it."""
        with self._lock:
            if key in self.papers:
                self.papers[key].update(fields)

    # -- direct vector access ----------------------------------------------- #
    def matrix(self) -> np.ndarray:
        """All stored vectors as an (n, dim) array, in row order (cached)."""
        with self._lock:
            if self._matrix is None:
                if self.index is None or self.index.ntotal == 0:
                    self._matrix = np.zeros((0, self.dim), np.float32)
                else:
                    self._matrix = self.index.reconstruct_n(0, self.index.ntotal)
            return self._matrix

    def papers_snapshot(self) -> dict[str, dict]:
        """A copy of the per-paper metadata that is safe to iterate while a
        sync adds or removes papers on another thread."""
        with self._lock:
            return dict(self.papers)

    def paper_vectors(self, key: str) -> tuple[np.ndarray, list[bool]]:
        """A paper's passage vectors and bibliography flags, by passage index.

        Taken under one lock, so a concurrent sync cannot shift the rows
        between looking them up and reading the vectors.
        """
        with self._lock:
            rows = sorted((m["chunk"], i, bool(m.get("ref")))
                          for i, m in enumerate(self.row_meta) if m["key"] == key)
            if not rows:
                return np.zeros((0, self.dim), np.float32), []
            vectors = self.matrix()[[i for _, i, _ in rows]].copy()
            return vectors, [flag for _, _, flag in rows]

    def rows_for(self, key: str) -> list[int]:
        """Row numbers of a paper's passages, ordered by passage index."""
        with self._lock:
            rows = [(m["chunk"], i) for i, m in enumerate(self.row_meta)
                    if m["key"] == key]
        return [i for _, i in sorted(rows)]

    def doc_vectors(self) -> tuple[list[str], np.ndarray]:
        """One L2-normalised mean vector per paper: ``(keys, (n, dim))``."""
        with self._lock:
            mat = self.matrix()
            by_key: dict[str, list[int]] = {}
            for i, m in enumerate(self.row_meta):
                by_key.setdefault(m["key"], []).append(i)
        keys = sorted(by_key)
        out = np.zeros((len(keys), self.dim), np.float32)
        for n, key in enumerate(keys):
            v = mat[by_key[key]].mean(axis=0)
            out[n] = v / (np.linalg.norm(v) or 1.0)
        return keys, out

    def search_chunks(self, query_vec: np.ndarray, top_k: int,
                      threshold: float = -1.0,
                      keys: Iterable[str] | None = None,
                      skip_refs: bool = True
                      ) -> list[tuple[str, int, float]]:
        """Best passages as ``(paper key, passage index, cosine)`` tuples.

        With ``keys`` the search is restricted to those papers (exact).
        Bibliography passages are left out unless ``skip_refs`` is False.
        """
        q = query_vec.astype(np.float32)
        with self._lock:
            if self.index is None or self.index.ntotal == 0:
                return []
            meta = self.row_meta
            if keys is None and not skip_refs:
                k = min(self.index.ntotal, top_k)
                sims, idxs = self.index.search(q.reshape(1, -1), k)
                pairs = [(int(r), float(s)) for s, r in zip(sims[0], idxs[0])
                         if r >= 0]
            else:
                # Exact search over the selected rows (a few thousand dot
                # products), so filtering never shortens the result list.
                wanted = set(keys) if keys is not None else None
                rows = [i for i, m in enumerate(meta)
                        if (wanted is None or m["key"] in wanted)
                        and not (skip_refs and m.get("ref"))]
                if not rows:
                    return []
                scores = self.matrix()[rows] @ q
                pairs = [(rows[int(o)], float(scores[int(o)]))
                         for o in np.argsort(-scores)[:top_k]]
            return [(meta[r]["key"], meta[r]["chunk"], s)
                    for r, s in pairs if s >= threshold]

    def ref_flags(self, key: str) -> list[bool]:
        """Bibliography flag of each passage of a paper, by passage index."""
        with self._lock:
            flags = sorted((m["chunk"], bool(m.get("ref")))
                           for m in self.row_meta if m["key"] == key)
        return [f for _, f in flags]

    def set_ref_flags(self, flags: dict[str, list[bool]], rule: int) -> None:
        """Replace the bibliography flag of every row.

        ``flags[key][i]`` is the flag of passage ``i``; ``rule`` is the
        version of the detection rule, stored so that an index flagged by an
        older rule is re-flagged (from stored text, without re-embedding).
        """
        with self._lock:
            for m in self.row_meta:
                paper = flags.get(m["key"], [])
                m["ref"] = m["chunk"] < len(paper) and bool(paper[m["chunk"]])
            self.ref_rule = rule

    # -- optional ANN optimisation ----------------------------------------- #
    def index_kind(self) -> str:
        if isinstance(self.index, faiss.IndexIVFFlat):
            return f"ivf (nlist={self.index.nlist})"
        return "flat (exact)"

    def optimize(self) -> str:
        """Convert a large flat index into an IVF index for faster search."""
        with self._lock:
            return self._optimize()

    def _optimize(self) -> str:
        if self.index is None or self.index.ntotal < IVF_THRESHOLD:
            return self.index_kind()
        if isinstance(self.index, faiss.IndexIVFFlat):
            return self.index_kind()
        n = self.index.ntotal
        nlist = max(16, int(np.sqrt(n)))
        vecs = self.index.reconstruct_n(0, n)
        quantizer = faiss.IndexFlatIP(self.dim)
        ivf = faiss.IndexIVFFlat(quantizer, self.dim, nlist,
                                 faiss.METRIC_INNER_PRODUCT)
        ivf.train(vecs)
        ivf.add(vecs)
        ivf.nprobe = min(nlist, 16)
        self.index = ivf
        return f"ivf (nlist={nlist})"

    # -- search ------------------------------------------------------------- #
    def search(self, query_vec: np.ndarray, top_k: int,
               threshold: float, aggregate: str = "max") -> list[dict]:
        """Return ranked papers above ``threshold`` cosine similarity."""
        with self._lock:
            return self._search(query_vec, top_k, threshold, aggregate)

    def _search(self, query_vec: np.ndarray, top_k: int,
                threshold: float, aggregate: str) -> list[dict]:
        if self.index is None or self.index.ntotal == 0:
            return []
        q = query_vec.reshape(1, -1).astype(np.float32)
        # Over-fetch chunks so several can map to the same paper.
        k = min(self.index.ntotal, max(top_k * 8, 40))
        sims, idxs = self.index.search(q, k)

        best: dict[str, list[float]] = {}
        for sim, row in zip(sims[0], idxs[0]):
            if row < 0:
                continue
            key = self.row_meta[row]["key"]
            best.setdefault(key, []).append(float(sim))

        results = []
        for key, scores in best.items():
            score = max(scores) if aggregate == "max" else float(np.mean(scores))
            if score < threshold:
                continue
            meta = self.papers.get(key, {})
            results.append({"key": key, "score": score,
                            "matched_chunks": len(scores), **meta})
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    @property
    def n_papers(self) -> int:
        return len(self.papers)

    @property
    def n_vectors(self) -> int:
        return self.index.ntotal if self.index is not None else 0
