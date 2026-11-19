"""Sentence-aware chunking.

Full text is split into sentences (English and Japanese punctuation), and
consecutive sentences are packed into passages of at most ``max_tokens``
tokens. Passages do not overlap, so they can be shown one after another in the
document viewer, and each passage remembers the PDF page it starts on (pages
are separated by form feeds in Zotero's full-text cache and in our own PDF
extraction).

The module is pure Python: token counting is injected, so it can be unit
tested without loading the embedding model.
"""
from __future__ import annotations

import math
import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import Callable, Sequence

# Sentence boundary: closing punctuation followed by whitespace, a Japanese
# full stop, a blank line, or a page break.
_BOUNDARY = re.compile(
    r"(?<=[.!?])[\"'”’)\]]?\s+|(?<=[。！？])\s*|\s*\n\s*\n\s*|\s*\f\s*")
# A "." after one of these does not end a sentence.
_ABBREVIATIONS = re.compile(
    r"(?:\b(?:al|fig|figs|eq|eqs|e\.g|i\.e|etc|vs|cf|dr|prof|no|sec|ref|refs|"
    r"approx|resp|vol|pp|ed|eds)|\b[A-Z])\.[\"'”’)\]]?$", re.IGNORECASE)
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_WHITESPACE = re.compile(r"\s+")
_CJK_END = re.compile(r"[　-鿿＀-￯]$")

TokenCounter = Callable[[Sequence[str]], list[int]]


@dataclass(frozen=True)
class Sentence:
    text: str
    page: int   # 1-based page the sentence starts on


@dataclass(frozen=True)
class Chunk:
    text: str
    page: int


def _clean(raw: str) -> str:
    """Undo PDF line wrapping: join hyphenated words and collapse whitespace."""
    return _WHITESPACE.sub(" ", _HYPHEN_BREAK.sub(r"\1\2", raw)).strip()


def split_sentences(text: str) -> list[Sentence]:
    """Split ``text`` into cleaned sentences, tracking the page of each one."""
    if not text:
        return []
    page_breaks = [m.start() for m in re.finditer("\f", text)]
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        if m.end() <= start:
            continue
        spans.append((start, m.end()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))

    sentences: list[Sentence] = []
    pending = ""
    pending_page = 1
    for begin, end in spans:
        piece = _clean(text[begin:end])
        if not piece:
            continue
        if not pending:
            pending_page = bisect_right(page_breaks, begin) + 1
        pending = f"{pending} {piece}" if pending else piece
        # Keep "et al. (2020)" / "Fig. 3" / "J. Smith" in one sentence.
        if _ABBREVIATIONS.search(piece):
            continue
        sentences.append(Sentence(pending, pending_page))
        pending = ""
    if pending:
        sentences.append(Sentence(pending, pending_page))
    return sentences


def _split_long(text: str, n_tokens: int, max_tokens: int) -> list[str]:
    """Cut one over-long sentence into roughly equal pieces."""
    n_parts = max(2, math.ceil(n_tokens / max_tokens * 1.15))
    words = text.split(" ")
    if len(words) >= n_parts * 2:
        size = math.ceil(len(words) / n_parts)
        return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]
    size = math.ceil(len(text) / n_parts)   # e.g. Japanese: no spaces
    return [text[i:i + size] for i in range(0, len(text), size)]


def _join(a: str, b: str) -> str:
    return a + b if _CJK_END.search(a) else f"{a} {b}"


def pack_sentences(sentences: Sequence[Sentence], count_tokens: TokenCounter,
                   max_tokens: int) -> list[Chunk]:
    """Greedily pack sentences into chunks of at most ``max_tokens`` tokens."""
    if not sentences:
        return []
    counts = count_tokens([s.text for s in sentences])

    units: list[tuple[str, int, int]] = []   # (text, page, tokens)
    for sent, n in zip(sentences, counts):
        if n <= max_tokens:
            units.append((sent.text, sent.page, n))
            continue
        parts = _split_long(sent.text, n, max_tokens)
        for part, pn in zip(parts, count_tokens(parts)):
            units.append((part, sent.page, pn))

    chunks: list[Chunk] = []
    buf, buf_page, buf_tokens = "", 1, 0
    for text, page, n in units:
        if buf and buf_tokens + n > max_tokens:
            chunks.append(Chunk(buf, buf_page))
            buf, buf_tokens = "", 0
        if not buf:
            buf, buf_page = text, page
        else:
            buf = _join(buf, text)
        buf_tokens += n
    if buf:
        chunks.append(Chunk(buf, buf_page))
    return chunks


_REF_YEAR = re.compile(r"\b(?:19|20)\d{2}[a-z]?\b")
_REF_PAGES = re.compile(r"\d+\s*[–\-]\s*\d+")
_REF_VOLUME = re.compile(r"\b\d+\s?\(\d+\)")          # volume(issue)
_REF_HEADING = re.compile(
    r"(?:^|\s)(?:References|REFERENCES|Bibliography|BIBLIOGRAPHY|"
    r"Literature Cited|参考文献|引用文献)(?:\s|$)")


def is_reference_like(text: str) -> bool:
    """True for passages that are (mostly) a bibliography.

    Reference lists are dense in publication years and page ranges. They match
    almost any query on the paper's topic, so they are kept out of search
    results, markers and fact-check evidence.
    """
    words = max(len(text.split()), 1)
    years = len(_REF_YEAR.findall(text))
    if years < 4 or years / words < 0.025:
        return False
    return (len(_REF_PAGES.findall(text)) >= 2
            or len(_REF_VOLUME.findall(text)) >= 2
            or "doi" in text.lower() or years / words >= 0.04)


def is_noise(text: str) -> bool:
    """True for PDF-extraction debris: a few characters, or mostly symbols
    and digits (garbled figures, tables, watermarks)."""
    if len(text) < 40:
        return True
    wordlike = sum(c.isalpha() or c.isspace() for c in text)
    return wordlike / len(text) < 0.7


def reference_flags(texts: Sequence[str]) -> list[bool]:
    """Bibliography / noise flag for each passage of one paper, in order.

    Passages that look like a reference list are flagged individually; in
    addition, once a "References" heading has been seen in the second half of
    the paper and most of what follows looks like references, everything after
    the heading is flagged (this catches entries with unusual formatting).
    """
    flags = [is_reference_like(t) or is_noise(t) for t in texts]
    n = len(texts)
    if all(flags):
        return [False] * n    # e.g. a title-only entry: keep it searchable
    for i in range(n // 2, n):
        if not _REF_HEADING.search(texts[i]):
            continue
        tail = flags[i + 1:]
        if not tail or sum(tail) / len(tail) >= 0.5:
            return flags[:i + 1] + [True] * len(tail)
    return flags


def chunk_text(text: str, count_tokens: TokenCounter,
               max_tokens: int) -> list[Chunk]:
    """Split ``text`` into page-tagged, non-overlapping passages."""
    return pack_sentences(split_sentences(text), count_tokens, max_tokens)
