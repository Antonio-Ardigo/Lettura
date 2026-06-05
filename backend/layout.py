"""Map sentences to their location on the original PDF page.

For read-along highlighting on the rendered document, the frontend needs, for
each sentence, the rectangles it occupies on the page. pdfplumber gives every
word a bounding box; we segment the word stream into sentences and merge each
sentence's words into per-line rectangles.

Coordinates are normalised to [0, 1] of the page width/height (origin top-left),
so the frontend can scale them to whatever size it renders the page at.

Only works on digital PDFs (a text layer with word boxes); scanned/OCR-only
pages yield no boxes and are simply skipped here.
"""
from __future__ import annotations

import io

import pdfplumber

from . import segment

# Words whose top edges are within this fraction of page height count as one line.
_LINE_TOLERANCE = 0.012


def extract_layout(pdf_bytes: bytes) -> dict:
    """Return {"pages": [{width, height}], "sentences": [{text, boxes}]}.

    Box coordinates are normalised to [0, 1]; each box carries its page index.
    """
    pages: list[dict] = []
    words: list[dict] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_index, page in enumerate(pdf.pages):
            width = float(page.width) or 1.0
            height = float(page.height) or 1.0
            pages.append({"width": width, "height": height})
            for word in page.extract_words(use_text_flow=True):
                words.append(
                    {
                        "page": page_index,
                        "text": word["text"],
                        "x0": word["x0"] / width,
                        "y0": word["top"] / height,
                        "x1": word["x1"] / width,
                        "y1": word["bottom"] / height,
                    }
                )

    return {"pages": pages, "sentences": _sentences_from_words(words)}


def _sentences_from_words(words: list[dict]) -> list[dict]:
    sentences: list[dict] = []
    current: list[dict] = []
    for word in words:
        current.append(word)
        if segment.is_sentence_end(word["text"]):
            sentences.append(_build_sentence(current))
            current = []
    if current:
        sentences.append(_build_sentence(current))
    return sentences


def _build_sentence(words: list[dict]) -> dict:
    text = " ".join(word["text"] for word in words)
    return {"text": text, "boxes": _merge_line_boxes(words)}


def _merge_line_boxes(words: list[dict]) -> list[dict]:
    """Merge consecutive words on the same page+line into rectangles."""
    boxes: list[dict] = []
    for word in words:
        if boxes:
            last = boxes[-1]
            same_line = (
                word["page"] == last["page"]
                and abs(word["y0"] - last["y0"]) < _LINE_TOLERANCE
                and word["x0"] >= last["x0"] - _LINE_TOLERANCE
            )
            if same_line:
                last["x1"] = max(last["x1"], word["x1"])
                last["y0"] = min(last["y0"], word["y0"])
                last["y1"] = max(last["y1"], word["y1"])
                continue
        boxes.append(
            {
                "page": word["page"],
                "x0": word["x0"],
                "y0": word["y0"],
                "x1": word["x1"],
                "y1": word["y1"],
            }
        )
    return boxes
