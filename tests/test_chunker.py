"""Sentence splitting and passage packing."""
from __future__ import annotations

import pytest

from src.chunker import chunk_text, pack_sentences, split_sentences

pytestmark = pytest.mark.unit


def count_words(texts):
    """Stand-in tokenizer: one token per whitespace-separated word."""
    return [len(t.split()) for t in texts]


def test_splits_english_and_japanese_sentences():
    text = "Deep nets are hard to train. Residuals help! 残差学習は有効である。次の文です。"
    assert [s.text for s in split_sentences(text)] == [
        "Deep nets are hard to train.", "Residuals help!",
        "残差学習は有効である。", "次の文です。"]


def test_abbreviations_do_not_end_a_sentence():
    text = "He et al. (2016) fixed it, see Fig. 3 for details. Next one."
    assert [s.text for s in split_sentences(text)] == [
        "He et al. (2016) fixed it, see Fig. 3 for details.", "Next one."]


def test_pages_follow_form_feeds():
    sentences = split_sentences("Page one text.\fPage two text. More.\fPage three.")
    assert [s.page for s in sentences] == [1, 2, 2, 3]


def test_line_wrapping_and_hyphenation_are_undone():
    sentences = split_sentences("Repre-\nsentation matters\nfor vision.")
    assert sentences[0].text == "Representation matters for vision."


def test_chunks_respect_token_budget_and_do_not_overlap():
    text = " ".join(f"Sentence number {i} has six words." for i in range(10))
    chunks = chunk_text(text, count_words, max_tokens=12)
    assert all(len(c.text.split()) <= 12 for c in chunks)
    assert " ".join(c.text for c in chunks) == text   # nothing lost or repeated


def test_overlong_sentence_is_split():
    long_sentence = " ".join(["word"] * 100) + "."
    chunks = chunk_text(long_sentence, count_words, max_tokens=30)
    assert len(chunks) >= 4
    assert all(len(c.text.split()) <= 30 for c in chunks)


def test_chunk_page_is_the_page_of_its_first_sentence():
    chunks = chunk_text("One two three.\fFour five six.", count_words, max_tokens=3)
    assert [(c.text, c.page) for c in chunks] == [
        ("One two three.", 1), ("Four five six.", 2)]


def test_empty_input():
    assert split_sentences("") == []
    assert pack_sentences([], count_words, 10) == []
