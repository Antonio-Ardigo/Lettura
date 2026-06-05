"""Unit tests for approximate word alignment."""
from backend.align import align_words


def test_partitions_duration_contiguously():
    words = align_words("ab cd", 3.0)
    assert [w["text"] for w in words] == ["ab", "cd"]
    assert words[0]["start"] == 0.0
    assert words[0]["end"] == words[1]["start"]  # contiguous, no gaps/overlap
    assert words[-1]["end"] == 3.0  # covers the whole clip


def test_longer_words_get_more_time():
    words = align_words("a bbbb", 5.0)
    short = words[0]["end"] - words[0]["start"]
    long = words[1]["end"] - words[1]["start"]
    assert long > short


def test_times_are_monotonic():
    words = align_words("uno due tre quattro", 4.0)
    times = [w["start"] for w in words] + [words[-1]["end"]]
    assert times == sorted(times)


def test_empty_or_zero_duration():
    assert align_words("", 3.0) == []
    assert align_words("ciao", 0.0) == []
