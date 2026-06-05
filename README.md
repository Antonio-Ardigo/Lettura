# Lettura

Read Italian PDFs aloud with a single, natural narrator — fully **offline** and
built only from **permissively licensed** (commercial-safe) open-source tools.

Upload a PDF → Lettura extracts the Italian text (with OCR fallback for scanned
documents) → an offline neural voice reads it back to you in the browser, with
the current sentence highlighted **either in a text view or on the rendered
original PDF**. You can also **export a whole document to one audio file**
(WAV / MP3 / M4B with chapters).

## Why these tools

| Concern | Tool | License |
|---|---|---|
| Web API | FastAPI + Uvicorn | MIT / BSD |
| PDF text extraction | [pdfplumber](https://github.com/jsvine/pdfplumber), pypdf | MIT |
| OCR (scanned PDFs) | Tesseract + `ita` pack | Apache-2.0 |
| Text-to-speech | [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) via ONNX | Apache-2.0 |
| PDF rendering (browser) | [PDF.js](https://github.com/mozilla/pdf.js) (vendored) | Apache-2.0 |
| Audio export (MP3/M4B) | ffmpeg (via imageio-ffmpeg) | LGPL/GPL |

No cloud APIs and no API keys. TTS runs through **ONNX Runtime** (no torch); the
weights are mirrored on GitHub and downloaded **once** (~90 MB) into a local
cache, after which everything runs offline.

> Note on PyMuPDF: it's faster than pdfplumber but AGPL-3.0 (needs a paid
> license for closed-source commercial use), so this project uses pdfplumber to
> stay commercial-safe. Swap it in if your licensing allows.

## Architecture

```
PDF ──▶ extract_quick (pdfplumber, NO OCR)
          ├─ text-layer pages ─▶ ready immediately ─▶ sentence segmentation
          └─ scanned pages     ─▶ marked "needs_ocr" (held by doc_id)
        │                              │
        │                              ▼  (lazily, as the reader reaches a page)
        │                        Tesseract(ita) OCR ─▶ ocr_clean ─▶ spliced in
        ▼
   Kokoro TTS (ONNX, Italian) ─▶ WAV/MP3/M4B ─▶ browser playback / download
        │
        └─ long exports run as a background job streaming progress over SSE
```

Extraction returns **fast**: only the text layer is read up front. Scanned pages
are OCR'd **one at a time, on demand, while you read** (with a progress bar),
and the raw OCR output is sanitised (`ocr_clean`) before it is ever spoken or
exported. The TTS model is **warmed up in the background at startup** so the
first synthesis isn't blocked on the ~90 MB download.

- `backend/pdf_extract.py` — fast extract (`extract_quick`), on-demand OCR (`ocr_page_text`), OCR sanitisation (`ocr_clean`) + cleanup
- `backend/store.py` — small in-memory TTL caches: uploaded PDFs (`doc_id`) and export jobs (`job_id`)
- `backend/segment.py` — Italian sentence segmentation
- `backend/layout.py` — per-sentence bounding boxes on the page (`/api/layout`)
- `backend/tts.py` — Kokoro ONNX Italian TTS (background warm-up; download-once, then offline)
- `backend/export.py` — chunk → synthesize → concatenate to WAV/MP3/M4B (+ CLI)
- `backend/main.py` — FastAPI routes (lazy OCR + SSE export progress) + serves the frontend
- `frontend/` — vanilla HTML/CSS/JS UI; `frontend/vendor/pdfjs/` is vendored PDF.js

## Run it locally

### 1. System dependencies

```bash
# Debian/Ubuntu
sudo apt-get install -y espeak-ng tesseract-ocr tesseract-ocr-ita poppler-utils
# macOS (Homebrew)
brew install espeak-ng tesseract tesseract-lang poppler
```

- `espeak-ng` — phonemiser Kokoro uses for Italian (required)
- `tesseract-ocr` + `tesseract-ocr-ita`, `poppler-utils` — OCR for scanned PDFs (optional)
- ffmpeg for MP3/M4B export is bundled via `imageio-ffmpeg` (no system install needed)

### 2. Python dependencies

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Start the server

```bash
uvicorn backend.main:app --reload
```

Open http://127.0.0.1:8000 — upload a PDF (try `samples/esempio.pdf`) and
**Estrai testo**. Then:

- **Leggi con evidenziazione** — read-along, highlighting each sentence. Switch
  between the **Testo** and **Documento** tabs to follow along on the extracted
  text or on the rendered original page.
- **Scarica audio** — export the whole document as WAV / MP3 / M4B.

The first synthesis downloads the Kokoro weights (~90 MB from GitHub), then runs
offline. Pre-seed them by setting `LETTURA_MODEL_DIR` to a folder that already
contains `kokoro-v1.0.int8.onnx` and `voices-v1.0.bin`.

### Export from the command line

Best for long documents (an hour of audio is a multi-minute batch job):

```bash
python -m backend.export samples/esempio.pdf out.m4b --chapters-per-page
python -m backend.export book.pdf out.mp3 --voice im_nicola
```

## Install on Windows

A one-command installer sets Lettura up under `C:\Program Files\Lettura` with a
Start-Menu shortcut — see [`install/windows/README.md`](install/windows/README.md).
In short, from an **Administrator** PowerShell inside a clone of the repo:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install\windows\Install-Lettura.ps1
```

## Develop & test

```bash
pip install -r requirements-dev.txt
ruff check backend/ tests/     # lint
pytest -q                      # unit tests
```

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Liveness + whether OCR is available + TTS model readiness |
| `GET` | `/api/voices` | Available Italian voices |
| `POST` | `/api/extract` | `multipart` PDF → fast text-layer extract + `doc_id` + pages needing OCR |
| `POST` | `/api/ocr_page` | JSON `{doc_id, page}` → OCR one page on demand (cleaned) |
| `POST` | `/api/layout` | `multipart` PDF → per-sentence bounding boxes |
| `POST` | `/api/speak` | JSON `{text, voice, speed}` → WAV audio |
| `POST` | `/api/export` | JSON `{text, voice, speed, format}` → WAV/MP3/M4B (blocking; CLI/back-compat) |
| `POST` | `/api/export_job` | JSON → `{job_id}`; progress via SSE `…/events`, file via `…/result` |

## Status

Working prototype: single-voice Italian narration with **sentence-synced
read-along** (in a text view or overlaid on the original PDF page), and
**whole-document export** to WAV/MP3/M4B with per-page chapters. Possible next
steps — streaming very long documents, per-character voices, word-level
highlighting.

## License

The tools above are permissively licensed; choose a license for this project
that suits your needs.
