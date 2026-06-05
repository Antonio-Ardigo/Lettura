"""Render long text (whole PDFs) into a single audio file.

Sentences are batched into chunks, synthesised, and concatenated, so documents
of any length work without a per-request character cap. Output is WAV by
default; MP3 and M4B (with per-section chapter markers) are produced via ffmpeg
when available — either a system ffmpeg or the bundled imageio-ffmpeg.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

import numpy as np

from . import segment, tts

_MAX_CHARS_PER_CHUNK = 1500

Progress = Callable[[int, int], None]


@dataclass
class Chapter:
    start: float  # seconds
    title: str


def chunk_sentences(
    sentences: Iterable[str], max_chars: int = _MAX_CHARS_PER_CHUNK
) -> Iterator[str]:
    """Group sentences into chunks no longer than max_chars (never splitting one)."""
    batch: list[str] = []
    length = 0  # length of " ".join(batch)
    for sentence in sentences:
        addition = (1 if batch else 0) + len(sentence)
        if batch and length + addition > max_chars:
            yield " ".join(batch)
            batch, length, addition = [], 0, len(sentence)
        batch.append(sentence)
        length += addition
    if batch:
        yield " ".join(batch)


def _sentences(text: str) -> list[str]:
    return segment.segment_sentences(text) or ([text] if text.strip() else [])


def _render(chunks, voice, speed, gap, progress) -> tuple[np.ndarray, int, list[float]]:
    """Synthesize chunks, returning the waveform, rate, and per-chunk end times."""
    sample_rate = tts.SAMPLE_RATE
    silence = np.zeros(int(sample_rate * gap), dtype=np.float32)
    parts: list[np.ndarray] = []
    ends: list[float] = []
    total = len(chunks)
    elapsed = 0
    for index, chunk in enumerate(chunks, start=1):
        samples, sample_rate = tts.synthesize_array(chunk, voice=voice, speed=speed)
        parts.append(samples)
        parts.append(silence)
        elapsed += len(samples) + len(silence)
        ends.append(elapsed / sample_rate)
        if progress:
            progress(index, total)
    audio = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
    return audio, sample_rate, ends


def synthesize_long(
    text: str,
    *,
    voice: str = tts.DEFAULT_VOICE,
    speed: float = 1.0,
    gap: float = 0.3,
    progress: Progress | None = None,
) -> tuple[np.ndarray, int]:
    """Synthesize arbitrarily long text into one waveform."""
    chunks = list(chunk_sentences(_sentences(text)))
    audio, sample_rate, _ = _render(chunks, voice, speed, gap, progress)
    return audio, sample_rate


def synthesize_sections(
    sections: list[tuple[str, str]],
    *,
    voice: str = tts.DEFAULT_VOICE,
    speed: float = 1.0,
    gap: float = 0.3,
    progress: Progress | None = None,
) -> tuple[np.ndarray, int, list[Chapter]]:
    """Synthesize (title, text) sections into one waveform plus chapter marks."""
    plan: list[tuple[str | None, str]] = []
    for title, text in sections:
        first = True
        for chunk in chunk_sentences(_sentences(text)):
            plan.append((title if first else None, chunk))
            first = False
    chunks = [chunk for _title, chunk in plan]
    audio, sample_rate, ends = _render(chunks, voice, speed, gap, progress)
    chapters: list[Chapter] = []
    for i, (title, _chunk) in enumerate(plan):
        if title is not None:
            start = ends[i - 1] if i > 0 else 0.0
            chapters.append(Chapter(start=start, title=title))
    return audio, sample_rate, chapters


# --- Encoding ------------------------------------------------------------------

def ffmpeg_exe() -> str | None:
    """Locate ffmpeg: a system install, else the bundled imageio-ffmpeg."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def encode(
    audio: np.ndarray,
    sample_rate: int,
    *,
    fmt: str = "wav",
    chapters: list[Chapter] | None = None,
    bitrate: str = "64k",
) -> bytes:
    """Encode a waveform to wav/mp3/m4b bytes (mp3/m4b require ffmpeg)."""
    fmt = fmt.lower()
    if fmt == "wav":
        return tts.to_wav_bytes(audio, sample_rate)

    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError(
            "ffmpeg is required for MP3/M4B export "
            "(`pip install imageio-ffmpeg`, or install ffmpeg)."
        )

    with tempfile.TemporaryDirectory() as work:
        wav_path = os.path.join(work, "in.wav")
        out_path = os.path.join(work, f"out.{fmt}")
        with open(wav_path, "wb") as handle:
            handle.write(tts.to_wav_bytes(audio, sample_rate))

        cmd = [exe, "-y", "-i", wav_path]
        if fmt == "m4b" and chapters:
            meta_path = os.path.join(work, "chapters.txt")
            _write_ffmetadata(meta_path, chapters, total=len(audio) / sample_rate)
            cmd += ["-i", meta_path, "-map_metadata", "1"]
        if fmt in ("m4b", "m4a"):
            cmd += ["-c:a", "aac", "-b:a", bitrate, "-f", "mp4"]
        elif fmt == "mp3":
            cmd += ["-c:a", "libmp3lame", "-b:a", bitrate]
        else:
            raise ValueError(f"Unsupported format {fmt!r}.")
        cmd.append(out_path)

        subprocess.run(cmd, check=True, capture_output=True)
        with open(out_path, "rb") as handle:
            return handle.read()


def _write_ffmetadata(path: str, chapters: list[Chapter], total: float) -> None:
    lines = [";FFMETADATA1"]
    for i, chapter in enumerate(chapters):
        end = chapters[i + 1].start if i + 1 < len(chapters) else total
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={int(chapter.start * 1000)}",
            f"END={int(end * 1000)}",
            f"title={chapter.title}",
        ]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


# --- CLI -----------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse
    import sys
    from pathlib import Path

    from . import pdf_extract

    parser = argparse.ArgumentParser(
        prog="python -m backend.export",
        description="Turn a PDF (or text file) into a single audio file.",
    )
    parser.add_argument("input", help="input .pdf or .txt ('-' reads text from stdin)")
    parser.add_argument("output", help="output file: .wav, .mp3, or .m4b")
    parser.add_argument("--voice", default=tts.DEFAULT_VOICE, choices=tts.ITALIAN_VOICES)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument(
        "--chapters-per-page",
        action="store_true",
        help="(PDF + .m4b) one chapter marker per page",
    )
    args = parser.parse_args(argv)

    fmt = Path(args.output).suffix.lstrip(".").lower() or "wav"

    def report(done: int, total: int) -> None:
        print(f"  …chunk {done}/{total}", file=sys.stderr)

    chapters: list[Chapter] | None = None
    if args.input == "-":
        audio, rate = synthesize_long(
            sys.stdin.read(), voice=args.voice, speed=args.speed, progress=report
        )
    else:
        raw = Path(args.input).read_bytes()
        is_pdf = args.input.lower().endswith(".pdf")
        if is_pdf and args.chapters_per_page:
            pages = pdf_extract.extract_pages(raw)
            sections = [(f"Pagina {i}", text) for i, text in enumerate(pages, start=1)]
            audio, rate, chapters = synthesize_sections(
                sections, voice=args.voice, speed=args.speed, progress=report
            )
        else:
            text = pdf_extract.extract_pdf(raw).text if is_pdf else raw.decode("utf-8")
            audio, rate = synthesize_long(
                text, voice=args.voice, speed=args.speed, progress=report
            )

    data = encode(audio, rate, fmt=fmt, chapters=chapters)
    Path(args.output).write_bytes(data)
    print(f"wrote {args.output}: {len(audio) / rate:.1f}s, {len(data) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
