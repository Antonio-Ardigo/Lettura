"""Italian sentence segmentation for read-along playback.

A lightweight, dependency-free heuristic: split on sentence-ending punctuation
followed by whitespace, while avoiding common Italian abbreviations, single
initials, and mid-sentence lowercase continuations. Good enough to drive
sentence-level highlighting without pulling in a full NLP stack.
"""
from __future__ import annotations

import re

# Common Italian abbreviations that end in a period but not a sentence.
_ABBREVIATIONS = {
    "sig", "sigg", "sig.ra", "dott", "dr", "prof", "egr", "gent", "ing",
    "avv", "rag", "geom", "arch", "on", "rev", "ecc", "es", "pag", "pagg",
    "art", "artt", "cap", "fig", "tab", "vol", "nr", "tel", "vs", "ca",
    "seg", "segg", "gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago",
    "set", "sett", "ott", "nov", "dic",
}

# Sentence-ending punctuation, optional closing quotes/brackets, then spaces.
_BOUNDARY = re.compile("[.!?…]+[\"»”'’)\\]]*\\s+")


def segment_sentences(text: str) -> list[str]:
    """Split cleaned text into sentences, preserving paragraph order."""
    sentences: list[str] = []
    for paragraph in text.split("\n\n"):
        stripped = paragraph.strip()
        if stripped:
            sentences.extend(_split_paragraph(stripped))
    return sentences


def _split_paragraph(paragraph: str) -> list[str]:
    out: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(paragraph):
        if not _is_real_boundary(paragraph, match.start(), match.end()):
            continue
        sentence = paragraph[start:match.end()].strip()
        if sentence:
            out.append(sentence)
            start = match.end()
    tail = paragraph[start:].strip()
    if tail:
        out.append(tail)
    return out


def _is_real_boundary(paragraph: str, punct_pos: int, after_pos: int) -> bool:
    # The word immediately before the punctuation.
    head = paragraph[:punct_pos].split()
    preceding = head[-1].lower().rstrip(".") if head else ""
    if preceding in _ABBREVIATIONS or len(preceding) == 1:
        return False
    # A lowercase start after the break usually means it wasn't a real end.
    nxt = paragraph[after_pos:after_pos + 1]
    return not nxt.islower()
