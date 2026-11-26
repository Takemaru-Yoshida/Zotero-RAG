"""Find a sentence of the extracted text in the text layer of a PDF page.

The passages shown in the app come from Zotero's full-text cache, the PDF
viewer reads the page text through QtPdf. The two agree on the words but not
on line breaks, hyphenation, ligatures or spacing, so both sides are reduced
to their letters before comparing, and a sentence that still differs somewhere
in the middle is found by its beginning and its end.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

_HYPHENS = frozenset("-­‐‑‒–—−")
# Letters of a sentence's beginning / end that have to match.
ANCHOR = 32
MIN_ANCHOR = 12


@dataclass(frozen=True)
class PageText:
    """The letters of a page, each with its position in the page's text."""
    letters: str
    index: tuple[int, ...]


def letters_of(text: str) -> PageText:
    """Lower-case letters of ``text`` without spaces, hyphens and control
    characters, with ligatures and full-width forms spelled out."""
    letters: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch).lower():
            if c.isspace() or c in _HYPHENS or unicodedata.category(c)[0] == "C":
                continue
            letters.append(c)
            index.append(i)
    return PageText("".join(letters), tuple(index))


def _common(a: str, b: str) -> int:
    """Length of the common beginning of ``a`` and ``b``."""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def locate(page: PageText, sentence: str) -> list[tuple[int, int]]:
    """Where ``sentence`` is in the page's text, as ``(start, length)`` spans;
    empty when it is not on the page.

    Usually one span. When the page has other text between the beginning and
    the end of the sentence (a title followed by the author list before the
    abstract goes on, a figure in the middle), the two parts are returned
    separately. A sentence that runs over the page break is located by the
    part that is on this page.
    """
    wanted = letters_of(sentence).letters
    text = page.letters
    if len(wanted) < MIN_ANCHOR or not text:
        return []
    exact = text.find(wanted)
    if exact >= 0:
        return [_span(page, exact, exact + len(wanted))]
    size = min(ANCHOR, len(wanted) // 2)
    if size < MIN_ANCHOR:
        return []
    head = text.find(wanted[:size])
    tail = text.find(wanted[-size:], max(head, 0))
    end = tail + size
    # A small difference in between (a footnote mark, a formula) is marked
    # along with the rest.
    if head >= 0 and tail >= head and end - head <= len(wanted) * 1.15 + 8:
        return [_span(page, head, end)]
    parts: list[tuple[int, int]] = []
    if head >= 0:
        parts.append((head, head + _common(text[head:], wanted)))
    if tail >= 0:
        back = _common(text[end - 1::-1], wanted[::-1])
        if not parts or end - back >= parts[0][1]:
            parts.append((end - back, end))
        else:                           # the two parts overlap: one stretch
            parts = [(parts[0][0], end)]
    return [_span(page, first, last) for first, last in parts]


def _span(page: PageText, first: int, last: int) -> tuple[int, int]:
    start = page.index[first]
    return start, page.index[last - 1] + 1 - start
