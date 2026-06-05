"""Unit tests for text cleanup — pure logic, no heavy dependencies."""
from backend.pdf_extract import clean_text, ocr_clean


def test_dehyphenates_words_split_across_lines():
    assert clean_text("lettura auto-\nmatica") == "lettura automatica"


def test_joins_soft_wrapped_lines_with_spaces():
    assert clean_text("riga uno\nriga due") == "riga uno riga due"


def test_preserves_paragraph_breaks():
    assert clean_text("paragrafo uno\n\nparagrafo due") == "paragrafo uno\n\nparagrafo due"


def test_collapses_repeated_whitespace():
    assert clean_text("a    b\t\tc") == "a b c"


def test_keeps_accented_characters():
    assert clean_text("perché città è università") == "perché città è università"


# --- ocr_clean: sanitise raw OCR output without harming real (accented) text ---

def test_ocr_clean_keeps_accents():
    text = "perché città è università À È É Ì Ò Ù"
    assert ocr_clean(text) == text


def test_ocr_clean_strips_control_chars_and_ligatures():
    # form-feed (\x0c) and NUL (\x00) are control chars; "ﬁ" is a ligature.
    assert ocr_clean("ﬁnale\x0c testo\x00") == "finale testo"


def test_ocr_clean_drops_isolated_symbol_noise_but_keeps_words_and_numbers():
    assert ocr_clean("testo | ~ 42 parola") == "testo 42 parola"


def test_ocr_clean_keeps_meaningful_lone_symbols():
    # "%", "&", "°" carry meaning in real text; only speckle should be dropped.
    assert ocr_clean("sconto del 50 % e A & B a 20 °") == "sconto del 50 % e A & B a 20 °"


def test_ocr_clean_preserves_paragraph_breaks_for_segmentation():
    assert ocr_clean("riga uno\n\nriga due") == "riga uno\n\nriga due"


def test_ocr_clean_collapses_noise_runs():
    assert ocr_clean("buongiorno!!!!") == "buongiorno!"
