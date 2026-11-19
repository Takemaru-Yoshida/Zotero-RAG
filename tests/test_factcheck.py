"""Citation parsing, paper matching and the verdict rule (no models needed)."""
from __future__ import annotations

import pytest

from src.factcheck import Candidate, decide, extract_citations, match_documents
from src.nli import NliScores

pytestmark = pytest.mark.unit

PAPERS = {
    "HE16": {"authors": ["Kaiming He", "Xiangyu Zhang"], "year": "2016"},
    "HE15": {"authors": ["Kaiming He"], "year": "2015"},
    "TREUE": {"authors": ["Stefan Treue", "Julio C. Martinez-Trujillo"], "year": "1999"},
    "TANAKA": {"authors": ["太郎 田中"], "year": "2021"},
}


def cand(sim: float, entail: float, contra: float, idx: int = 0) -> Candidate:
    return Candidate("K", idx, 1, f"evidence {idx}", sim,
                     NliScores(entail, 1 - entail - contra, contra))


def test_parenthetical_citation():
    (c,) = extract_citations("Residual nets reach 152 layers (He et al., 2016).")
    assert (c.author, c.year) == ("He", "2016")
    assert c.claim == "Residual nets reach 152 layers."


def test_multiple_citations_in_one_parenthesis():
    cites = extract_citations(
        "Attention changes gain (e.g., Treue & Martinez-Trujillo, 1999; "
        "Reynolds and Heeger, 2009).")
    assert [(c.author, c.year) for c in cites] == [
        ("Treue", "1999"), ("Reynolds", "2009")]
    assert cites[0].claim == "Attention changes gain."


def test_surname_particles_are_skipped():
    (c,) = extract_citations("Gain changes with attention (van der Berg et al., 2018).")
    assert (c.author, c.year) == ("Berg", "2018")


def test_narrative_citation():
    (c,) = extract_citations("Lindsay and Miller (2018) implemented attention in a CNN.")
    assert (c.author, c.year) == ("Lindsay", "2018")


def test_japanese_citation_with_fullwidth_parentheses():
    (c,) = extract_citations("田中ら（2021）は空間注意で説明できると述べた。")
    assert c.year == "2021"
    assert match_documents(c.author, c.year, PAPERS) == ["TANAKA"]


def test_sentences_without_citations_are_ignored():
    assert extract_citations("No citation here. Sample size was (n = 20).") == []


def test_match_by_surname_and_year():
    assert match_documents("He", "2016", PAPERS) == ["HE16"]
    assert match_documents("Martinez-Trujillo", "1999", PAPERS) == ["TREUE"]
    assert match_documents("Nobody", "2016", PAPERS) == []


def test_first_author_one_year_off_is_accepted_as_fallback():
    assert match_documents("He", "2014", PAPERS) == ["HE15"]
    assert match_documents("Zhang", "2017", PAPERS) == []   # not first author


def test_supported_when_a_passage_entails():
    verdict, best, score, _ = decide(
        [cand(0.9, 0.1, 0.1, 0), cand(0.8, 0.92, 0.02, 1)], 0.5, 0.5)
    assert (verdict, best.chunk_idx, score) == ("supported", 1, 0.92)


def test_refuted_when_most_passages_contradict():
    verdict, best, score, _ = decide(
        [cand(0.8, 0.05, 0.83, 0), cand(0.9, 0.02, 0.71, 1), cand(0.7, 0.0, 0.2, 2)],
        0.5, 0.5)
    # median contradiction = 0.71; evidence = closest contradicting sentence
    assert (verdict, best.chunk_idx) == ("refuted", 1)
    assert score == pytest.approx(0.71)


def test_one_contradicting_passage_is_not_enough():
    verdict, best, _, _ = decide(
        [cand(0.9, 0.1, 0.1, 0), cand(0.85, 0.1, 0.1, 1), cand(0.5, 0.0, 0.95, 2)],
        0.5, 0.5)
    assert (verdict, best.chunk_idx) == ("partial", 0)


def test_one_noisy_contradiction_does_not_override_support():
    verdict, best, score, _ = decide(
        [cand(0.85, 0.01, 0.36, 0), cand(0.86, 0.06, 0.88, 1),
         cand(0.84, 0.60, 0.02, 2), cand(0.83, 0.35, 0.02, 3)], 0.5, 0.5)
    assert (verdict, best.chunk_idx, score) == ("supported", 2, 0.60)


def test_conflicting_signals_are_reported_as_partial():
    verdict, _, _, note = decide(
        [cand(0.9, 0.9, 0.05, 0), cand(0.8, 0.0, 0.9, 1), cand(0.7, 0.0, 0.8, 2)],
        0.5, 0.5)
    assert verdict == "partial" and "両方" in note


def test_decide_requires_candidates():
    with pytest.raises(ValueError):
        decide([], 0.5, 0.5)
