"""Lettura web app — FastAPI backend.

Endpoints
  GET  /            -> the single-page frontend
  GET  /api/health  -> liveness + which optional features are available
  GET  /api/voices  -> the Italian voices Kokoro can use
  POST /api/extract -> multipart PDF upload, returns cleaned Italian text
  POST /api/speak   -> JSON {text, voice, speed}, returns a WAV audio stream

Everything runs locally: pdfplumber for extraction, Kokoro for TTS. No data
leaves the machine and there are no API keys.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, export, pdf_extract, segment, tts

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
MAX_PDF_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_TTS_CHARS = 20_000  # guardrail per /api/speak request
MAX_EXPORT_CHARS = 500_000  # ~ several hours of audio per /api/export request
_EXPORT_MEDIA = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4b": "audio/mp4"}

app = FastAPI(title="Lettura", version=__version__)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1)
    voice: str = tts.DEFAULT_VOICE
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class ExportRequest(BaseModel):
    text: str = Field(min_length=1)
    voice: str = tts.DEFAULT_VOICE
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    format: str = "wav"


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "ocr_available": pdf_extract._OCR_AVAILABLE,
        "voices": tts.ITALIAN_VOICES,
    }


@app.get("/api/voices")
def voices() -> dict:
    return {"voices": tts.ITALIAN_VOICES, "default": tts.DEFAULT_VOICE}


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)) -> dict:
    if (file.content_type or "").lower() not in {"application/pdf", "application/x-pdf"}:
        raise HTTPException(status_code=415, detail="Please upload a PDF file.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded PDF is empty.")
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF exceeds the 50 MB limit.")
    try:
        result = pdf_extract.extract_pdf(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Could not read PDF: {exc}") from exc
    return {
        "text": result.text,
        "sentences": segment.segment_sentences(result.text),
        "page_count": result.page_count,
        "ocr_used": result.ocr_used,
        "ocr_pages": result.ocr_pages,
        "char_count": len(result.text),
    }


@app.post("/api/speak")
def speak(req: SpeakRequest) -> Response:
    if len(req.text) > MAX_TTS_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Text exceeds {MAX_TTS_CHARS} characters; split it into chunks.",
        )
    try:
        audio = tts.synthesize(req.text, voice=req.voice, speed=req.speed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:  # Kokoro missing / synthesis failure
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=audio, media_type="audio/wav")


@app.post("/api/export")
def export_audio(req: ExportRequest) -> Response:
    """Synthesize a whole document into one downloadable audio file.

    This is a batch job: long documents take a while (minutes for ~1 hour of
    audio on CPU). WAV needs no extra tools; MP3/M4B require ffmpeg.
    """
    fmt = req.format.lower()
    if fmt not in _EXPORT_MEDIA:
        raise HTTPException(status_code=400, detail="format must be wav, mp3, or m4b.")
    if len(req.text) > MAX_EXPORT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Text exceeds {MAX_EXPORT_CHARS} characters.",
        )
    try:
        audio, sample_rate = export.synthesize_long(
            req.text, voice=req.voice, speed=req.speed
        )
        data = export.encode(audio, sample_rate, fmt=fmt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:  # Kokoro / ffmpeg missing
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type=_EXPORT_MEDIA[fmt],
        headers={"Content-Disposition": f'attachment; filename="lettura.{fmt}"'},
    )


# --- Static frontend (mounted last so it doesn't shadow /api routes) ---
@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
