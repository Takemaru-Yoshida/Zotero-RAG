"""Relation graph between the papers of the library.

Two kinds of edge, as in the web app:

* ``cites``   — paper A cites paper B. Zotero stores no citation links, so they
  are detected from the text: B's title appears in A's full text (normally in
  its reference list).
* ``similar`` — the two papers are mutual nearest neighbours by the cosine of
  their mean passage vectors.

``layout`` is a small force-directed layout (repulsion + springs + pull to the
centre) used by the GUI to place the nodes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from .library_db import LibraryDB
from .vector_store import VectorStore

# Short titles ("Attention", "Deep learning") would match by accident.
MIN_TITLE_CHARS = 25
_NON_ALNUM = re.compile(r"[^0-9a-z぀-ヿ一-鿿]+")


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str       # "cites" (source cites target) | "similar"
    weight: float


@dataclass(frozen=True)
class Graph:
    nodes: list[str]
    edges: list[Edge]

    def neighbours(self, key: str, kinds: tuple[str, ...] = ("cites", "similar")
                   ) -> list[tuple[str, Edge]]:
        out = []
        for e in self.edges:
            if e.kind not in kinds:
                continue
            if e.source == key:
                out.append((e.target, e))
            elif e.target == key:
                out.append((e.source, e))
        return out

    def degree(self, key: str) -> int:
        return len(self.neighbours(key))


def normalize(text: str) -> str:
    """Lower-case and drop everything but letters/digits (robust to PDF
    line breaks, hyphenation and punctuation differences)."""
    return _NON_ALNUM.sub("", text.lower())


def citation_edges(titles: dict[str, str], bodies: dict[str, str],
                   years: dict[str, str] | None = None) -> list[Edge]:
    """``A cites B`` when B's normalised title occurs in A's normalised text."""
    years = years or {}
    norm_titles = {k: normalize(t) for k, t in titles.items()}
    edges: list[Edge] = []
    for a, body in bodies.items():
        own = norm_titles.get(a, "")
        for b, title in norm_titles.items():
            if b == a or len(title) < MIN_TITLE_CHARS or title == own:
                continue
            ya, yb = years.get(a, ""), years.get(b, "")
            # A paper cannot cite something published well after it.
            if ya.isdigit() and yb.isdigit() and int(yb) > int(ya) + 1:
                continue
            if title in body:
                edges.append(Edge(a, b, "cites", 1.0))
    return edges


def similarity_edges(keys: list[str], vectors: np.ndarray, k: int,
                     skip: set[frozenset] | None = None) -> list[Edge]:
    """Mutual k-nearest-neighbour edges on cosine similarity."""
    n = len(keys)
    if n < 2 or k < 1:
        return []
    sims = vectors @ vectors.T
    np.fill_diagonal(sims, -1.0)
    k = min(k, n - 1)
    top = np.argsort(-sims, axis=1)[:, :k]
    nearest = [set(int(j) for j in row) for row in top]
    skip = skip or set()
    edges: list[Edge] = []
    for i in range(n):
        for j in nearest[i]:
            if i < j and i in nearest[j] \
                    and frozenset((keys[i], keys[j])) not in skip:
                edges.append(Edge(keys[i], keys[j], "similar", float(sims[i, j])))
    return edges


def build_graph(store: VectorStore, db: LibraryDB, neighbours: int) -> Graph:
    """Compute the full relation graph of the indexed library."""
    keys, vectors = store.doc_vectors()
    papers = store.papers_snapshot()
    titles = {k: papers.get(k, {}).get("title", "") for k in keys}
    years = {k: str(papers.get(k, {}).get("year", "")) for k in keys}
    bodies = {k: normalize(" ".join(c.text for c in db.get_chunks(k)))
              for k in keys}
    cites = citation_edges(titles, bodies, years)
    linked = {frozenset((e.source, e.target)) for e in cites}
    similar = similarity_edges(keys, vectors, neighbours, skip=linked)
    return Graph(keys, cites + similar)


def related(store: VectorStore, key: str, n: int = 4) -> list[tuple[str, float]]:
    """The ``n`` papers most similar to ``key`` as ``(key, cosine)``."""
    keys, vectors = store.doc_vectors()
    if key not in keys or len(keys) < 2:
        return []
    sims = vectors @ vectors[keys.index(key)]
    order = [int(i) for i in np.argsort(-sims) if keys[int(i)] != key][:n]
    return [(keys[i], float(sims[i])) for i in order]


def layout(nodes: list[str], edges: list[Edge], width: float, height: float,
           iterations: int = 300, seed: int = 42) -> dict[str, tuple[float, float]]:
    """Force-directed node positions inside a ``width`` x ``height`` box."""
    n = len(nodes)
    if n == 0:
        return {}
    rng = np.random.default_rng(seed)
    angle = np.arange(n) * 2.4            # golden-angle spiral start
    radius = 0.4 * np.sqrt((np.arange(n) + 1) / n)
    pos = np.stack([width / 2 + width * radius * np.cos(angle),
                    height / 2 + height * radius * np.sin(angle)], axis=1)
    pos += rng.normal(0, 1.0, pos.shape)
    index = {k: i for i, k in enumerate(nodes)}
    linked = [e for e in edges if e.source in index and e.target in index]
    src = np.array([index[e.source] for e in linked], dtype=int)
    dst = np.array([index[e.target] for e in linked], dtype=int)
    weights = np.array([e.weight for e in linked])
    centre = np.array([width / 2, height / 2])
    margin = np.array([60.0, 40.0])
    # Fruchterman-Reingold: nodes repel (k^2 / d), edges attract (d^2 / k),
    # and the step size ("temperature") cools down so the layout settles.
    k = 0.55 * np.sqrt(width * height / n)
    temperature = width / 10
    cooling = temperature / (iterations + 1)
    for _ in range(iterations):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.sqrt((delta ** 2).sum(axis=2)) + 1e-6
        disp = (delta * (k * k / dist ** 2)[:, :, None]).sum(axis=1)
        if len(linked):
            d = pos[dst] - pos[src]
            length = np.sqrt((d ** 2).sum(axis=1)) + 1e-6
            pull = d * (length / k * weights)[:, None]
            np.add.at(disp, src, pull)
            np.add.at(disp, dst, -pull)
        disp += (centre - pos) * 0.2     # gravity: keep loose nodes in view
        step = np.sqrt((disp ** 2).sum(axis=1)) + 1e-6
        pos += disp / step[:, None] * np.minimum(step, temperature)[:, None]
        pos = np.clip(pos, margin, np.array([width, height]) - margin)
        temperature -= cooling
    return {key: (float(pos[i, 0]), float(pos[i, 1])) for key, i in index.items()}
