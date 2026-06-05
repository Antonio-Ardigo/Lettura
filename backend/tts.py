"""Offline Italian text-to-speech using Kokoro via ONNX Runtime.

Kokoro is an 82M-parameter open-weights model (Apache-2.0). Running it through
ONNX Runtime means **no torch dependency and no Hugging Face access**: the
weights are mirrored on GitHub and downloaded once into a local cache, after
which everything runs fully offline.

Italian uses lang code "it" with the if_sara / im_nicola voices. Phonemisation
relies on espeak-ng (bundled via espeakng-loader, or the system package).

Configuration (all optional):
  LETTURA_MODEL_DIR     directory for the cached weights (default: ./models)
  LETTURA_KOKORO_MODEL  explicit path to the .onnx model (skips download)
  LETTURA_KOKORO_VOICES explicit path to the voices .bin (skips download)
"""
from __future__ import annotations

import io
import os
import shutil
import urllib.request
from functools import lru_cache
from pathlib import Path

import numpy as np

# Kokoro Italian voices (see https://huggingface.co/hexgrad/Kokoro-82M).
ITALIAN_VOICES = ["if_sara", "im_nicola"]
DEFAULT_VOICE = "if_sara"
SAMPLE_RATE = 24_000
_LANG = "it"

# Kokoro ONNX weights, mirrored on GitHub (no Hugging Face needed). The int8
# model keeps the download (~90 MB) and CPU inference light.
_RELEASE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
)
_MODEL_FILE = "kokoro-v1.0.int8.onnx"
_VOICES_FILE = "voices-v1.0.bin"


def _model_dir() -> Path:
    default = Path(__file__).resolve().parent.parent / "models"
    return Path(os.environ.get("LETTURA_MODEL_DIR", default))


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as response, open(tmp, "wb") as out:  # noqa: S310
        shutil.copyfileobj(response, out)
    tmp.replace(dest)


def _ensure_weights() -> tuple[Path, Path]:
    directory = _model_dir()
    model = Path(os.environ.get("LETTURA_KOKORO_MODEL", directory / _MODEL_FILE))
    voices = Path(os.environ.get("LETTURA_KOKORO_VOICES", directory / _VOICES_FILE))
    if not model.exists():
        _download(f"{_RELEASE}/{_MODEL_FILE}", model)
    if not voices.exists():
        _download(f"{_RELEASE}/{_VOICES_FILE}", voices)
    return model, voices


@lru_cache(maxsize=1)
def _kokoro():
    """Build and cache the Kokoro ONNX session (downloads weights if missing)."""
    try:
        from kokoro_onnx import Kokoro
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "kokoro-onnx is not installed. Install it with "
            "`pip install kokoro-onnx onnxruntime` and ensure `espeak-ng` is present."
        ) from exc
    model, voices = _ensure_weights()
    return Kokoro(str(model), str(voices))


def synthesize_array(
    text: str, *, voice: str = DEFAULT_VOICE, speed: float = 1.0
) -> tuple[np.ndarray, int]:
    """Render Italian `text` to a float32 waveform and its sample rate."""
    if voice not in ITALIAN_VOICES:
        raise ValueError(f"Unknown voice {voice!r}; choose one of {ITALIAN_VOICES}.")
    if not text.strip():
        raise ValueError("Cannot synthesize empty text.")
    samples, sample_rate = _kokoro().create(text, voice=voice, speed=speed, lang=_LANG)
    return np.asarray(samples, dtype=np.float32), int(sample_rate)


def synthesize(text: str, *, voice: str = DEFAULT_VOICE, speed: float = 1.0) -> bytes:
    """Render Italian `text` to WAV audio bytes (24 kHz mono)."""
    samples, sample_rate = synthesize_array(text, voice=voice, speed=speed)
    return to_wav_bytes(samples, sample_rate)


def to_wav_bytes(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, samples, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()
