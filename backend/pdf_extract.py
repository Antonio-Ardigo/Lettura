"""PDF text extraction for Italian documents.

Strategy (all permissively licensed, offline):
  1. Try a text layer with pdfplumber (MIT). Fast and accurate for digital PDFs.
  2. If a page has little/no extractable text, fall back to OCR with Tesseract
     and the Italian language pack ("ita"), via pytesseract + pdf2image.
  3. Clean the raw text (de-hyphenation, line-break joining) so it reads well
     when spoken aloud.

OCR is optional: if pytesseract / pdf2image (and the system `tesseract-ocr-ita`
and poppler) are not installed, scanned pages simply yield empty text instead
of raising.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pdfplumber

# OCR is an optional dependency. Import defensively so the app still runs (for
# digital PDFs) when Tesseract isn't installed.
try:  # pragma: no cover - exercised only when OCR deps are present
    import pytesseract
    from pdf2image import convert_from_bytes

    _OCR_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import problem disables OCR
    _OCR_AVAILABLE = False

# Below this many characters we assume a page is scanned (image-only).
_MIN_CHARS_FOR_TEXT_LAYER = 20
# Sentinel used to preserve real paragraph breaks during cleanup.
_PARAGRAPH = "\x00"


@dataclass
class ExtractionResult:
    text: str
    page_count: int
    ocr_pages: list[int] = field(default_factory=list)

    @property
    def ocr_used(self) -> bool:
        return bool(self.ocr_pages)


def _ocr_page(pdf_bytes: bytes, page_number: int) -> str:
    """OCR a single (1-indexed) page in Italian. Returns "" if OCR unavailable."""
    if not _OCR_AVAILABLE:
        return ""
    images = convert_from_bytes(
        pdf_bytes, first_page=page_number, last_page=page_number, dpi=300
    )
    if not images:
        return ""
    return pytesseract.image_to_string(images[0], lang="ita")


def clean_text(raw: str) -> str:
    """Tidy extracted text so it flows when read aloud.

    - join words split across line breaks ("paro-\\nla" -> "parola")
    - keep blank lines as paragraph separators
    - collapse single newlines inside a paragraph into spaces
    - normalise repeated whitespace
    """
    # De-hyphenate words broken across lines.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", raw)
    # Mark real paragraph breaks (a blank line = two or more newlines).
    text = re.sub(r"\n[ \t]*\n+", _PARAGRAPH, text)
    # Remaining single newlines are soft wraps -> spaces.
    text = text.replace("\n", " ")
    # Collapse runs of spaces/tabs.
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Restore paragraph breaks.
    text = text.replace(_PARAGRAPH, "\n\n")
    return text.strip()


def extract_pdf(pdf_bytes: bytes, *, ocr_fallback: bool = True) -> ExtractionResult:
    """Extract cleaned Italian text from a PDF given as raw bytes."""
    pages: list[str] = []
    ocr_pages: list[int] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            if len(page_text.strip()) < _MIN_CHARS_FOR_TEXT_LAYER and ocr_fallback:
                ocr_text = _ocr_page(pdf_bytes, index)
                if ocr_text.strip():
                    page_text = ocr_text
                    ocr_pages.append(index)
            pages.append(page_text)

    cleaned = clean_text("\n\n".join(pages))
    return ExtractionResult(text=cleaned, page_count=len(pages), ocr_pages=ocr_pages)


def extract_pages(pdf_bytes: bytes, *, ocr_fallback: bool = True) -> list[str]:
    """Return cleaned text for each page separately (useful for chapters)."""
    out: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            if len(page_text.strip()) < _MIN_CHARS_FOR_TEXT_LAYER and ocr_fallback:
                ocr_text = _ocr_page(pdf_bytes, index)
                if ocr_text.strip():
                    page_text = ocr_text
            out.append(clean_text(page_text))
    return out
