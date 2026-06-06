"""Lettura web app — FastAPI backend.

Endpoints
  GET  /                       -> the single-page frontend
  GET  /api/health             -> liveness + which optional features are ready
  GET  /api/voices             -> the Italian voices Kokoro can use
  POST /api/extract            -> multipart PDF upload; fast text-layer extract
                                  (returns a doc_id; scanned pages are OCR'd later)
  POST /api/ocr_page           -> JSON {doc_id, page}: OCR one page on demand
  POST /api/layout             -> multipart PDF -> per-sentence bounding boxes
  POST /api/speak              -> JSON {text, voice, speed} -> WAV audio
  POST /api/speak_aligned      -> JSON -> base64 WAV + per-word [start,end] times
  POST /api/export             -> JSON -> whole-document audio (blocking; CLI/back-compat)
  POST /api/export_job         -> JSON -> {job_id}; streams progress, then a file
  GET  /api/export_job/{id}/events  -> Server-Sent Events progress stream
  GET  /api/export_job/{id}/result  -> the finished audio file

Everything runs locally: pdfplumber (+ Tesseract for scanned pages) for
extraction, Kokoro for TTS. No data leaves the machine and there are no API
keys. OCR happens lazily — one page at a time, as the reader reaches it — so
extraction returns quickly even for large scanned documents.
"""
from __future__ import annotations

import base64
import json
import os
import queue
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (
    __version__,
    align,
    documents,
    export,
    layout,
    pdf_extract,
    segment,
    store,
    tts,
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
MAX_PDF_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_TTS_CHARS = 20_000  # guardrail per /api/speak request
MAX_EXPORT_CHARS = 500_000  # ~ several hours of audio per /api/export request
_EXPORT_MEDIA = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4b": "audio/mp4"}

_DOC_STORE = store.DocStore()
_JOB_STORE = store.JobStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the TTS model in the background so the first synthesis isn't paying
    # the ~90 MB download + session-build cost. Disabled in tests/CI via env.
    if not os.environ.get("LETTURA_NO_WARMUP"):
        threading.Thread(target=tts.prefetch, name="kokoro-warmup", daemon=True).start()
    yield


app = FastAPI(title="Lettura", version=__version__, lifespan=lifespan)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1)
    voice: str = tts.DEFAULT_VOICE
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class ExportRequest(BaseModel):
    text: str = Field(min_length=1)
    voice: str = tts.DEFAULT_VOICE
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    format: str = "wav"


class OcrPageRequest(BaseModel):
    doc_id: str
    page: int = Field(ge=1)


async def _read_pdf_upload(file: UploadFile) -> bytes:
    """Validate a PDF upload and return its bytes (used by /api/layout)."""
    if (file.content_type or "").lower() not in {"application/pdf", "application/x-pdf"}:
        raise HTTPException(status_code=415, detail="Please upload a PDF file.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded PDF is empty.")
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF exceeds the 50 MB limit.")
    return data


async def _read_document_upload(file: UploadFile) -> bytes:
    """Validate a PDF / EPUB / HTML upload and return its bytes."""
    if not documents.is_supported(file.filename or "", file.content_type or ""):
        raise HTTPException(
            status_code=415, detail="Please upload a PDF, EPUB or HTML file."
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 50 MB limit.")
    return data


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "ocr_available": pdf_extract._OCR_AVAILABLE,
        "model_state": tts.model_state(),
        "model_ready": tts.is_ready(),
        "voices": tts.ITALIAN_VOICES,
    }


@app.get("/api/voices")
def voices() -> dict:
    return {"voices": tts.ITALIAN_VOICES, "default": tts.DEFAULT_VOICE}


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)) -> dict:
    """Fast extraction for PDF / EPUB / HTML.

    For PDFs, text-layer pages return now and scanned pages are OCR'd later
    (see /api/ocr_page). EPUB and HTML are plain text — all pages are ``ready``.
    Returns a ``doc_id`` so the browser can drive read-along (and lazy OCR for
    PDFs) without re-uploading the file.
    """
    data = await _read_document_upload(file)
    try:
        quick = documents.extract_document(
            data, file.filename or "", file.content_type or ""
        )
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Could not read file: {exc}") from exc
    doc_id = _DOC_STORE.put(data)
    text = quick.text
    return {
        "doc_id": doc_id,
        "text": text,
        "sentences": segment.segment_sentences(text),
        "page_count": quick.page_count,
        "pages": [
            {
                "page": p.page,
                "status": p.status,
                "sentences": segment.segment_sentences(p.text) if p.text else [],
            }
            for p in quick.pages
        ],
        "pending_ocr_pages": [p.page for p in quick.pages if p.status == "needs_ocr"],
        "ocr_available": quick.ocr_available,
        "ocr_error": quick.ocr_error,
        "ocr_used": False,
        "ocr_pages": [],
        "char_count": len(text),
    }


@app.post("/api/ocr_page")
def ocr_page(req: OcrPageRequest) -> dict:
    """OCR a single page on demand, using the PDF cached under ``doc_id``."""
    data = _DOC_STORE.get(req.doc_id)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail="Documento non più disponibile; ricaricalo.",
        )
    if not pdf_extract._OCR_AVAILABLE:
        return {"page": req.page, "status": "ocr_failed", "text": "", "sentences": []}
    try:
        text = pdf_extract.ocr_page_text(data, req.page)
    except Exception:  # noqa: BLE001 - OCR is best-effort, degrade per page
        return {"page": req.page, "status": "ocr_failed", "text": "", "sentences": []}
    status = "ready" if text.strip() else "empty"
    return {
        "page": req.page,
        "status": status,
        "text": text,
        "sentences": segment.segment_sentences(text),
    }


@app.post("/api/layout")
async def pdf_layout(file: UploadFile = File(...)) -> dict:
    """Per-sentence bounding boxes for highlighting on the rendered PDF."""
    data = await _read_pdf_upload(file)
    try:
        return layout.extract_layout(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Could not read PDF: {exc}") from exc


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


@app.post("/api/speak_aligned")
def speak_aligned(req: SpeakRequest) -> dict:
    """Synthesize one sentence; return base64 WAV plus per-word [start,end] times.

    Used by the read-along view to move a word-level highlight as it plays.
    """
    if len(req.text) > MAX_TTS_CHARS:
        raise HTTPException(status_code=413, detail="Text too long for alignment.")
    try:
        samples, sample_rate = tts.synthesize_array(
            req.text, voice=req.voice, speed=req.speed
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    duration = len(samples) / sample_rate
    wav = tts.to_wav_bytes(samples, sample_rate)
    return {
        "sample_rate": sample_rate,
        "audio_base64": base64.b64encode(wav).decode("ascii"),
        "words": align.align_words(req.text, duration),
    }


def _export_bytes(req: ExportRequest, fmt: str, progress=None) -> tuple[bytes, str]:
    """Synthesize + encode a whole document. Returns (data, media_type)."""
    audio, sample_rate = export.synthesize_long(
        req.text, voice=req.voice, speed=req.speed, progress=progress
    )
    data = export.encode(audio, sample_rate, fmt=fmt)
    return data, _EXPORT_MEDIA[fmt]


def _validate_export(req: ExportRequest) -> str:
    fmt = req.format.lower()
    if fmt not in _EXPORT_MEDIA:
        raise HTTPException(status_code=400, detail="format must be wav, mp3, or m4b.")
    if len(req.text) > MAX_EXPORT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Text exceeds {MAX_EXPORT_CHARS} characters.",
        )
    return fmt


@app.post("/api/export")
def export_audio(req: ExportRequest) -> Response:
    """Synthesize a whole document into one downloadable audio file (blocking).

    Kept for the CLI and back-compat; the frontend uses /api/export_job so it
    can show a progress bar. WAV needs no extra tools; MP3/M4B require ffmpeg.
    """
    fmt = _validate_export(req)
    try:
        data, media_type = _export_bytes(req, fmt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:  # Kokoro / ffmpeg missing
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="lettura.{fmt}"'},
    )


@app.post("/api/export_job")
def export_job_start(req: ExportRequest) -> dict:
    """Start a background export. Poll progress via .../events, fetch .../result."""
    fmt = _validate_export(req)
    job_id, job = _JOB_STORE.create()

    def run() -> None:
        try:
            def progress(done: int, total: int) -> None:
                job.events.put({"phase": "synth", "done": done, "total": total})

            job.events.put({"phase": "synth", "done": 0, "total": 1})
            audio, sample_rate = export.synthesize_long(
                req.text, voice=req.voice, speed=req.speed, progress=progress
            )
            job.events.put({"phase": "encode", "done": 0, "total": 1})
            job.result = export.encode(audio, sample_rate, fmt=fmt)
            job.media_type = _EXPORT_MEDIA[fmt]
            job.filename = f"lettura.{fmt}"
            job.done = True
            job.events.put({"phase": "done"})
        except (ValueError, RuntimeError) as exc:
            job.error = str(exc)
            job.events.put({"phase": "error", "detail": str(exc)})
        except Exception:  # noqa: BLE001
            job.error = "Esportazione non riuscita."
            job.events.put({"phase": "error", "detail": job.error})

    threading.Thread(target=run, name=f"export-{job_id}", daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/export_job/{job_id}/events")
def export_job_events(job_id: str) -> StreamingResponse:
    job = _JOB_STORE.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Esportazione non trovata.")

    def stream():
        while True:
            try:
                event = job.events.get(timeout=15)
            except queue.Empty:  # heartbeat to keep the connection open
                yield ": keep-alive\n\n"
                continue
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("phase") in ("done", "error"):
                break

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/export_job/{job_id}/result")
def export_job_result(job_id: str) -> Response:
    job = _JOB_STORE.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Esportazione non trovata.")
    if job.error is not None:
        raise HTTPException(status_code=500, detail=job.error)
    if not job.done or job.result is None:
        raise HTTPException(status_code=404, detail="File non ancora pronto.")
    return Response(
        content=job.result,
        media_type=job.media_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{job.filename}"'},
    )


# --- Static frontend (mounted last so it doesn't shadow /api routes) ---
@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
