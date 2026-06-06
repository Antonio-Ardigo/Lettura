"""Unit tests for text cleanup — pure logic, no heavy dependencies."""
import pytest

from backend.pdf_extract import clean_text, normalize_for_speech, ocr_clean


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


# --- normalize_for_speech: vowel+apostrophe accents (grave/acute) ---

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("e'", "è"),            # bare copula
        ("perche'", "perché"),  # -ché -> acute
        ("poiche'", "poiché"),
        ("benche'", "benché"),
        ("cioe'", "cioè"),      # -è grave
        ("caffe'", "caffè"),
        ("citta'", "città"),
        ("piu'", "più"),
        ("puo'", "può"),
        ("cosi'", "così"),
        ("li'", "lì"),
        ("Giro'", "Girò"),      # capitalised stem keeps its case
        ("ventitre'", "ventitré"),  # -tré numerals -> acute
    ],
)
def test_normalize_folds_apostrophe_accents(raw, expected):
    assert normalize_for_speech(raw) == expected


@pytest.mark.parametrize(
    "elision",
    ["l'amico", "dell'arte", "un'altra", "quell'uomo", "c'è", "anch'io", "dov'è"],
)
def test_normalize_preserves_elision_apostrophes(elision):
    assert normalize_for_speech(elision) == elision


@pytest.mark.parametrize("troncamento", ["po'", "un po' di pane", "va'", "da'", "fa'"])
def test_normalize_preserves_truncation_apostrophes(troncamento):
    assert normalize_for_speech(troncamento) == troncamento


def test_normalize_accent_before_punctuation():
    assert normalize_for_speech("perche'.") == "perché."
    assert normalize_for_speech("e', dunque") == "è, dunque"


def test_normalize_curly_apostrophe_accent_and_elision():
    assert normalize_for_speech("perche’") == "perché"
    assert normalize_for_speech("l’amico") == "l’amico"


def test_normalize_is_idempotent():
    once = normalize_for_speech("perche' citta' e' p a r o l a")
    assert normalize_for_speech(once) == once


# --- normalize_for_speech: rejoin letter-spaced words ---

def test_normalize_rejoins_letter_spaced_word():
    assert normalize_for_speech("p a r o l a") == "parola"
    assert normalize_for_speech("la p a r o l a giusta") == "la parola giusta"


def test_normalize_rejoins_spaced_caps_title():
    assert normalize_for_speech("C A P I T O L O") == "CAPITOLO"


def test_normalize_keeps_vowel_only_runs():
    # All-vowel runs are real single-letter words, never letter-spacing.
    assert normalize_for_speech("a e i o") == "a e i o"


def test_normalize_short_runs_are_left_alone():
    # Below the 4-token threshold we never merge (protects "a b c").
    assert normalize_for_speech("a b c") == "a b c"


# --- normalize_for_speech: curated missing-accent lexicon ---

@pytest.mark.parametrize(
    "bare, accented",
    [
        ("perche", "perché"),
        ("piu", "più"),
        ("gia", "già"),
        ("cosi", "così"),
        ("citta", "città"),
        ("universita", "università"),
        ("virtu", "virtù"),
        ("puo", "può"),
        ("pero", "però"),  # borderline entry, included on request
        ("Perche", "Perché"),  # capitalised
        ("PERCHE", "PERCHÉ"),  # upper-case
    ],
)
def test_normalize_restores_missing_accents(bare, accented):
    assert normalize_for_speech(bare) == accented
    assert normalize_for_speech(f"e {bare} via") == f"e {accented} via"


@pytest.mark.parametrize(
    "word",
    # Ambiguous monosyllables and verb forms must NEVER be touched.
    ["e", "si", "da", "ne", "la", "se", "di", "li", "te",
     "parlo", "meta", "unita", "pianeta", "perché", "città"],
)
def test_normalize_leaves_ambiguous_and_already_accented_words(word):
    assert normalize_for_speech(f"la {word} qui") == f"la {word} qui"


# --- normalize_for_speech: ellipsis -> single "…" suspension ---

@pytest.mark.parametrize(
    "raw",
    ["Aspetta... arrivo", "Aspetta.... arrivo", "Aspetta . . . arrivo",
     "Aspetta ... arrivo"],
)
def test_normalize_collapses_ellipsis_to_single_char(raw):
    out = normalize_for_speech(raw)
    assert "…" in out and "..." not in out
    assert out.count("…") == 1
    assert out.startswith("Aspetta…")  # glued to the preceding word
    assert out.endswith("arrivo")


def test_normalize_ellipsis_idempotent():
    once = normalize_for_speech("Aspetta... arrivo")
    assert normalize_for_speech(once) == once


def test_normalize_does_not_eat_paragraph_break_after_ellipsis():
    assert normalize_for_speech("fine...\n\nNuovo") == "fine…\n\nNuovo"


# --- punctuation that Kokoro reads as prosody is preserved verbatim ---

@pytest.mark.parametrize(
    "text",
    ["Che bello!", "Davvero?", "il cane (nero) corre", "uno; due: tre"],
)
def test_clean_text_preserves_prosody_punctuation(text):
    assert clean_text(text) == text


# --- clean_text composes the normalisation across paragraphs ---

def test_clean_text_normalises_accents_and_spacing():
    assert clean_text("perche'\n\ncitta'") == "perché\n\ncittà"
    assert clean_text("la p a r o l a") == "la parola"
