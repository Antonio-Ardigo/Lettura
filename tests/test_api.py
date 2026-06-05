"""API smoke tests.

Skipped automatically where the web/ML deps aren't installed (e.g. the
lightweight CI lane), so the pure-logic tests can still run everywhere.
"""
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

client = TestClient(app)
SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "esempio.pdf"


def test_health_ok():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


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


def test_speak_without_kokoro_is_graceful():
    # No model weights available in test env -> a clear 503, never a crash.
    res = client.post("/api/speak", json={"text": "Ciao."})
    assert res.status_code in (200, 503)
