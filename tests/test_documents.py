"""Unit tests for EPUB/HTML extraction and the type dispatcher."""
import io
import zipfile

import pytest

from backend import documents


def test_html_to_text_strips_scripts_styles_and_keeps_text():
    html = (
        "<html><head><title>T</title><style>p{color:red}</style>"
        "<script>var x=1;</script></head>"
        "<body><h1>Titolo</h1><p>Primo paragrafo.</p><p>Secondo.</p></body></html>"
    )
    text = documents.html_to_text(html)
    assert "Titolo" in text and "Primo paragrafo." in text and "Secondo." in text
    assert "color:red" not in text and "var x" not in text


def test_extract_html_folds_accents_and_keeps_elision():
    html = b"<html><body><p>perche' e' cosi'. L'amico del po' di pane.</p></body></html>"
    result = documents.extract_document(html, "doc.html", "text/html")
    assert result.page_count == 1
    assert result.pages[0].status == "ready"
    assert "perché" in result.text and "è" in result.text and "così" in result.text
    assert "L'amico" in result.text and "po'" in result.text


def _build_epub(chapters: list[str]) -> bytes:
    container = (
        '<?xml version="1.0"?><container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
        '<rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    items = "".join(
        f'<item id="c{i}" href="ch{i}.xhtml" media-type="application/xhtml+xml"/>'
        for i in range(len(chapters))
    )
    refs = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
    opf = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
        'version="3.0" unique-identifier="id"><metadata '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>T</dc:title>'
        f"</metadata><manifest>{items}</manifest><spine>{refs}</spine></package>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        for i, body in enumerate(chapters):
            z.writestr(
                f"OEBPS/ch{i}.xhtml",
                '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml">'
                f"<body>{body}</body></html>",
            )
    return buf.getvalue()


def test_extract_epub_returns_a_page_per_chapter_in_spine_order():
    epub = _build_epub(["<p>Prima citta'.</p>", "<p>Seconda, piu' lunga.</p>"])
    result = documents.extract_document(epub, "book.epub", "application/epub+zip")
    assert result.page_count == 2
    assert "città" in result.pages[0].text
    assert "più" in result.pages[1].text
    assert result.pages[0].status == "ready"


def test_extract_epub_empty_when_no_readable_chapters():
    epub = _build_epub(["<p></p>"])
    result = documents.extract_document(epub, "book.epub", "application/epub+zip")
    assert result.page_count == 1
    assert result.pages[0].status == "empty"


@pytest.mark.parametrize(
    "name, ctype, expected",
    [
        ("a.pdf", "application/pdf", True),
        ("a.epub", "application/epub+zip", True),
        ("a.html", "text/html", True),
        ("a.htm", "", True),
        ("a.xhtml", "", True),
        ("a.txt", "text/plain", False),
        ("a.docx", "application/octet-stream", False),
        ("noext", "application/epub+zip", True),  # MIME-only
    ],
)
def test_is_supported(name, ctype, expected):
    assert documents.is_supported(name, ctype) is expected


def test_extract_document_rejects_unsupported():
    with pytest.raises(ValueError):
        documents.extract_document(b"hello", "a.txt", "text/plain")
