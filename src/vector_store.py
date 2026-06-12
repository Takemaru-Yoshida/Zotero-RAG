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
from pathlib import Path

import faiss
import numpy as np

# Below this many chunks a brute-force flat index is fastest and exact.
IVF_THRESHOLD = 4000


class VectorStore:
    def __init__(self, config):
        self.config = config
        self.dim = config.embedding_dim
        self.index: faiss.Index | None = None
        # Per-vector metadata: list of {key, chunk}
        self.row_meta: list[dict] = []
        # Per-paper metadata: key -> {title, authors, year, ..., date_modified, n_chunks}
        self.papers: dict[str, dict] = {}

    # -- lifecycle ---------------------------------------------------------- #
    def load(self) -> bool:
        ip, mp = self.config.index_path, self.config.meta_path
        if ip.exists() and mp.exists():
            self.index = faiss.read_index(str(ip))
            data = json.loads(mp.read_text(encoding="utf-8"))
            self.row_meta = data.get("row_meta", [])
            self.papers = data.get("papers", {})
            return True
        return False

    def save(self) -> None:
        if self.index is None:
            return
        faiss.write_index(self.index, str(self.config.index_path))
        self.config.meta_path.write_text(
            json.dumps({"row_meta": self.row_meta, "papers": self.papers},
                       ensure_ascii=False),
            encoding="utf-8",
        )

    def _new_index(self) -> faiss.Index:
        return faiss.IndexFlatIP(self.dim)

    # -- incremental update ------------------------------------------------- #
    def indexed_keys(self) -> set[str]:
        return set(self.papers.keys())

    def needs_update(self, key: str, date_modified: str) -> bool:
        rec = self.papers.get(key)
        return rec is None or rec.get("date_modified") != date_modified

    def remove_paper(self, key: str) -> None:
        """Drop a paper and rebuild the index without its rows."""
        if key not in self.papers:
            return
        keep_rows = [i for i, m in enumerate(self.row_meta) if m["key"] != key]
        self._rebuild_from_rows(keep_rows)
        self.papers.pop(key, None)

    def _rebuild_from_rows(self, keep_rows: list[int]) -> None:
        if self.index is None or self.index.ntotal == 0:
            return
        vecs = self.index.reconstruct_n(0, self.index.ntotal)
        kept = vecs[keep_rows] if keep_rows else np.zeros((0, self.dim), np.float32)
        self.index = self._new_index()
        if len(kept):
            self.index.add(kept)
        self.row_meta = [self.row_meta[i] for i in keep_rows]

    def add_paper(self, paper_meta: dict, vectors: np.ndarray) -> None:
        """Add (or replace) a paper's chunk vectors."""
        key = paper_meta["key"]
        if key in self.papers:
            self.remove_paper(key)
        if self.index is None:
            self.index = self._new_index()
        if len(vectors):
            self.index.add(vectors)
            for c in range(len(vectors)):
                self.row_meta.append({"key": key, "chunk": c})
        paper_meta = dict(paper_meta)
        paper_meta["n_chunks"] = int(len(vectors))
        self.papers[key] = paper_meta

    # -- optional ANN optimisation ----------------------------------------- #
    def optimize(self) -> str:
        """Convert a large flat index into an IVF index for faster search."""
        if self.index is None or self.index.ntotal < IVF_THRESHOLD:
            return "flat (exact)"
        if isinstance(self.index, faiss.IndexIVFFlat):
            return "ivf"
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
