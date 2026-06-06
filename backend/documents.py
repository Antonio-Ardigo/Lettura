"""Text extraction for the supported document types: PDF, EPUB and HTML.

PDF is delegated to :mod:`backend.pdf_extract` (pdfplumber + lazy OCR). EPUB and
HTML are pure text and need no OCR, so they are parsed with the Python standard
library only (zipfile + html.parser) — no extra dependencies, all permissive.

Every path returns a :class:`~backend.pdf_extract.QuickResult`, so the API and
frontend treat all formats uniformly: EPUB chapters and HTML become ``ready``
pages, never ``needs_ocr``.
"""
from __future__ import annotations

import io
import posixpath
import zipfile
from html.parser import HTMLParser
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from .pdf_extract import PageInfo, QuickResult, clean_text, extract_quick

# Recognised types, by extension and by MIME (browsers vary; we accept both).
PDF_EXTS = (".pdf",)
EPUB_EXTS = (".epub",)
HTML_EXTS = (".html", ".htm", ".xhtml")
SUPPORTED_EXTS = PDF_EXTS + EPUB_EXTS + HTML_EXTS

_PDF_MIMES = {"application/pdf", "application/x-pdf"}
_EPUB_MIMES = {"application/epub+zip", "application/epub", "application/zip"}
_HTML_MIMES = {"text/html", "application/xhtml+xml", "application/xml", "text/xml"}

# Tags whose text content is not spoken (scripts, styles, document head, etc.).
_SKIP_TAGS = {"script", "style", "head", "title", "nav", "footer", "aside"}
# Block-level tags that imply a line/paragraph break around their content.
_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "section", "article", "blockquote",
    "figcaption", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "ul", "ol",
    "table", "header", "main",
}


class _TextExtractor(HTMLParser):
    """Collect readable text from HTML, with block tags as paragraph breaks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str) -> str:
    """Strip HTML to readable plain text (block tags become paragraph breaks)."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - tolerate malformed markup
        pass
    return parser.get_text()


def _decode(data: bytes) -> str:
    """Decode bytes as text, trying UTF-8 first then a permissive fallback."""
    for encoding in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def extract_html(data: bytes) -> QuickResult:
    """Extract an HTML document into a single ready page."""
    text = clean_text(html_to_text(_decode(data)))
    page = PageInfo(page=1, status="ready" if text else "empty", text=text)
    return QuickResult(page_count=1, pages=[page], ocr_available=False)


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _opf_path(z: zipfile.ZipFile) -> str:
    """Find the OPF package document via META-INF/container.xml."""
    root = ET.fromstring(z.read("META-INF/container.xml"))
    for el in root.iter():
        if _localname(el.tag) == "rootfile" and el.get("full-path"):
            return el.get("full-path")
    raise ValueError("EPUB container has no rootfile.")


def extract_epub(data: bytes) -> QuickResult:
    """Extract EPUB spine documents in reading order, one page per chapter."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        opf_path = _opf_path(z)
        opf_dir = posixpath.dirname(opf_path)
        opf = ET.fromstring(z.read(opf_path))

        manifest: dict[str, str] = {}  # id -> href
        spine: list[str] = []  # ordered idrefs
        for el in opf.iter():
            name = _localname(el.tag)
            if name == "item" and el.get("id") and el.get("href"):
                manifest[el.get("id")] = el.get("href")
            elif name == "itemref" and el.get("idref"):
                spine.append(el.get("idref"))

        names = set(z.namelist())
        pages: list[PageInfo] = []
        for idref in spine:
            href = manifest.get(idref)
            if not href:
                continue
            href = unquote(href.split("#", 1)[0])
            path = posixpath.normpath(posixpath.join(opf_dir, href)) if opf_dir else href
            if path not in names:
                continue
            try:
                text = clean_text(html_to_text(_decode(z.read(path))))
            except Exception:  # noqa: BLE001 - skip an unreadable chapter
                continue
            if text:
                pages.append(PageInfo(page=len(pages) + 1, status="ready", text=text))

    if not pages:
        pages = [PageInfo(page=1, status="empty", text="")]
    return QuickResult(page_count=len(pages), pages=pages, ocr_available=False)


def _kind(filename: str, content_type: str) -> str:
    """Classify an upload as 'pdf' | 'epub' | 'html' from its name/MIME."""
    name = (filename or "").lower()
    ctype = (content_type or "").lower().split(";", 1)[0].strip()
    if name.endswith(PDF_EXTS) or ctype in _PDF_MIMES:
        return "pdf"
    if name.endswith(EPUB_EXTS) or ctype in _EPUB_MIMES:
        return "epub"
    if name.endswith(HTML_EXTS) or ctype in _HTML_MIMES:
        return "html"
    return "unknown"


def is_supported(filename: str, content_type: str) -> bool:
    return _kind(filename, content_type) != "unknown"


def extract_document(data: bytes, filename: str, content_type: str) -> QuickResult:
    """Dispatch extraction by document type. Raises ValueError if unsupported."""
    kind = _kind(filename, content_type)
    if kind == "pdf":
        return extract_quick(data)
    if kind == "epub":
        return extract_epub(data)
    if kind == "html":
        return extract_html(data)
    raise ValueError("Unsupported file type; upload a PDF, EPUB or HTML file.")
