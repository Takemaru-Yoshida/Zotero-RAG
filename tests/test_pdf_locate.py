"""Locating a sentence of the extracted text in a PDF page's text layer."""
from __future__ import annotations

import pytest

from src.pdf_locate import letters_of, locate

pytestmark = pytest.mark.unit

PAGE = ("1 Introduction\r\nAttention selects relevant informa-\r\ntion from the "
        "visual scene. The ﬁrst stage of processing is thought\r\nto be "
        "parallel across the visual ﬁeld [3]. Later stages are\r\nlimited in "
        "capacity and operate on one object at a time.\r\n2\r\n")


def _found(sentence, page=PAGE):
    """The marked text; several parts are joined with " … "."""
    spans = locate(letters_of(page), sentence)
    return " … ".join(page[a:a + n] for a, n in spans) if spans else None


def test_line_breaks_hyphenation_and_ligatures_do_not_matter():
    assert _found("Attention selects relevant information from the visual "
                  "scene.") == ("Attention selects relevant informa-\r\ntion "
                                "from the visual scene.")
    assert _found("The first stage of processing is thought to be parallel "
                  "across the visual field [3].").startswith("The ﬁrst stage")


def test_a_difference_in_the_middle_is_bridged_by_both_ends():
    got = _found("The first stage of processing is thought to be parallel "
                 "across the visual field. Later stages are limited in "
                 "capacity and operate on one object at a time.")
    assert got.startswith("The ﬁrst stage") and got.endswith("at a time.")


def test_a_sentence_cut_by_the_page_break_is_marked_up_to_the_break():
    got = _found("Later stages are limited in capacity and operate on one "
                 "object at a time. 2 This continues on the following page "
                 "with many more words than fit here.")
    assert got.startswith("Later stages are") and got.endswith("2")
    got = _found("These words are on the page before this one, and only the "
                 "end of it, attention selects relevant information from the "
                 "visual scene.")
    assert got.endswith("from the visual scene.")


def test_text_that_is_not_on_the_page_is_not_found():
    assert _found("Representational similarity analysis compares patterns "
                  "of activity across conditions.") is None
    assert _found("Attention") is None            # too short to be sure
    assert _found("Attention selects relevant information.", page="") is None


def test_japanese_text_without_spaces():
    page = "注意は視覚情\r\n報の選択に関わる。前頭前野がその制御を担う。"
    assert _found("注意は視覚情報の選択に関わる。", page) == "注意は視覚情\r\n報の選択に関わる。"


def test_other_text_between_the_two_ends_is_left_unmarked():
    page = ("Why vision is not both hierarchical and feedforward\r\n"
            "Michael H. Herzog and Aaron M. Clarke\r\nLaboratory of "
            "Psychophysics, Brain Mind Institute, Lausanne, Switzerland\r\n"
            "Edited by: Somebody Else, University of Somewhere, Austria\r\n"
            "In classical models of object recognition, basic features are "
            "analyzed by independent filters.\r\n")
    got = _found("Why vision is not both hierarchical and feedforward In "
                 "classical models of object recognition, basic features are "
                 "analyzed by independent filters.", page)
    assert got == ("Why vision is not both hierarchical and feedforward … "
                   "In classical models of object recognition, basic features "
                   "are analyzed by independent filters.")
