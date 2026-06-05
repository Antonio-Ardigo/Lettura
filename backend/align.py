"""Approximate word-level timing for a synthesized clip.

Kokoro's ONNX API returns only audio + sample rate (no phoneme/word
timestamps), so we estimate each word's time span by distributing the clip's
measured duration across the words in proportion to their length. It's not
frame-accurate, but it tracks the narration closely enough to drive a moving
word highlight.
"""
from __future__ import annotations


def align_words(text: str, duration: float, *, min_weight: int = 1) -> list[dict]:
    """Split text into words with estimated [start, end] times (seconds).

    Words partition [0, duration] contiguously, weighted by character length.
    """
    words = text.split()
    if not words or duration <= 0:
        return []
    weights = [max(len(word), min_weight) for word in words]
    total = sum(weights)
    spans: list[dict] = []
    cursor = 0.0
    for word, weight in zip(words, weights):
        start = cursor
        cursor += duration * weight / total
        spans.append({"text": word, "start": round(start, 3), "end": round(cursor, 3)})
    spans[-1]["end"] = round(duration, 3)  # avoid rounding drift at the end
    return spans
