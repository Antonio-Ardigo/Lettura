"use strict";

const $ = (id) => document.getElementById(id);
const fileInput = $("file");
const fileDrop = $("filedrop");
const fileLabel = $("filelabel");
const extractBtn = $("extractBtn");
const resultCard = $("resultCard");
const meta = $("meta");
const reader = $("reader");
const docview = $("docview");
const textViewBtn = $("textViewBtn");
const docViewBtn = $("docViewBtn");
const voiceSelect = $("voice");
const speed = $("speed");
const speedVal = $("speedval");
const readAlongBtn = $("readAlongBtn");
const speakBtn = $("speakBtn");
const formatSel = $("format");
const downloadBtn = $("downloadBtn");
const player = $("player");
const statusEl = $("status");

let selectedFile = null;
let fullText = "";
let textSentences = []; // strings, from /api/extract
let layoutSentences = []; // [{text, boxes:[...]}], from /api/layout
let pdfDoc = null;

let mode = "text"; // "text" | "doc"
let activeSentences = []; // strings the read-along will speak
let activeHighlight = () => {}; // sentence-level highlight for the current mode

let playing = false;
let currentIndex = 0;
let currentAudioUrl = null;
let endedResolver = null;
let rafId = null;

function setStatus(message, isError = false) {
  statusEl.textContent = message || "";
  statusEl.classList.toggle("error", Boolean(isError));
}

// --- File selection (click + drag & drop) ---
fileInput.addEventListener("change", () => selectFile(fileInput.files[0]));

["dragenter", "dragover"].forEach((evt) =>
  fileDrop.addEventListener(evt, (e) => {
    e.preventDefault();
    fileDrop.classList.add("drag");
  })
);
["dragleave", "drop"].forEach((evt) =>
  fileDrop.addEventListener(evt, (e) => {
    e.preventDefault();
    fileDrop.classList.remove("drag");
  })
);
fileDrop.addEventListener("drop", (e) => selectFile(e.dataTransfer.files[0]));

function selectFile(file) {
  if (!file) return;
  if (file.type !== "application/pdf") {
    setStatus("Seleziona un file PDF.", true);
    return;
  }
  selectedFile = file;
  fileLabel.textContent = file.name;
  extractBtn.disabled = false;
  setStatus("");
}

// --- Extract ---
extractBtn.addEventListener("click", async () => {
  if (!selectedFile) return;
  stopReadAlong();
  extractBtn.disabled = true;
  setStatus("Estrazione del testo in corso…");
  try {
    const form = new FormData();
    form.append("file", selectedFile);
    const res = await fetch("/api/extract", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Estrazione non riuscita.");
    fullText = data.text;
    textSentences = data.sentences || [];
    pdfDoc = null;
    layoutSentences = [];
    docview.innerHTML = "";
    renderReader();
    setMode("text", { force: true });
    meta.textContent =
      `${data.page_count} pagine · ${textSentences.length} frasi · ${data.char_count} caratteri` +
      (data.ocr_used ? ` · OCR sulle pagine ${data.ocr_pages.join(", ")}` : "");
    resultCard.hidden = false;
    if (data.ocr_error) {
      setStatus(
        "Alcune pagine sembrano scansionate ma l'OCR non è disponibile — " +
          "installa Tesseract con la lingua italiana (ita.traineddata).",
        true
      );
    } else {
      setStatus("");
    }
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    extractBtn.disabled = false;
  }
});

// --- Text view (sentences split into word spans for word-level highlight) ---
function renderReader() {
  reader.innerHTML = "";
  currentIndex = 0;
  textSentences.forEach((sentence, i) => {
    const span = document.createElement("span");
    span.className = "sentence";
    span.dataset.index = String(i);
    sentence.split(/(\s+)/).forEach((token) => {
      if (token === "") return;
      if (/^\s+$/.test(token)) {
        span.appendChild(document.createTextNode(token));
      } else {
        const word = document.createElement("span");
        word.className = "word";
        word.textContent = token;
        span.appendChild(word);
      }
    });
    span.appendChild(document.createTextNode(" "));
    span.addEventListener("click", () => {
      if (playing) stopReadAlong();
      startReadAlong(i);
    });
    reader.appendChild(span);
  });
}

function highlightText(i) {
  reader
    .querySelectorAll(".sentence.active")
    .forEach((el) => el.classList.remove("active"));
  const el = reader.querySelector(`.sentence[data-index="${i}"]`);
  if (el) {
    el.classList.add("active");
    el.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

// --- Document view (PDF.js render + box overlay) ---
async function ensurePdfRendered() {
  if (pdfDoc) return;
  const pdfjsLib = window.pdfjsLib;
  if (!pdfjsLib) throw new Error("PDF.js non disponibile.");
  pdfjsLib.GlobalWorkerOptions.workerSrc = "/vendor/pdfjs/pdf.worker.js";
  const buffer = await selectedFile.arrayBuffer();
  pdfDoc = await pdfjsLib.getDocument({ data: buffer }).promise;
  docview.innerHTML = "";
  for (let p = 1; p <= pdfDoc.numPages; p++) {
    const page = await pdfDoc.getPage(p);
    const viewport = page.getViewport({ scale: 1.4 });
    const pageDiv = document.createElement("div");
    pageDiv.className = "pdf-page";
    pageDiv.style.width = `${viewport.width}px`;
    pageDiv.style.height = `${viewport.height}px`;
    const canvas = document.createElement("canvas");
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    const overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.dataset.page = String(p - 1);
    pageDiv.appendChild(canvas);
    pageDiv.appendChild(overlay);
    docview.appendChild(pageDiv);
    await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
  }
}

async function fetchLayout() {
  const form = new FormData();
  form.append("file", selectedFile);
  const res = await fetch("/api/layout", { method: "POST", body: form });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Analisi del layout non riuscita.");
  layoutSentences = data.sentences || [];
}

function highlightDoc(i) {
  docview.querySelectorAll(".hl").forEach((el) => el.remove());
  const sentence = layoutSentences[i];
  if (!sentence) return;
  let first = null;
  sentence.boxes.forEach((box) => {
    const overlay = docview.querySelector(`.overlay[data-page="${box.page}"]`);
    if (!overlay) return;
    const w = overlay.clientWidth;
    const h = overlay.clientHeight;
    const hl = document.createElement("div");
    hl.className = "hl";
    hl.style.left = `${box.x0 * w}px`;
    hl.style.top = `${box.y0 * h}px`;
    hl.style.width = `${(box.x1 - box.x0) * w}px`;
    hl.style.height = `${(box.y1 - box.y0) * h}px`;
    overlay.appendChild(hl);
    if (!first) first = hl;
  });
  if (first) first.scrollIntoView({ block: "center", behavior: "smooth" });
}

// --- View switching ---
async function setMode(next, { force = false } = {}) {
  if (mode === next && !force) return;
  stopReadAlong();
  mode = next;
  textViewBtn.classList.toggle("active", mode === "text");
  docViewBtn.classList.toggle("active", mode === "doc");
  reader.hidden = mode !== "text";
  docview.hidden = mode !== "doc";

  if (mode === "doc") {
    setStatus("Rendering del documento…");
    try {
      await ensurePdfRendered();
      if (layoutSentences.length === 0) await fetchLayout();
      activeSentences = layoutSentences.map((s) => s.text);
      activeHighlight = highlightDoc;
      setStatus(
        layoutSentences.length === 0
          ? "Nessun testo selezionabile in questa pagina (forse è scansionata)."
          : ""
      );
    } catch (err) {
      setStatus(err.message, true);
    }
  } else {
    activeSentences = textSentences;
    activeHighlight = highlightText;
  }
}

textViewBtn.addEventListener("click", () => setMode("text"));
docViewBtn.addEventListener("click", () => setMode("doc"));

// --- Voices + speed ---
async function loadVoices() {
  try {
    const res = await fetch("/api/voices");
    const data = await res.json();
    voiceSelect.innerHTML = "";
    data.voices.forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      if (v === data.default) opt.selected = true;
      voiceSelect.appendChild(opt);
    });
  } catch {
    /* voices endpoint unavailable; leave selector empty */
  }
}

speed.addEventListener("input", () => {
  speedVal.textContent = `${Number(speed.value).toFixed(1)}×`;
});

// --- Synthesis helpers ---
async function synth(text) {
  const res = await fetch("/api/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,
      voice: voiceSelect.value || undefined,
      speed: Number(speed.value),
    }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Sintesi vocale non riuscita.");
  }
  return URL.createObjectURL(await res.blob());
}

function wavUrlFromBase64(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let k = 0; k < binary.length; k++) bytes[k] = binary.charCodeAt(k);
  return URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
}

// In the text view we request word timings to move a word-level highlight.
async function fetchClip(text, aligned) {
  if (!aligned) {
    return { url: await synth(text), words: null };
  }
  const res = await fetch("/api/speak_aligned", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,
      voice: voiceSelect.value || undefined,
      speed: Number(speed.value),
    }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Sintesi vocale non riuscita.");
  }
  const data = await res.json();
  return { url: wavUrlFromBase64(data.audio_base64), words: data.words };
}

function playUrl(url) {
  return new Promise((resolve) => {
    endedResolver = resolve;
    player.src = url;
    player.hidden = false;
    player.onended = () => resolve("ended");
    player.play();
  });
}

// --- Word-level highlight, driven by the audio clock ---
function startWordTracker(sentenceIndex, words) {
  const sentenceEl = reader.querySelector(
    `.sentence[data-index="${sentenceIndex}"]`
  );
  if (!sentenceEl) return;
  const wordEls = sentenceEl.querySelectorAll(".word");
  let last = -1;
  const tick = () => {
    const t = player.currentTime;
    let active = words.findIndex((w) => t >= w.start && t < w.end);
    if (active === -1 && words.length && t >= words[words.length - 1].end) {
      active = words.length - 1;
    }
    if (active !== last) {
      if (last >= 0 && wordEls[last]) wordEls[last].classList.remove("wordactive");
      if (active >= 0 && wordEls[active]) {
        wordEls[active].classList.add("wordactive");
        wordEls[active].scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
      last = active;
    }
    rafId = requestAnimationFrame(tick);
  };
  rafId = requestAnimationFrame(tick);
}

function stopWordTracker() {
  if (rafId) cancelAnimationFrame(rafId);
  rafId = null;
  reader
    .querySelectorAll(".word.wordactive")
    .forEach((el) => el.classList.remove("wordactive"));
}

// --- Read-along (sentence highlight + word-level highlight in the text view) ---
async function startReadAlong(from) {
  if (playing || activeSentences.length === 0) return;
  playing = true;
  setReadAlongUI(true);
  setStatus("Generazione dell'audio…");
  let i = from;
  for (; playing && i < activeSentences.length; i++) {
    currentIndex = i;
    activeHighlight(i);
    let clip;
    try {
      clip = await fetchClip(activeSentences[i], mode === "text");
    } catch (err) {
      setStatus(err.message, true);
      break;
    }
    if (!playing) {
      URL.revokeObjectURL(clip.url);
      break;
    }
    setStatus("");
    if (currentAudioUrl) URL.revokeObjectURL(currentAudioUrl);
    currentAudioUrl = clip.url;
    if (mode === "text" && clip.words && clip.words.length) {
      startWordTracker(i, clip.words);
    }
    await playUrl(clip.url);
    stopWordTracker();
  }
  if (i >= activeSentences.length) currentIndex = 0;
  stopReadAlong();
}

function stopReadAlong() {
  stopWordTracker();
  if (!playing) {
    setReadAlongUI(false);
    return;
  }
  playing = false;
  try {
    player.pause();
  } catch {
    /* ignore */
  }
  if (endedResolver) {
    endedResolver("stopped");
    endedResolver = null;
  }
  setReadAlongUI(false);
}

function setReadAlongUI(on) {
  readAlongBtn.textContent = on ? "⏹ Ferma" : "▶ Leggi con evidenziazione";
  readAlongBtn.classList.toggle("playing", on);
}

readAlongBtn.addEventListener("click", () => {
  if (playing) stopReadAlong();
  else startReadAlong(currentIndex);
});

// --- Read everything in one shot ---
speakBtn.addEventListener("click", async () => {
  if (!fullText.trim()) {
    setStatus("Non c'è testo da leggere.", true);
    return;
  }
  stopReadAlong();
  speakBtn.disabled = true;
  setStatus("Generazione dell'audio… (la prima volta scarica il modello)");
  try {
    const url = await synth(fullText);
    if (currentAudioUrl) URL.revokeObjectURL(currentAudioUrl);
    currentAudioUrl = url;
    player.src = url;
    player.hidden = false;
    player.play();
    setStatus("");
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    speakBtn.disabled = false;
  }
});

// --- Download a single audio file of the whole document ---
downloadBtn.addEventListener("click", async () => {
  if (!fullText.trim()) {
    setStatus("Non c'è testo da scaricare.", true);
    return;
  }
  stopReadAlong();
  const fmt = formatSel.value;
  downloadBtn.disabled = true;
  setStatus(
    `Generazione del file ${fmt.toUpperCase()}… ` +
      "(per documenti lunghi può richiedere minuti)"
  );
  try {
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: fullText,
        voice: voiceSelect.value || undefined,
        speed: Number(speed.value),
        format: fmt,
      }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Esportazione non riuscita.");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `lettura.${fmt}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setStatus("File scaricato.");
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    downloadBtn.disabled = false;
  }
});

activeSentences = textSentences;
activeHighlight = highlightText;
loadVoices();
