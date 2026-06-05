"""Unit tests for Italian sentence segmentation."""
from backend.segment import is_sentence_end, segment_sentences


def test_splits_basic_sentences():
    assert segment_sentences("Ciao. Come stai? Bene!") == [
        "Ciao.",
        "Come stai?",
        "Bene!",
    ]


def test_does_not_split_on_abbreviation():
    assert segment_sentences("Il Dott. Rossi è qui.") == ["Il Dott. Rossi è qui."]


def test_keeps_paragraphs_separate():
    assert segment_sentences("Primo.\n\nSecondo.") == ["Primo.", "Secondo."]


def test_handles_ellipsis():
    assert segment_sentences("Aspetta... Arrivo.") == ["Aspetta...", "Arrivo."]


def test_does_not_split_after_single_initial():
    assert segment_sentences("Scritto da A. Manzoni qui.") == [
        "Scritto da A. Manzoni qui."
    ]


def test_empty_text_returns_empty_list():
    assert segment_sentences("   ") == []


def test_is_sentence_end():
    assert is_sentence_end("vita.")
    assert is_sentence_end("Bene!")
    assert is_sentence_end("oscura,") is False  # comma is not terminal
    assert is_sentence_end("Dott.") is False  # abbreviation
    assert is_sentence_end("A.") is False  # single initial
    assert is_sentence_end("Manzoni") is False  # no terminal punctuation
