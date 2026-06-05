"""Unit tests for export chunking (pure logic, no audio deps)."""
from backend.export import chunk_sentences


def test_groups_sentences_under_limit():
    sentences = ["Uno.", "Due.", "Tre."]
    # "Uno. Due." = 9 chars; adding "Tre." (-> 14) exceeds 9 -> new chunk.
    assert list(chunk_sentences(sentences, max_chars=9)) == ["Uno. Due.", "Tre."]


def test_never_splits_a_single_long_sentence():
    long_sentence = "x" * 50
    assert list(chunk_sentences([long_sentence], max_chars=10)) == [long_sentence]


def test_empty_input_yields_nothing():
    assert list(chunk_sentences([])) == []
