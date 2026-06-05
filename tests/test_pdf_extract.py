"""Unit tests for text cleanup — pure logic, no heavy dependencies."""
from backend.pdf_extract import clean_text


def test_dehyphenates_words_split_across_lines():
    assert clean_text("lettura auto-\nmatica") == "lettura automatica"


def test_joins_soft_wrapped_lines_with_spaces():
    assert clean_text("riga uno\nriga due") == "riga uno riga due"


def test_preserves_paragraph_breaks():
    assert clean_text("paragrafo uno\n\nparagrafo due") == "paragrafo uno\n\nparagrafo due"


def test_collapses_repeated_whitespace():
    assert clean_text("a    b\t\tc") == "a b c"


def test_keeps_accented_characters():
    assert clean_text("perché città è università") == "perché città è università"
