"""Tests for PDF layout extraction (bounding boxes per sentence)."""
from pathlib import Path

from backend.layout import extract_layout

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "esempio.pdf"


def test_layout_has_pages_and_sentences():
    result = extract_layout(SAMPLE.read_bytes())
    assert len(result["pages"]) == 1
    assert result["pages"][0]["width"] > 0
    assert result["sentences"]
    assert "Nel mezzo del cammin" in result["sentences"][0]["text"]
    assert result["sentences"][0]["boxes"]


def test_boxes_are_normalised_and_tagged_with_page():
    result = extract_layout(SAMPLE.read_bytes())
    for sentence in result["sentences"]:
        for box in sentence["boxes"]:
            assert box["page"] == 0
            for key in ("x0", "y0", "x1", "y1"):
                assert 0.0 <= box[key] <= 1.0
            assert box["x1"] >= box["x0"]
            assert box["y1"] >= box["y0"]
