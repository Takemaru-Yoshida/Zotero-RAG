"""Relation graph edges and layout."""
from __future__ import annotations

import numpy as np
import pytest

from src.graph import (Edge, Graph, citation_edges, layout, normalize,
                       similarity_edges)

pytestmark = pytest.mark.unit

TITLE_B = "Representational similarity analysis connecting the branches"


def test_normalize_is_robust_to_pdf_artifacts():
    assert normalize("Deep Residual\nLearning – for Image") == "deepresiduallearningforimage"


def test_citation_detected_from_title_in_text():
    titles = {"A": "A later paper about attention in networks", "B": TITLE_B}
    bodies = {"A": normalize(f"Intro ... References: Kriegeskorte N. {TITLE_B}."),
              "B": normalize(f"{TITLE_B}. We propose RSA.")}
    edges = citation_edges(titles, bodies, {"A": "2018", "B": "2008"})
    assert edges == [Edge("A", "B", "cites", 1.0)]


def test_short_titles_and_future_papers_are_not_cited():
    titles = {"A": "Attention", "B": TITLE_B}
    bodies = {"A": normalize("old paper"), "B": normalize("mentions attention a lot")}
    assert citation_edges(titles, bodies) == []          # "Attention" too short
    bodies["A"] = normalize(TITLE_B)
    assert citation_edges(titles, bodies, {"A": "2000", "B": "2008"}) == []


def test_similarity_edges_are_mutual_nearest_neighbours():
    vectors = np.array([[1, 0], [0.99, 0.14], [0, 1], [0.14, 0.99]], np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    edges = similarity_edges(["a", "b", "c", "d"], vectors, k=1)
    assert {(e.source, e.target) for e in edges} == {("a", "b"), ("c", "d")}
    skipped = similarity_edges(["a", "b", "c", "d"], vectors, k=1,
                               skip={frozenset(("a", "b"))})
    assert {(e.source, e.target) for e in skipped} == {("c", "d")}


def test_graph_neighbours_and_degree():
    graph = Graph(["a", "b", "c"], [Edge("a", "b", "cites", 1.0),
                                    Edge("c", "a", "similar", 0.9)])
    assert [k for k, _ in graph.neighbours("a")] == ["b", "c"]
    assert [k for k, _ in graph.neighbours("a", ("cites",))] == ["b"]
    assert graph.degree("b") == 1


def test_layout_stays_in_bounds_and_pulls_linked_nodes_together():
    nodes = [f"n{i}" for i in range(12)]
    edges = [Edge("n0", "n1", "cites", 1.0)]
    pos = layout(nodes, edges, 800, 560)
    assert set(pos) == set(nodes)
    assert all(0 <= x <= 800 and 0 <= y <= 560 for x, y in pos.values())
    dist = lambda a, b: np.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1])
    others = [dist("n0", n) for n in nodes[2:]]
    assert dist("n0", "n1") < np.mean(others)
    assert layout([], [], 800, 560) == {}
