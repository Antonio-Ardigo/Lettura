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
const progressEl = $("progress");
const progressBar = $("progressBar");
const progressLabel = $("progressLabel");
const modelNotice = $("modelNotice");

let selectedFile = null;
let fullText = "";
let textSentences = []; // strings, from /api/extract (placeholders for pending pages)
let sentenceMeta = []; // [{page, placeholder, failed}] aligned with textSentences
let layoutSentences = []; // [{text, boxes:[...]}], from /api/layout
let pdfDoc = null;

let docId = null;
let pages = []; // [{page, status, sentences:[str]}] — the assembled document
let pendingPages = new Set(); // 1-indexed pages awaiting on-demand OCR
let ocrAvailable = false;

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

// --- Reusable progress bar (OCR, audio export, model download) ---
function showProgress(label, indeterminate = false) {
  progressEl.hidden = false;
  progressEl.classList.toggle("indeterminate", indeterminate);
  progressLabel.textContent = label || "";
  if (indeterminate) {
    progressBar.style.width = "";
    progressEl.removeAttribute("aria-valuenow");
  }
}

function setProgress(pct, label) {
  progressEl.hidden = false;
  progressEl.classList.remove("indeterminate");
  const clamped = Math.max(0, Math.min(100, pct));
  progressBar.style.width = `${clamped}%`;
  progressEl.setAttribute("aria-valuenow", String(Math.round(clamped)));
  if (label != null) progressLabel.textContent = label;
}

function hideProgress() {
  progressEl.hidden = true;
  progressEl.classList.remove("indeterminate");
  progressBar.style.width = "0%";
  progressLabel.textContent = "";
}

// --- Model readiness (so the user knows the first synthesis is being prepared) ---
async function refreshModelState() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    if (data.model_ready) {
      modelNotice.hidden = true;
      return;
    }
    if (data.model_state === "failed") {
      modelNotice.textContent =
        "Modello vocale non disponibile — verifica la connessione per il primo " +
        "avvio (scarica ~90 MB una sola volta).";
      modelNotice.hidden = false;
      return;
    }
    modelNotice.textContent =
      "Preparazione del modello vocale… (primo avvio, scarica ~90 MB una sola volta)";
    modelNotice.hidden = false;
    setTimeout(refreshModelState, 2500);
  } catch {
    /* health unavailable; ignore */
  }
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

// --- Extract (fast: text layer now, scanned pages OCR'd lazily while reading) ---
extractBtn.addEventListener("click", async () => {
  if (!selectedFile) return;
  stopReadAlong();
  extractBtn.disabled = true;
  extractBtn.classList.add("loading");
  setStatus("Estrazione del testo in corso…");
  try {
    const form = new FormData();
    form.append("file", selectedFile);
    const res = await fetch("/api/extract", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Estrazione non riuscita.");
    docId = data.doc_id;
    ocrAvailable = data.ocr_available;
    pages = (data.pages || []).map((p) => ({
      page: p.page,
      status: p.status,
      sentences: p.sentences || [],
    }));
    pendingPages = new Set(data.pending_ocr_pages || []);
    pdfDoc = null;
    layoutSentences = [];
    docview.innerHTML = "";
    currentIndex = 0;
    rebuildDocument();
    setMode("text", { force: true });
    const realCount = pages.reduce((n, p) => n + p.sentences.length, 0);
    meta.textContent =
      `${data.page_count} pagine · ${realCount} frasi · ${data.char_count} caratteri` +
      (pendingPages.size
        ? ` · ${pendingPages.size} pagine scansionate (OCR alla lettura)`
        : "");
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
    extractBtn.classList.remove("loading");
  }
});

// --- Assemble the flat sentence list (with placeholders for pending pages) ---
function rebuildDocument() {
  textSentences = [];
  sentenceMeta = [];
  const realParts = [];
  for (const pg of pages) {
    if (pg.status === "needs_ocr") {
      textSentences.push(
        `Pagina ${pg.page} — testo scansionato, verrà riconosciuto durante la lettura…`
      );
      sentenceMeta.push({ page: pg.page, placeholder: true, failed: false });
    } else if (pg.status === "ocr_failed") {
      textSentences.push(`Pagina ${pg.page}: testo non riconosciuto.`);
      sentenceMeta.push({ page: pg.page, placeholder: false, failed: true });
    } else {
      for (const s of pg.sentences) {
        textSentences.push(s);
        sentenceMeta.push({ page: pg.page, placeholder: false, failed: false });
      }
      if (pg.sentences.length) realParts.push(pg.sentences.join(" "));
    }
  }
  fullText = realParts.join("\n\n");
  if (mode === "text") activeSentences = textSentences;
  renderReader();
}

function firstIndexForPage(page) {
  return sentenceMeta.findIndex(
    (m) => m.page === page && !m.placeholder && !m.failed
  );
}

function firstReadableFrom(start) {
  for (let i = start; i < sentenceMeta.length; i++) {
    if (!sentenceMeta[i].failed) return i;
  }
  return -1;
}

// --- Text view (sentences split into word spans for word-level highlight) ---
function renderReader() {
  reader.innerHTML = "";
  textSentences.forEach((sentence, i) => {
    const meta = sentenceMeta[i] || {};
    const span = document.createElement("span");
    span.dataset.index = String(i);
    if (meta.placeholder) {
      span.className = "sentence pending";
      span.textContent = sentence;
      span.addEventListener("click", () => ensurePageOcr(meta.page));
      reader.appendChild(span);
      return;
    }
    if (meta.failed) {
      span.className = "sentence ocr-failed";
      span.textContent = sentence;
      reader.appendChild(span);
      return;
    }
    span.className = "sentence";
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

// --- On-demand OCR: fetch one scanned page and splice it into the document ---
async function ensurePageOcr(page, { rebuild = true } = {}) {
  if (!pendingPages.has(page)) return;
  const pg = pages.find((p) => p.page === page);
  try {
    const res = await fetch("/api/ocr_page", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_id: docId, page }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Riconoscimento non riuscito.");
    if (pg) {
      if (data.status === "ready") {
        pg.status = "ready";
        pg.sentences = data.sentences || [];
      } else if (data.status === "empty") {
        // Page processed fine but had no readable text — not a failure.
        pg.status = "empty";
        pg.sentences = [];
      } else {
        pg.status = "ocr_failed";
        pg.sentences = [];
      }
    }
  } catch (err) {
    if (pg) {
      pg.status = "ocr_failed";
      pg.sentences = [];
    }
    setStatus(err.message, true);
  } finally {
    pendingPages.delete(page);
    if (rebuild) rebuildDocument();
  }
}

// OCR every still-pending page (needed before reading/exporting the whole doc).
async function ensureAllOcr(label) {
  const todo = [...pendingPages];
  if (!todo.length) return;
  let done = 0;
  setProgress(0, `${label} (pagina ${done}/${todo.length})…`);
  for (const page of todo) {
    await ensurePageOcr(page, { rebuild: false }); // one rebuild after the batch
    done += 1;
    setProgress((done / todo.length) * 100, `${label} (pagina ${done}/${todo.length})…`);
  }
  rebuildDocument();
  hideProgress();
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
  currentIndex = 0; // the two views index different sentence lists
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
  if (from == null || from < 0 || from >= activeSentences.length) {
    setReadAlongUI(false);
    return;
  }
  playing = true;
  setReadAlongUI(true);
  setStatus("Generazione dell'audio…");
  let i = from;
  for (; playing && i < activeSentences.length; i++) {
    // In the text view, OCR a scanned page just-in-time as we reach it.
    if (mode === "text") {
      const m = sentenceMeta[i];
      if (m && m.failed) continue; // unreadable page -> skip
      if (m && m.placeholder) {
        setStatus(`Riconoscimento del testo (OCR) — pagina ${m.page}…`);
        showProgress(`Riconoscimento del testo (OCR) — pagina ${m.page}…`, true);
        await ensurePageOcr(m.page);
        hideProgress();
        setStatus("");
        if (!playing) break;
        // Indices shifted after splicing; resume at this page's first sentence.
        const resume = firstIndexForPage(m.page);
        playing = false;
        setReadAlongUI(false);
        return startReadAlong(resume >= 0 ? resume : firstReadableFrom(i + 1));
      }
    }
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
  if (!fullText.trim() && pendingPages.size === 0) {
    setStatus("Non c'è testo da leggere.", true);
    return;
  }
  stopReadAlong();
  speakBtn.disabled = true;
  speakBtn.classList.add("loading");
  try {
    if (pendingPages.size) {
      await ensureAllOcr("Digitalizzazione delle pagine scansionate");
    }
    setStatus("Generazione dell'audio… (la prima volta scarica il modello)");
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
    speakBtn.classList.remove("loading");
  }
});

// --- Download a single audio file of the whole document (with progress) ---
downloadBtn.addEventListener("click", async () => {
  if (!fullText.trim() && pendingPages.size === 0) {
    setStatus("Non c'è testo da scaricare.", true);
    return;
  }
  stopReadAlong();
  const fmt = formatSel.value;
  downloadBtn.disabled = true;
  downloadBtn.classList.add("loading");
  try {
    if (pendingPages.size) {
      await ensureAllOcr("Digitalizzazione delle pagine scansionate");
    }
    setStatus("");
    showProgress("Avvio della generazione…", true);
    const job = await startExportJob(fmt);
    await streamExportProgress(job, fmt);
  } catch (err) {
    setStatus(err.message, true);
    hideProgress();
  } finally {
    downloadBtn.disabled = false;
    downloadBtn.classList.remove("loading");
  }
});

async function startExportJob(fmt) {
  const res = await fetch("/api/export_job", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: fullText,
      voice: voiceSelect.value || undefined,
      speed: Number(speed.value),
      format: fmt,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Esportazione non riuscita.");
  return data.job_id;
}

function streamExportProgress(jobId, fmt) {
  return new Promise((resolve, reject) => {
    const es = new EventSource(`/api/export_job/${jobId}/events`);
    es.onmessage = (e) => {
      let evt;
      try {
        evt = JSON.parse(e.data);
      } catch {
        return;
      }
      if (evt.phase === "synth") {
        const pct = evt.total ? (evt.done / evt.total) * 100 : 0;
        setProgress(pct, `Generazione audio ${Math.round(pct)}%`);
      } else if (evt.phase === "encode") {
        showProgress(`Conversione in ${fmt.toUpperCase()}…`, true);
      } else if (evt.phase === "done") {
        es.close();
        downloadExportResult(jobId, fmt).then(resolve, reject);
      } else if (evt.phase === "error") {
        es.close();
        reject(new Error(evt.detail || "Esportazione non riuscita."));
      }
    };
    es.onerror = () => {
      // EventSource auto-reconnects on transient drops (readyState CONNECTING);
      // only treat a fully-closed connection as a hard failure.
      if (es.readyState === EventSource.CLOSED) {
        reject(new Error("Connessione interrotta durante l'esportazione."));
      }
    };
  });
}

async function downloadExportResult(jobId, fmt) {
  const res = await fetch(`/api/export_job/${jobId}/result`);
  if (!res.ok) throw new Error("File non disponibile.");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `lettura.${fmt}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  hideProgress();
  setStatus("File scaricato.");
}

activeSentences = textSentences;
activeHighlight = highlightText;
loadVoices();
refreshModelState();
