"""Citation fact-check.

For every cited claim in a manuscript — ``... (Author et al., 2020).`` or
``Author et al. (2020) showed ...`` — the pipeline:

1. finds the cited paper in the library by author surname + year,
2. retrieves the passages of that paper closest in meaning to the claim,
3. asks a local NLI model whether the best sentences entail or contradict it,
4. returns one of four verdicts with the evidence sentence:
   ``supported`` / ``partial`` / ``refuted`` / ``not_found``.

Parsing, matching and the verdict rule are pure functions so they can be unit
tested without any model.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Callable, Optional, Sequence

import numpy as np

from .chunker import split_sentences
from .embedder import Embedder
from .library_db import LibraryDB
from .nli import NliModel, NliScores
from .vector_store import VectorStore

VERDICTS = ("supported", "partial", "refuted", "not_found")
ProgressCb = Optional[Callable[[str, float], None]]

_NAME = r"[A-Za-zÀ-ɏ぀-ヿ一-鿿][\w'’\-]*"
_YEAR = r"(?:19|20)\d{2}"
_PAREN = re.compile(rf"\(([^()]*?{_YEAR}[a-z]?[^()]*?)\)")
_PARTICLE = r"(?:(?:van|von|de|der|den|del|della|la|le|di|da)\s+)*"
_CITE_PART = re.compile(rf"({_PARTICLE}{_NAME})[^\d]{{0,80}}?({_YEAR})")
_LEAD_IN = re.compile(r"^(?:e\.g\.|i\.e\.|see also|see|cf\.|also|but see)[,\s]*",
                      re.IGNORECASE)
_NARRATIVE = re.compile(
    rf"([A-Z][\w'’\-]+)(?:\s+et al\.?|\s+(?:and|&)\s+[A-Z][\w'’\-]+)?"
    rf"\s*\(({_YEAR})[a-z]?\)")
_NARRATIVE_JA = re.compile(rf"([぀-ヿ一-鿿]{{1,8}}?)ら?\s*\(({_YEAR})\)")
_FULLWIDTH = str.maketrans("（）；，", "();,")


@dataclass(frozen=True)
class CitedClaim:
    claim: str       # the sentence without its citation
    citation: str    # e.g. "He et al., 2016"
    author: str      # first surname in the citation
    year: str


@dataclass(frozen=True)
class Candidate:
    """One passage of the cited paper tested against the claim."""
    key: str
    chunk_idx: int
    page: int
    evidence: str        # the sentence shown to the user
    similarity: float    # cosine(claim, evidence sentence)
    nli: NliScores


@dataclass
class CitationCheck:
    claim: str
    citation: str
    verdict: str
    score: float = 0.0
    note: str = ""
    key: str = ""            # matched paper ("" when not found)
    title: str = ""
    authors: Sequence[str] = ()
    year: str = ""
    chunk_idx: int = -1
    page: int = 0
    evidence: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["authors"] = list(self.authors)
        return d


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def extract_citations(text: str) -> list[CitedClaim]:
    """Find every (claim sentence, citation) pair in a manuscript."""
    out: list[CitedClaim] = []
    for sent in split_sentences((text or "").translate(_FULLWIDTH)):
        s = sent.text
        found: list[tuple[str, str, str]] = []   # (citation, author, year)
        for m in _PAREN.finditer(s):
            for part in re.split(r";", m.group(1)):
                part = _LEAD_IN.sub("", part.strip())
                cm = _CITE_PART.match(part)
                if cm:
                    # "van der Berg" is matched on its last word, "Berg".
                    surname = cm.group(1).split()[-1]
                    if len(surname) >= 2:
                        found.append((part, surname, cm.group(2)))
        for pattern in (_NARRATIVE, _NARRATIVE_JA):
            for m in pattern.finditer(s):
                found.append((m.group(0), m.group(1), m.group(2)))
        if not found:
            continue
        claim = re.sub(r"\s+([.,;:。、])", r"\1", _PAREN.sub("", s))
        claim = re.sub(r"\s{2,}", " ", claim).strip()
        seen: set[tuple[str, str]] = set()
        for citation, author, year in found:
            author = author.rstrip("ら") or author
            if (author.casefold(), year) in seen:
                continue
            seen.add((author.casefold(), year))
            out.append(CitedClaim(claim, citation, author, year))
    return out


def _has_author(name: str, author: str) -> bool:
    if re.search(r"[぀-ヿ一-鿿]", author):
        # Japanese has no word breaks, so the captured "author" may carry
        # leading text ("先行研究では田中"): accept a name part as its suffix.
        return author in name or any(
            len(part) >= 2 and author.endswith(part) for part in name.split())
    return author.casefold() in re.split(r"[\s,]+", name.casefold())


def match_documents(author: str, year: str, papers: dict[str, dict]) -> list[str]:
    """Keys of library papers matching a citation, best match first.

    A paper matches when its year equals the cited year and one of its
    authors has the cited surname (first-author matches rank first). If
    nothing matches, first-author papers one year off are accepted, because
    preprint and publication years often differ.
    """
    exact: list[tuple[int, str]] = []
    near: list[str] = []
    for key, meta in papers.items():
        names = meta.get("authors") or []
        pos = next((i for i, n in enumerate(names) if _has_author(n, author)), None)
        if pos is None:
            continue
        paper_year = str(meta.get("year", ""))
        if paper_year == year:
            exact.append((pos, key))
        elif (pos == 0 and paper_year.isdigit()
              and abs(int(paper_year) - int(year)) == 1):
            near.append(key)
    return [k for _, k in sorted(exact)] or sorted(near)


def decide(candidates: Sequence[Candidate], entail_threshold: float,
           contradict_threshold: float) -> tuple[str, Candidate, float, str]:
    """Turn NLI scores into ``(verdict, evidence, score, note)``.

    A single NLI score is noisy: the model sometimes reports entailment or
    contradiction for a passage that has nothing to do with the claim. The
    rule therefore looks at the candidates together:

    * ``refuted``   — the *median* contradiction over the candidates reaches
      the threshold (most of the relevant text disagrees) and nothing entails;
    * ``supported`` — some passage entails the claim and the candidates do not
      contradict it as a group;
    * ``partial``   — anything else, including conflicting signals.

    The evidence shown is, among the passages behind the verdict, the one
    whose sentence is closest in meaning to the claim.
    """
    if not candidates:
        raise ValueError("decide() needs at least one candidate")
    entail = max(c.nli.entailment for c in candidates)
    contra = float(np.median([c.nli.contradiction for c in candidates]))
    closest = max(candidates, key=lambda c: c.similarity)
    supports = entail >= entail_threshold
    refutes = contra >= contradict_threshold
    if supports and not refutes:
        pool = [c for c in candidates if c.nli.entailment >= entail_threshold]
        return ("supported", max(pool, key=lambda c: c.similarity), entail,
                "原文のこの記述が主張を支持しています。")
    if refutes and not supports:
        pool = [c for c in candidates
                if c.nli.contradiction >= contradict_threshold]
        return ("refuted", max(pool, key=lambda c: c.similarity), contra,
                "原文の記述は主張と矛盾しています。引用内容を確認してください。")
    if supports and refutes:
        return ("partial", closest, entail,
                "支持する記述と矛盾する記述の両方が見つかりました。"
                "原文を確認してください。")
    return ("partial", closest, entail,
            "主張を直接支持する記述は見つかりませんでした。"
            "本文中で最も近い記述を表示しています。")


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
class FactChecker:
    def __init__(self, config, embedder: Embedder, store: VectorStore,
                 db: LibraryDB, nli: NliModel):
        self.config = config
        self.embedder = embedder
        self.store = store
        self.db = db
        self.nli = nli

    def _candidates(self, claim: str, keys: list[str]) -> list[Candidate]:
        qvec = self.embedder.embed_query(claim)
        hits = self.store.search_chunks(
            qvec, self.config.factcheck_candidates, keys=keys)
        premises: list[str] = []
        drafts: list[tuple[str, int, int, str, float]] = []
        for key, idx, sim in hits:
            row = self.db.get_chunk(key, idx)
            if row is None:
                continue
            sentences = [s.text for s in split_sentences(row.text)
                         if len(s.text) >= 25]
            if len(sentences) < 2:
                premise = evidence = row.text
            else:
                scores = self.embedder.embed_passages(sentences) @ qvec
                best = int(np.argmax(scores))
                evidence = sentences[best]
                sim = float(scores[best])   # closeness of the shown sentence
                # One sentence of context on each side helps the NLI model.
                premise = " ".join(sentences[max(0, best - 1):best + 2])
            premises.append(premise)
            drafts.append((key, idx, row.page, evidence, sim))
        scores = self.nli.classify([(p, claim) for p in premises])
        return [Candidate(*d, nli=s) for d, s in zip(drafts, scores)]

    def check_claim(self, cited: CitedClaim) -> CitationCheck:
        papers = self.store.papers_snapshot()
        keys = match_documents(cited.author, cited.year, papers)
        if not keys:
            return CitationCheck(
                cited.claim, cited.citation, "not_found",
                note="ライブラリ内に該当する文献がありません。実在しない引用"
                     "（ハルシネーション）か、未登録の文献の可能性があります。")
        candidates = self._candidates(cited.claim, keys)
        if not candidates:
            meta = papers[keys[0]]
            return CitationCheck(
                cited.claim, cited.citation, "partial", key=keys[0],
                title=meta.get("title", ""), authors=meta.get("authors", []),
                year=str(meta.get("year", "")),
                note="文献は見つかりましたが、照合できる本文がありません。")
        verdict, best, score, note = decide(
            candidates, self.config.entail_threshold,
            self.config.contradict_threshold)
        meta = papers.get(best.key, {})
        if str(meta.get("year", "")) != cited.year:
            note += f"（引用の年 {cited.year} と文献の年 {meta.get('year')} が異なります）"
        return CitationCheck(
            cited.claim, cited.citation, verdict, score=score, note=note,
            key=best.key, title=meta.get("title", ""),
            authors=meta.get("authors", []), year=str(meta.get("year", "")),
            chunk_idx=best.chunk_idx, page=best.page, evidence=best.evidence)

    def check(self, text: str, progress: ProgressCb = None,
              save: bool = True) -> list[CitationCheck]:
        """Fact-check every citation in ``text``; optionally keep the run."""
        claims = extract_citations(text)
        results: list[CitationCheck] = []
        for i, cited in enumerate(claims):
            if progress:
                progress(f"照合中 [{i + 1}/{len(claims)}] ({cited.citation})",
                         i / len(claims))
            results.append(self.check_claim(cited))
        if progress:
            progress("完了", 1.0)
        if save and results:
            title = re.sub(r"\s+", " ", text).strip()[:40]
            self.db.add_factcheck(title, text, [r.to_dict() for r in results])
        return results
