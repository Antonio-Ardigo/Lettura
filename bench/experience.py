"""Experience benchmark: time & responsiveness of the new lazy-OCR / progress flow.

Measures, per PDF:
  * /api/extract latency (the fast path the user now waits on)
  * the OLD eager full-document OCR time, for comparison (the wait we removed)
  * per-page /api/ocr_page latency (what happens "during reading")
and, once, the TTS model warm-up + a short export with live progress.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("LETTURA_NO_WARMUP", "1")  # time warm-up explicitly instead

from fastapi.testclient import TestClient  # noqa: E402

from backend import pdf_extract, tts  # noqa: E402
from backend.main import app  # noqa: E402

PDFS = sorted((Path(__file__).resolve().parent / "pdfs").glob("*.pdf"))
client = TestClient(app)


def t() -> float:
    return time.perf_counter()


def ms(dt: float) -> str:
    return f"{dt * 1000:7.1f} ms"


def bench_extract():
    print("=" * 78)
    print("1) EXTRACTION RESPONSIVENESS  —  time to first usable text")
    print("=" * 78)
    print(f"{'PDF':28s}{'pages':>6}{'/api/extract':>14}{'old eager OCR':>16}{'pending':>9}")
    print("-" * 78)
    results = {}
    for pdf in PDFS:
        data = pdf.read_bytes()
        # New fast path (what the browser awaits now).
        start = t()
        res = client.post(
            "/api/extract",
            files={"file": (pdf.name, data, "application/pdf")},
        )
        extract_dt = t() - start
        body = res.json()
        pending = body["pending_ocr_pages"]
        # Old behaviour: extract_pdf OCR'd every scanned page up front.
        start = t()
        pdf_extract.extract_pdf(data)
        eager_dt = t() - start
        results[pdf.name] = (body, extract_dt, eager_dt)
        speedup = f"{eager_dt / extract_dt:4.0f}x faster" if pending else "—"
        print(
            f"{pdf.name:28s}{body['page_count']:>6}{ms(extract_dt):>14}"
            f"{ms(eager_dt):>16}{len(pending):>9}   {speedup}"
        )
    return results


def bench_ocr_pages(results):
    print()
    print("=" * 78)
    print("2) ON-DEMAND OCR  —  per-page latency 'during the reading'")
    print("=" * 78)
    for name, (body, _e, _o) in results.items():
        pending = body["pending_ocr_pages"]
        if not pending:
            continue
        doc_id = body["doc_id"]
        print(f"\n{name}  (pagine da OCR: {pending})")
        for page in pending:
            start = t()
            r = client.post("/api/ocr_page", json={"doc_id": doc_id, "page": page})
            dt = t() - start
            pj = r.json()
            sample = " ".join(pj["sentences"][:1])[:70] if pj["sentences"] else "(vuoto)"
            print(f"   pagina {page}: {ms(dt)}  status={pj['status']:9s} » {sample}…")


def bench_quality(results):
    print()
    print("=" * 78)
    print("3) OCR CLEANUP QUALITY  —  accents kept, garbage removed")
    print("=" * 78)
    name = "it5_scanned_accents.pdf"
    body, *_ = results[name]
    doc_id = body["doc_id"]
    r = client.post("/api/ocr_page", json={"doc_id": doc_id, "page": 1})
    text = r.json()["text"]
    accents = [a for a in "àèéìòùÈ" if a in text]
    ctrl = [c for c in text if ord(c) < 32 and c not in "\n\t"]
    print(f"  accenti riconosciuti presenti nel testo: {''.join(accents) or '(nessuno)'}")
    print(f"  caratteri di controllo/garbage residui : {len(ctrl)}")
    print(f"  estratto: {text[:160]!r}")


def bench_tts():
    print()
    print("=" * 78)
    print("4) TTS START-UP & EXPORT  —  warm-up cost and export progress")
    print("=" * 78)
    start = t()
    try:
        tts.prefetch()
    except Exception as exc:  # noqa: BLE001
        print(f"  warm-up non riuscito (offline?): {exc}")
        return
    warm_dt = t() - start
    state = "ready" if tts.is_ready() else tts.model_state()
    print(f"  warm-up modello (download+sessione): {warm_dt:6.1f} s  -> stato={state}")
    if not tts.is_ready():
        print("  modello non pronto; salto l'export.")
        return
    # Short export with live progress events.
    pdf = PDFS[0]
    body = client.post(
        "/api/extract", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")}
    ).json()
    text = body["text"]
    start = t()
    jid = client.post("/api/export_job", json={"text": text, "format": "wav"}).json()["job_id"]
    first_event = None
    events = 0
    with client.stream("GET", f"/api/export_job/{jid}/events") as s:
        for line in s.iter_lines():
            if line.startswith("data: "):
                if first_event is None:
                    first_event = t() - start
                events += 1
                import json

                if json.loads(line[6:])["phase"] in ("done", "error"):
                    break
    total_dt = t() - start
    audio = client.get(f"/api/export_job/{jid}/result")
    print(
        f"  export '{pdf.name}' ({len(text)} caratteri): {total_dt:5.1f} s totali, "
        f"primo evento progresso a {first_event*1000:.0f} ms, {events} eventi, "
        f"audio {len(audio.content)/1024:.0f} KB"
    )


if __name__ == "__main__":
    print(f"Benchmark su {len(PDFS)} PDF italiani  (OCR disponibile: {pdf_extract._OCR_AVAILABLE})\n")
    results = bench_extract()
    bench_ocr_pages(results)
    bench_quality(results)
    bench_tts()
