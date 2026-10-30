from __future__ import annotations

import pytest

from llm_search_eval.text import detect_language, is_rtl, normalize_text, tokenize


def test_arabic_letters_normalize_to_persian():
    assert normalize_text("كيف") == normalize_text("کیف")


def test_digits_are_unified():
    assert normalize_text("۱۲۸ گیگ") == "128 گیگ"
    assert normalize_text("١٢٨") == "128"


def test_diacritics_tatweel_and_zwnj():
    assert normalize_text("كـتـاب") == "کتاب"
    assert normalize_text("کِتاب") == "کتاب"
    assert normalize_text("کتاب\u200cها") == "کتاب ها"


def test_case_and_whitespace():
    assert normalize_text("  Hello   WORLD ") == "hello world"


def test_tokenize_drops_stopwords_in_both_languages():
    assert tokenize("the best red shoes for running") == ["red", "shoes", "running"]
    assert tokenize("خرید کفش برای دویدن") == ["کفش", "دویدن"]
    assert "the" in tokenize("the shoes", drop_stopwords=False)


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("wireless headphones", "en"),
        ("هدفون بی سیم", "fa"),
        ("گوشی سامسونگ S24", "fa"),
        ("12345", "und"),
    ],
)
def test_detect_language(text, lang):
    assert detect_language(text) == lang


def test_is_rtl():
    assert is_rtl("سلام")
    assert not is_rtl("hello")
