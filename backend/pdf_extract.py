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
import unicodedata
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

# Unicode "presentation form" ligatures Tesseract sometimes emits, expanded so
# words like "ﬁnale" read/speak correctly as "finale".
_LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
}
# Lone single-character tokens that are almost always OCR speckle (a stray glyph
# floating between spaces). We drop only these explicit characters rather than
# every one-char symbol, so meaningful tokens like "%", "&", "°", "-" survive.
_NOISE_SINGLE_CHARS = set("|~^`_\\¦•·◦¬")


@dataclass
class ExtractionResult:
    text: str
    page_count: int
    ocr_pages: list[int] = field(default_factory=list)
    ocr_error: bool = False

    @property
    def ocr_used(self) -> bool:
        return bool(self.ocr_pages)


@dataclass
class PageInfo:
    """Per-page extraction state used by the lazy (on-demand OCR) flow."""

    page: int  # 1-indexed
    status: str  # "ready" | "needs_ocr" | "empty"
    text: str = ""  # cleaned text-layer text (empty until/unless OCR'd)


@dataclass
class QuickResult:
    """Result of a fast, OCR-free extraction pass."""

    page_count: int
    pages: list[PageInfo]
    ocr_available: bool
    ocr_error: bool = False  # a page needs OCR but OCR isn't available

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text)


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


def ocr_clean(raw: str) -> str:
    """Sanitise raw OCR output before it is read aloud or exported.

    OCR (Tesseract on imperfect scans) can emit control characters, broken
    ligatures, and isolated punctuation/symbol speckle that is unreadable and
    sounds wrong when spoken. This pass removes that noise while *structurally*
    preserving every real letter — accented Italian characters (à è é ì ò ù)
    included, because the strip rules key off Unicode categories, never an
    ASCII allow-list.

    OCR-only: it is deliberately NOT applied to clean digital text layers, where
    aggressive stripping could remove legitimately unusual-but-valid glyphs.
    """
    if not raw:
        return raw
    # Compose decomposed accents (letter + combining mark) into single chars.
    text = unicodedata.normalize("NFC", raw)
    # Expand ligatures so they read and speak correctly.
    for ligature, replacement in _LIGATURES.items():
        text = text.replace(ligature, replacement)
    # Drop control/format/private-use characters (Unicode category "C*"),
    # keeping only the newlines and tabs that carry layout meaning.
    text = "".join(
        ch
        for ch in text
        if ch in "\n\t" or not unicodedata.category(ch).startswith("C")
    )
    # Collapse runs of 3+ identical non-word, non-space chars (e.g. "----").
    text = re.sub(r"([^\w\s])\1{2,}", r"\1", text)
    # Drop lone symbol/punctuation "words" (OCR speckle) line by line, keeping
    # blank lines so clean_text() can still see paragraph breaks.
    out_lines: list[str] = []
    for line in text.split("\n"):
        kept = [tok for tok in line.split(" ") if _keep_token(tok)]
        out_lines.append(" ".join(kept))
    return "\n".join(out_lines)


def _keep_token(token: str) -> bool:
    """False only for a lone, known-noise speckle character (OCR artifact)."""
    return len(token) != 1 or token not in _NOISE_SINGLE_CHARS


def extract_pdf(pdf_bytes: bytes, *, ocr_fallback: bool = True) -> ExtractionResult:
    """Extract cleaned Italian text from a PDF given as raw bytes."""
    pages: list[str] = []
    ocr_pages: list[int] = []
    ocr_error = False

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            if len(page_text.strip()) < _MIN_CHARS_FOR_TEXT_LAYER and ocr_fallback:
                try:
                    ocr_text = ocr_clean(_ocr_page(pdf_bytes, index))
                except Exception:  # noqa: BLE001 - OCR is best-effort
                    ocr_text, ocr_error = "", True
                if ocr_text.strip():
                    page_text = ocr_text
                    ocr_pages.append(index)
            pages.append(page_text)

    cleaned = clean_text("\n\n".join(pages))
    return ExtractionResult(
        text=cleaned, page_count=len(pages), ocr_pages=ocr_pages, ocr_error=ocr_error
    )


def extract_quick(pdf_bytes: bytes) -> QuickResult:
    """Fast, OCR-free pass: return text-layer pages and flag the rest.

    This returns immediately even for scanned documents — pages without a usable
    text layer are marked ``needs_ocr`` (or ``empty`` when OCR is unavailable) so
    the caller can OCR them lazily, one at a time, via :func:`ocr_page_text`.
    """
    pages: list[PageInfo] = []
    ocr_error = False
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            if len(page_text.strip()) >= _MIN_CHARS_FOR_TEXT_LAYER:
                pages.append(PageInfo(page=index, status="ready", text=clean_text(page_text)))
            elif _OCR_AVAILABLE:
                pages.append(PageInfo(page=index, status="needs_ocr"))
            else:
                pages.append(PageInfo(page=index, status="empty"))
                ocr_error = True
    return QuickResult(
        page_count=len(pages),
        pages=pages,
        ocr_available=_OCR_AVAILABLE,
        ocr_error=ocr_error,
    )


def ocr_page_text(pdf_bytes: bytes, page_number: int) -> str:
    """OCR a single (1-indexed) page and return cleaned, readable text."""
    return clean_text(ocr_clean(_ocr_page(pdf_bytes, page_number)))


def extract_pages(pdf_bytes: bytes, *, ocr_fallback: bool = True) -> list[str]:
    """Return cleaned text for each page separately (useful for chapters)."""
    out: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            if len(page_text.strip()) < _MIN_CHARS_FOR_TEXT_LAYER and ocr_fallback:
                try:
                    ocr_text = ocr_clean(_ocr_page(pdf_bytes, index))
                except Exception:  # noqa: BLE001 - OCR is best-effort
                    ocr_text = ""
                if ocr_text.strip():
                    page_text = ocr_text
            out.append(clean_text(page_text))
    return out
