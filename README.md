# Lettura

Read Italian PDFs aloud with a single, natural narrator — fully **offline** and
built only from **permissively licensed** (commercial-safe) open-source tools.

Upload a PDF → Lettura extracts the Italian text (with OCR fallback for scanned
documents) → an offline neural voice reads it back to you in the browser.

## Why these tools

| Concern | Tool | License |
|---|---|---|
| Web API | FastAPI + Uvicorn | MIT / BSD |
| PDF text extraction | [pdfplumber](https://github.com/jsvine/pdfplumber), pypdf | MIT |
| OCR (scanned PDFs) | Tesseract + `ita` pack | Apache-2.0 |
| Text-to-speech | [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) | Apache-2.0 |

No cloud APIs, no API keys, no data leaving the machine.

> Note on PyMuPDF: it's faster than pdfplumber but AGPL-3.0 (needs a paid
> license for closed-source commercial use), so this project uses pdfplumber to
> stay commercial-safe. Swap it in if your licensing allows.

## Architecture

```
PDF ──▶ has text layer?
          ├─ yes ─▶ pdfplumber extract
          └─ no  ─▶ Tesseract(ita) OCR
        │
        ▼
   text cleanup (de-hyphenate, join soft line breaks, keep paragraphs)
        │
        ▼
   Kokoro TTS (Italian voice) ─▶ WAV ─▶ browser audio player
```

- `backend/pdf_extract.py` — extraction + OCR fallback + cleanup
- `backend/tts.py` — Kokoro Italian TTS wrapper (lazy model load)
- `backend/main.py` — FastAPI routes + serves the frontend
- `frontend/` — vanilla HTML/CSS/JS single-page UI

## Run it locally

### 1. System dependencies

```bash
# Debian/Ubuntu
sudo apt-get install -y espeak-ng tesseract-ocr tesseract-ocr-ita poppler-utils
# macOS (Homebrew)
brew install espeak-ng tesseract tesseract-lang poppler
```

- `espeak-ng` — phonemiser Kokoro uses for Italian
- `tesseract-ocr` + `tesseract-ocr-ita` — OCR for scanned PDFs (optional)
- `poppler-utils` — renders PDF pages to images for OCR (optional)

### 2. Python dependencies

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Start the server

```bash
uvicorn backend.main:app --reload
```

Open http://127.0.0.1:8000 — upload a PDF (try `samples/esempio.pdf`), extract,
then press **Leggi ad alta voce**. The first synthesis downloads the Kokoro
weights (~few hundred MB), then runs offline.

## Develop & test

```bash
pip install -r requirements-dev.txt
ruff check backend/ tests/     # lint
pytest -q                      # unit tests
```

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Liveness + whether OCR is available |
| `GET` | `/api/voices` | Available Italian voices |
| `POST` | `/api/extract` | `multipart` PDF upload → cleaned text JSON |
| `POST` | `/api/speak` | JSON `{text, voice, speed}` → WAV audio |

## Status

Early prototype: single-voice narration. Possible next steps — sentence-synced
highlighting (read-along), chapter/M4B export, and streaming long documents.

## License

The tools above are permissively licensed; choose a license for this project
that suits your needs.
