"""Offline Italian text-to-speech using Kokoro (Apache-2.0).

Kokoro is an 82M-parameter open-weights model that runs locally on CPU or GPU
with no API keys and a permissive license, which fits an offline,
commercial-safe app. Italian uses lang_code "i" and ships female/male voices.

The model is loaded lazily on first use (the first call downloads the weights).
Importing this module never fails even if Kokoro isn't installed yet, so the
rest of the app (PDF extraction) keeps working; calling `synthesize` without
Kokoro raises a clear, actionable error.

Phonemisation for Italian relies on the system package `espeak-ng`.
"""
from __future__ import annotations

import io
from functools import lru_cache

import numpy as np

# Kokoro Italian voices (see https://huggingface.co/hexgrad/Kokoro-82M).
ITALIAN_VOICES = ["if_sara", "im_nicola"]
DEFAULT_VOICE = "if_sara"
SAMPLE_RATE = 24_000
_LANG_CODE = "i"  # Italian


@lru_cache(maxsize=1)
def _pipeline():
    """Build and cache the Kokoro pipeline (downloads weights on first call)."""
    try:
        from kokoro import KPipeline
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Kokoro is not installed. Install it with `pip install kokoro "
            "soundfile` and ensure the system package `espeak-ng` is present."
        ) from exc
    return KPipeline(lang_code=_LANG_CODE)


def synthesize(text: str, *, voice: str = DEFAULT_VOICE, speed: float = 1.0) -> bytes:
    """Render Italian `text` to WAV audio bytes.

    Long text is chunked internally by Kokoro; the resulting audio segments are
    concatenated into a single waveform and encoded as a 24 kHz mono WAV.
    """
    if voice not in ITALIAN_VOICES:
        raise ValueError(f"Unknown voice {voice!r}; choose one of {ITALIAN_VOICES}.")
    if not text.strip():
        raise ValueError("Cannot synthesize empty text.")

    pipeline = _pipeline()
    segments = [audio for _gs, _ps, audio in pipeline(text, voice=voice, speed=speed)]
    if not segments:
        raise RuntimeError("TTS produced no audio.")

    waveform = np.concatenate(segments).astype(np.float32)
    return _to_wav_bytes(waveform)


def _to_wav_bytes(waveform: np.ndarray) -> bytes:
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, waveform, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return buffer.getvalue()
