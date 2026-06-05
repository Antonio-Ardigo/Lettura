"""API smoke tests.

Skipped automatically where the web/ML deps aren't installed (e.g. the
lightweight CI lane), so the pure-logic tests can still run everywhere.
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from backend import export  # noqa: E402
from backend.main import app  # noqa: E402

client = TestClient(app)
SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "esempio.pdf"


def test_health_ok():
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    # New readiness signals the frontend uses to show "modello in preparazione…".
    assert isinstance(body["model_ready"], bool)
    assert body["model_state"] in {"cold", "warming", "ready", "failed"}
    assert isinstance(body["ocr_available"], bool)


def test_extract_returns_sentences():
    with open(SAMPLE, "rb") as fh:
        res = client.post(
            "/api/extract",
            files={"file": ("esempio.pdf", fh, "application/pdf")},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["page_count"] == 1
    assert isinstance(data["sentences"], list)
    assert len(data["sentences"]) >= 2
    assert "Nel mezzo del cammin" in data["sentences"][0]
    assert data["ocr_error"] is False  # digital sample never needs OCR
    # Lazy-OCR contract: a doc_id to OCR scanned pages later, and a per-page list.
    assert isinstance(data["doc_id"], str) and data["doc_id"]
    assert data["pending_ocr_pages"] == []  # digital sample needs no OCR
    assert data["pages"][0]["status"] == "ready"


def test_ocr_page_unknown_doc_is_404():
    res = client.post("/api/ocr_page", json={"doc_id": "does-not-exist", "page": 1})
    assert res.status_code == 404


def test_ocr_page_rejects_invalid_page_number():
    res = client.post("/api/ocr_page", json={"doc_id": "x", "page": 0})
    assert res.status_code == 422  # page must be >= 1


def test_export_job_streams_progress_then_serves_file(monkeypatch):
    # Fake the heavy synthesis/encoding so the SSE plumbing is tested offline.
    def fake_synth(text, *, voice="if_sara", speed=1.0, progress=None):
        if progress:
            progress(1, 2)
            progress(2, 2)
        return [0.0] * 8, 24_000

    def fake_encode(audio, sample_rate, *, fmt="wav", **kwargs):
        return b"RIFFfakeaudio"

    monkeypatch.setattr(export, "synthesize_long", fake_synth)
    monkeypatch.setattr(export, "encode", fake_encode)

    start = client.post("/api/export_job", json={"text": "Ciao mondo.", "format": "wav"})
    assert start.status_code == 200
    job_id = start.json()["job_id"]

    phases = []
    with client.stream("GET", f"/api/export_job/{job_id}/events") as stream:
        for line in stream.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line[len("data: "):])
                phases.append(event["phase"])
                if event["phase"] in ("done", "error"):
                    break
    assert "synth" in phases
    assert phases[-1] == "done"

    result = client.get(f"/api/export_job/{job_id}/result")
    assert result.status_code == 200
    assert result.content == b"RIFFfakeaudio"


def test_export_job_events_unknown_job_is_404():
    res = client.get("/api/export_job/nope/events")
    assert res.status_code == 404


def test_export_job_result_reports_failure_distinctly(monkeypatch):
    # A failed job must not look like "still working" to a client polling /result.
    def boom(text, *, voice="if_sara", speed=1.0, progress=None):
        raise RuntimeError("ffmpeg non disponibile.")

    monkeypatch.setattr(export, "synthesize_long", boom)
    start = client.post("/api/export_job", json={"text": "Ciao.", "format": "mp3"})
    job_id = start.json()["job_id"]

    # Drain the stream so the worker thread has finished and recorded the error.
    with client.stream("GET", f"/api/export_job/{job_id}/events") as stream:
        for line in stream.iter_lines():
            if line.startswith("data: ") and json.loads(line[6:])["phase"] == "error":
                break

    res = client.get(f"/api/export_job/{job_id}/result")
    assert res.status_code == 500
    assert "ffmpeg" in res.json()["detail"]


def test_speak_without_kokoro_is_graceful():
    # No model weights available in test env -> a clear 503, never a crash.
    res = client.post("/api/speak", json={"text": "Ciao."})
    assert res.status_code in (200, 503)
