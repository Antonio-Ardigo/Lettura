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

import ftfy
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

# --- Speech normalisation -------------------------------------------------
# Many Italian PDFs encode a final accent as "vowel + apostrophe" (e.g.
# "perche'", "citta'", "puo'") because the font lacks the accented glyph. Spoken
# aloud the apostrophe trips up the TTS, so we fold these back to real accents —
# WITHOUT touching elision apostrophes (l'amico, dell'arte, un'altra), which are
# letter+apostrophe+letter, never vowel+apostrophe+boundary.
_APOSTROPHES = "'’ʼ´`"
# Truncations ("troncamenti") that legitimately keep the apostrophe and must NOT
# become accented vowels: po' (poco), va'/da'/fa'/sta'/di' (imperatives), be'…
_TRONCAMENTI = {"po", "mo", "be", "va", "da", "fa", "sta", "di", "to"}
# Final "-e" truncations that take an acute (closed) é rather than a grave è.
_ACUTE_E_WORDS = {"ne", "se", "merce", "vicere", "teste", "scimpanze"}
_GRAVE_VOWEL = {"a": "à", "e": "è", "i": "ì", "o": "ò", "u": "ù"}
_VOWELS_ACCENTED = "aeiouàèéìòù"

# A word's final vowel, an apostrophe, then a boundary (space / punctuation / end
# of string) — i.e. an accent, not an elision.
_ACCENT_RE = re.compile(
    r"([^\W\d_]*)([aeiouAEIOU])[" + _APOSTROPHES + r"]"
    r"(?=[\s.,;:!?\"»”)\]…]|$)"
)
# A standalone run of 4+ single letters spaced apart ("p a r o l a"), which only
# real words/titles produce — never natural single-letter words (all vowels).
_DESPACE_RE = re.compile(r"(?<!\S)([^\W\d_](?: [^\W\d_]){3,})(?!\S)")

# Invisible characters that corrupt words when extracted: soft hyphen + the
# zero-width family + BOM. Removed outright (they carry no spoken meaning).
_INVISIBLE_RE = re.compile("[\u00ad\u200b\u200c\u200d\u2060\ufeff]")

# Italian months for spelling out numeric dates (the day/year are left as digits
# — espeak-ng reads Italian numbers correctly, it only mishandles the "/"s).
_MONTHS = {
    1: "gennaio", 2: "febbraio", 3: "marzo", 4: "aprile", 5: "maggio",
    6: "giugno", 7: "luglio", 8: "agosto", 9: "settembre", 10: "ottobre",
    11: "novembre", 12: "dicembre",
}
# A full numeric date with a 4-digit year (unambiguously a date, not a fraction).
_DATE_RE = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b")

# --- Curated accent lexicon -------------------------------------------------
# Bare (unaccented) forms -> correctly accented form, for words extracted without
# their accent. DELIBERATELY narrow: only words whose accented form is the only
# real word in running Italian prose. We exclude every verb form (parlo != parlò)
# and every ambiguous monosyllable pair (e/è, si/sì, da/dà, ne/né, la/là, se/sé,
# di/dì, li/lì, te/tè) — those need grammar/context and are too risky to fold.
_ACCENT_LEXICON = {
    # conjunctions/adverbs in -ché (acute)
    "perche": "perché", "poiche": "poiché", "benche": "benché",
    "affinche": "affinché", "finche": "finché", "giacche": "giacché",
    "nonche": "nonché", "cosicche": "cosicché", "sicche": "sicché",
    "purche": "purché", "anziche": "anziché", "fuorche": "fuorché",
    "dacche": "dacché", "macche": "macché", "allorche": "allorché",
    "dopodiche": "dopodiché",
    # common adverbs
    "piu": "più", "gia": "già", "cosi": "così", "percio": "perciò", "cio": "ciò",
    # nouns ending in -tà / -tù (the bare forms are not Italian words)
    "citta": "città", "universita": "università", "qualita": "qualità",
    "liberta": "libertà", "verita": "verità", "realta": "realtà",
    "societa": "società", "attivita": "attività", "possibilita": "possibilità",
    "facolta": "facoltà", "velocita": "velocità", "difficolta": "difficoltà",
    "identita": "identità", "autorita": "autorità", "comunita": "comunità",
    "umanita": "umanità", "civilta": "civiltà", "novita": "novità",
    "quantita": "quantità", "proprieta": "proprietà", "maesta": "maestà",
    "virtu": "virtù", "gioventu": "gioventù", "servitu": "servitù",
    "schiavitu": "schiavitù",
    # more high-frequency -tà nouns whose bare form is NOT an Italian word/verb
    # (collisions with verb conjugations — gravita, stabilita, necessita,
    # felicita, abilita, capacita, unita — are deliberately omitted)
    "curiosita": "curiosità", "dignita": "dignità", "poverta": "povertà",
    "priorita": "priorità", "responsabilita": "responsabilità",
    "serieta": "serietà", "varieta": "varietà", "volonta": "volontà",
    "opportunita": "opportunità", "personalita": "personalità",
    "profondita": "profondità", "localita": "località", "modalita": "modalità",
    "attualita": "attualità", "diversita": "diversità", "entita": "entità",
    "fedelta": "fedeltà", "finalita": "finalità", "utilita": "utilità",
    "vanita": "vanità", "visibilita": "visibilità", "generosita": "generosità",
    "pubblicita": "pubblicità", "sincerita": "sincerità", "eternita": "eternità",
    "intensita": "intensità", "maturita": "maturità", "oscurita": "oscurità",
    "tranquillita": "tranquillità",
    # adverbs of place/manner and a couple of common -è/-ù words
    "giu": "giù", "lassu": "lassù", "laggiu": "laggiù", "quaggiu": "quaggiù",
    "quassu": "quassù", "caffe": "caffè",
    # unambiguous "puo" (not a word) -> può
    "puo": "può",
    # borderline: "pero" is also "pear tree", but in adult prose "però" dominates
    # — included on explicit request; remove this line for a botany-safe corpus.
    "pero": "però",
}
_LEXICON_RE = re.compile(
    r"\b(" + "|".join(sorted(_ACCENT_LEXICON, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
# 3+ dots (optionally space-separated) -> a single "…" glued to the previous word
# (Kokoro's dedicated suspension token); a trailing space/punctuation is kept.
_ELLIPSIS_DOTS_RE = re.compile(r"(?:[ \t]*\.){3,}")
_ELLIPSIS_TIDY_RE = re.compile(r"…(?:[ \t]*[.…])*")


def _accent_repl(match: re.Match) -> str:
    """Turn a vowel+apostrophe truncation into the correct accented vowel."""
    stem, vowel = match.group(1), match.group(2)
    word = (stem + vowel).lower()
    if word in _TRONCAMENTI:
        return match.group(0)  # genuine truncation; keep the apostrophe
    if vowel in "eE":
        acute = word.endswith("che") or word.endswith("tre") or word in _ACUTE_E_WORDS
        accented = "é" if acute else "è"
    else:
        accented = _GRAVE_VOWEL[vowel.lower()]
    if vowel.isupper():
        accented = accented.upper()
    return stem + accented


def _lexicon_repl(match: re.Match) -> str:
    """Map a bare word to its accented form, preserving the original case."""
    word = match.group(0)
    accented = _ACCENT_LEXICON[word.lower()]
    if word.isupper():
        return accented.upper()
    if word[0].isupper():
        return accented[0].upper() + accented[1:]
    return accented


def _despace_repl(match: re.Match) -> str:
    """Join a letter-spaced run, but only if it contains a consonant.

    Vowel-only runs (e.g. "a e i o") are left alone so legitimate single-letter
    words are never merged; letter-spaced words/titles always carry a consonant.
    """
    joined = match.group(0).replace(" ", "")
    if any(ch.lower() not in _VOWELS_ACCENTED for ch in joined):
        return joined
    return match.group(0)


def _date_repl(match: re.Match) -> str:
    """Spell a numeric date's month (12/03/2026 -> "12 marzo 2026").

    Italian convention is day/month/year; the day and year stay as digits because
    espeak-ng reads Italian numbers correctly — it only mis-speaks the "/" as
    "barra". The 1st of the month becomes "primo", as Italian requires.
    """
    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return match.group(0)  # not a real date (e.g. a fraction) — leave it
    day_word = "primo" if day == 1 else str(day)
    return f"{day_word} {_MONTHS[month]} {year}"


def fix_extraction_artifacts(text: str) -> str:
    """Repair encoding-level damage from PDF/EPUB extraction before cleanup.

    ftfy fixes mojibake ("perchÃ©"), broken ligatures, mis-decoded quotes and
    stray control characters, and composes to NFC; then we drop invisible
    characters (soft hyphen, zero-width marks, BOM) that split words silently.
    """
    if not text:
        return text
    text = ftfy.fix_text(text)
    return _INVISIBLE_RE.sub("", text)


def normalize_for_speech(text: str) -> str:
    """Make extracted text read correctly aloud.

    - fold vowel+apostrophe accents (perche' -> perché), keeping elisions (l'amico)
    - rejoin letter-spaced words ("p a r o l a" -> "parola")
    - restore accents on a curated set of unambiguous words (citta -> città)
    - spell numeric dates' months (12/03/2026 -> "12 marzo 2026")
    - normalise ellipses ("...", ". . .") to a single "…" suspension pause

    ``!``/``?`` and parentheses are left untouched: Kokoro already reads them as
    distinct prosody tokens. Idempotent and accent-safe (it keys off Unicode
    letter categories, never an ASCII allow-list).
    """
    if not text:
        return text
    text = unicodedata.normalize("NFC", text)
    text = _ACCENT_RE.sub(_accent_repl, text)
    text = _DESPACE_RE.sub(_despace_repl, text)
    text = _LEXICON_RE.sub(_lexicon_repl, text)
    text = _DATE_RE.sub(_date_repl, text)
    text = _ELLIPSIS_DOTS_RE.sub("…", text)
    text = _ELLIPSIS_TIDY_RE.sub("…", text)
    return text


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

    - repair encoding artifacts (mojibake, ligatures, invisibles) up front
    - join words split across line breaks ("paro-\\nla" -> "parola")
    - keep blank lines as paragraph separators
    - collapse single newlines inside a paragraph into spaces
    - normalise repeated whitespace
    - fold vowel+apostrophe accents and rejoin letter-spaced words for speech
    """
    # Repair encoding-level damage first, so later steps see correct codepoints.
    text = fix_extraction_artifacts(raw)
    # De-hyphenate words broken across lines.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # Mark real paragraph breaks (a blank line = two or more newlines).
    text = re.sub(r"\n[ \t]*\n+", _PARAGRAPH, text)
    # Remaining single newlines are soft wraps -> spaces.
    text = text.replace("\n", " ")
    # Collapse runs of spaces/tabs.
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Restore paragraph breaks.
    text = text.replace(_PARAGRAPH, "\n\n")
    # Fold vowel+apostrophe accents and rejoin letter-spaced words so the text
    # reads correctly when spoken aloud.
    text = normalize_for_speech(text)
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
