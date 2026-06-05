"""Generate 5 Italian sample PDFs (digital + scanned) for the experience test.

Digital PDFs have a real text layer (fast path). Scanned PDFs embed the text as
a rendered image with NO text layer, so they exercise the on-demand OCR path.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

OUT = Path(__file__).resolve().parent / "pdfs"
OUT.mkdir(exist_ok=True)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

DANTE = (
    "Nel mezzo del cammin di nostra vita mi ritrovai per una selva oscura, "
    "ché la diritta via era smarrita. Ahi quanto a dir qual era è cosa dura "
    "esta selva selvaggia e aspra e forte che nel pensier rinova la paura!"
)
PARAGRAPH = (
    "La lettura ad alta voce è un'attività che migliora la comprensione del "
    "testo e la pronuncia. Città, università, perché, è, così: gli accenti "
    "italiani devono essere riconosciuti correttamente. Questo documento "
    "contiene più frasi per verificare la segmentazione e i tempi di lettura. "
    "Il sole tramonta lentamente dietro le colline toscane mentre il vento "
    "accarezza i campi di grano dorato."
)
ACCENTS = (
    "Perché è così difficile? La città di Forlì, l'università di Bologna, "
    "il caffè della stazione, qualità e quantità, virtù e civiltà. "
    "Niccolò Machiavelli scrisse «Il Principe» nel Cinquecento. "
    "Èrecord di àncore, ìmpeto, òboli e ùmidi sentieri."
)


def wrap(text: str, width: int = 60) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def digital_page(c: canvas.Canvas, title: str, body: str) -> None:
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, 770, title)
    c.setFont("Helvetica", 12)
    y = 740
    for line in wrap(body, 70):
        c.drawString(72, y, line)
        y -= 18
    c.showPage()


def scanned_page_image(title: str, body: str) -> ImageReader:
    """Render text to a white image (no selectable text -> forces OCR)."""
    img = Image.new("RGB", (1240, 1754), "white")  # ~150 DPI A4
    draw = ImageDraw.Draw(img)
    title_font = ImageFont.truetype(FONT, 46)
    body_font = ImageFont.truetype(FONT, 34)
    draw.text((90, 90), title, fill="black", font=title_font)
    y = 200
    for line in wrap(body, 52):
        draw.text((90, y), line, fill="black", font=body_font)
        y += 52
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def scanned_page(c: canvas.Canvas, title: str, body: str) -> None:
    c.drawImage(scanned_page_image(title, body), 0, 0, width=A4[0], height=A4[1])
    c.showPage()


def build():
    # 1. Short digital (1 page)
    c = canvas.Canvas(str(OUT / "it1_short_digital.pdf"), pagesize=A4)
    digital_page(c, "Divina Commedia — Inferno", DANTE)
    c.save()

    # 2. Long digital (5 pages)
    c = canvas.Canvas(str(OUT / "it2_long_digital.pdf"), pagesize=A4)
    for i in range(1, 6):
        digital_page(c, f"Capitolo {i}", PARAGRAPH + " " + DANTE)
    c.save()

    # 3. Scanned, image-only (2 pages -> 2 OCR pages)
    c = canvas.Canvas(str(OUT / "it3_scanned.pdf"), pagesize=A4)
    scanned_page(c, "Documento Scansionato 1", PARAGRAPH)
    scanned_page(c, "Documento Scansionato 2", DANTE)
    c.save()

    # 4. Mixed: 1 digital page + 2 scanned pages
    c = canvas.Canvas(str(OUT / "it4_mixed.pdf"), pagesize=A4)
    digital_page(c, "Pagina Digitale", DANTE)
    scanned_page(c, "Pagina Scansionata A", PARAGRAPH)
    scanned_page(c, "Pagina Scansionata B", ACCENTS)
    c.save()

    # 5. Scanned with heavy accents (2 pages) — stresses OCR + cleanup
    c = canvas.Canvas(str(OUT / "it5_scanned_accents.pdf"), pagesize=A4)
    scanned_page(c, "Accenti e Citazioni 1", ACCENTS)
    scanned_page(c, "Accenti e Citazioni 2", PARAGRAPH)
    c.save()

    for p in sorted(OUT.glob("*.pdf")):
        print(f"  {p.name:30s} {p.stat().st_size/1024:6.1f} KB")


if __name__ == "__main__":
    build()
