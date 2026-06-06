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
const resetBtn = $("resetBtn");
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

let playing = false; // UI state only; loop control is gated on playToken
let currentIndex = 0;
let currentAudioUrl = null;
let endedResolver = null;
let rafId = null;

// Read-along engine: a monotonically increasing token identifies the live loop
// (so a stale loop can never clobber a newer one — the click-to-read race fix),
// plus a small prefetch cache that synthesizes the next segment ahead of time.
let playToken = 0;
const prefetch = new Map(); // startSentenceIndex -> Promise<{url, words, seg}>
const SEGMENT_WORDS = 12; // group short sentences up to ~N words per audio clip

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
    // Start reading from this sentence. startReadAlong bumps the play-token, so
    // any loop already running is superseded cleanly — no race, no stuck audio.
    span.addEventListener("click", () => startReadAlong(i));
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

function playSegment(url, myToken) {
  return new Promise((resolve) => {
    endedResolver = resolve;
    player.src = url;
    player.hidden = false;
    player.onended = () => resolve("ended");
    // A superseded loop (token changed) is torn down by stopReadAlong(), which
    // pauses the player and resolves this promise with "stopped".
    player.play().catch(() => resolve("ended"));
    if (myToken !== playToken) resolve("stopped");
  });
}

// --- Word-level highlight, driven by the audio clock ---
// Works across a *segment* (one or more grouped sentences): the word elements
// are collected in reading order and aligned 1:1 with the per-word timings.
function startWordTracker(wordEls, words) {
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

// --- Segmentation: group consecutive readable sentences up to ~N words so the
// narration flows naturally and starts as soon as one segment is ready. ---
function wordCount(s) {
  return s.split(/\s+/).filter(Boolean).length;
}

// Describe what to do starting at sentence `start`:
//   {kind:"seg", indices, text, next} — a playable segment
//   {kind:"ocr", page}                — a scanned page to OCR first
//   {kind:"skip", next}               — an unreadable sentence to skip
//   null                              — nothing left
function segmentAt(start) {
  const n = activeSentences.length;
  if (start >= n) return null;
  if (mode === "text") {
    const m = sentenceMeta[start] || {};
    if (m.failed) return { kind: "skip", next: start + 1 };
    if (m.placeholder) return { kind: "ocr", page: m.page };
  }
  const indices = [start];
  let words = wordCount(activeSentences[start]);
  let j = start + 1;
  if (mode === "text") {
    // Group only in the text view; the doc view highlights one sentence's boxes
    // at a time, so it stays one-sentence-per-segment.
    while (j < n && words < SEGMENT_WORDS) {
      const m = sentenceMeta[j] || {};
      if (m.placeholder || m.failed) break;
      indices.push(j);
      words += wordCount(activeSentences[j]);
      j += 1;
    }
  }
  return {
    kind: "seg",
    indices,
    text: indices.map((k) => activeSentences[k]).join(" "),
    next: j,
  };
}

// --- Prefetch pipeline: synthesize the next segment while the current plays ---
function ensureClip(startIndex) {
  if (prefetch.has(startIndex)) return prefetch.get(startIndex);
  const seg = segmentAt(startIndex);
  if (!seg || seg.kind !== "seg") return null;
  const p = fetchClip(seg.text, mode === "text").then((clip) => ({
    ...clip,
    seg,
  }));
  prefetch.set(startIndex, p);
  return p;
}

function clearPrefetch() {
  for (const p of prefetch.values()) {
    Promise.resolve(p)
      .then((clip) => {
        if (clip && clip.url) URL.revokeObjectURL(clip.url);
      })
      .catch(() => {});
  }
  prefetch.clear();
}

// Highlight every sentence in a segment and wire the word tracker across them.
function highlightSegment(seg, words) {
  if (mode !== "text") {
    activeHighlight(seg.indices[0]); // doc view: bounding-box highlight
    return;
  }
  reader
    .querySelectorAll(".sentence.active")
    .forEach((el) => el.classList.remove("active"));
  const wordEls = [];
  seg.indices.forEach((idx, k) => {
    const el = reader.querySelector(`.sentence[data-index="${idx}"]`);
    if (!el) return;
    el.classList.add("active");
    if (k === 0) el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.querySelectorAll(".word").forEach((w) => wordEls.push(w));
  });
  if (words && words.length) startWordTracker(wordEls, words);
}

// --- Read-along: token-gated loop with prefetch + a preparation indicator ---
async function startReadAlong(from) {
  const myToken = ++playToken; // supersede any loop already running
  stopWordTracker();
  try {
    player.pause();
  } catch {
    /* ignore */
  }
  clearPrefetch();
  let i = firstReadableFrom(from == null ? 0 : from);
  if (i < 0 || i >= activeSentences.length) {
    setReadAlongUI(false);
    return;
  }
  setReadAlongUI(true);

  while (myToken === playToken && i < activeSentences.length) {
    const seg = segmentAt(i);
    if (!seg) break;
    if (seg.kind === "skip") {
      i = seg.next;
      continue;
    }
    if (seg.kind === "ocr") {
      setStatus(`Riconoscimento del testo (OCR) — pagina ${seg.page}…`);
      showProgress(`Riconoscimento del testo (OCR) — pagina ${seg.page}…`, true);
      await ensurePageOcr(seg.page); // rebuilds the document (indices shift)
      if (myToken !== playToken) return;
      hideProgress();
      setStatus("");
      clearPrefetch();
      const resume = firstIndexForPage(seg.page);
      i = resume >= 0 ? resume : firstReadableFrom(i + 1);
      if (i < 0) break;
      continue;
    }

    // Show the prep indicator only if synthesis isn't ready almost instantly
    // (so a prefetched segment plays gap-free, with no flicker).
    const prepTimer = setTimeout(
      () => showProgress("Preparazione dell'audio…", true),
      120
    );
    let clip;
    try {
      clip = await ensureClip(i);
    } catch (err) {
      clearTimeout(prepTimer);
      if (myToken === playToken) setStatus(err.message, true);
      break;
    }
    clearTimeout(prepTimer);
    if (myToken !== playToken) {
      if (clip) URL.revokeObjectURL(clip.url);
      return;
    }
    hideProgress();
    setStatus("");
    prefetch.delete(i); // consumed; ownership moves to currentAudioUrl

    // Kick off synthesis of the NEXT segment while this one plays.
    if (seg.next < activeSentences.length) ensureClip(seg.next);

    currentIndex = i;
    if (currentAudioUrl) URL.revokeObjectURL(currentAudioUrl);
    currentAudioUrl = clip.url;
    highlightSegment(seg, clip.words);
    const outcome = await playSegment(clip.url, myToken);
    stopWordTracker();
    if (myToken !== playToken || outcome === "stopped") return;
    i = seg.next;
  }
  if (myToken !== playToken) return;
  currentIndex = 0;
  hideProgress();
  setReadAlongUI(false);
}

function stopReadAlong() {
  playToken += 1; // invalidate any in-flight loop (race-proof supersede)
  stopWordTracker();
  try {
    player.pause();
  } catch {
    /* ignore */
  }
  if (endedResolver) {
    endedResolver("stopped");
    endedResolver = null;
  }
  clearPrefetch();
  setReadAlongUI(false);
}

// Stop everything and rewind to the top, keeping the document loaded.
function resetReadAlong() {
  stopReadAlong();
  currentIndex = 0;
  reader
    .querySelectorAll(".sentence.active")
    .forEach((el) => el.classList.remove("active"));
  reader
    .querySelectorAll(".word.wordactive")
    .forEach((el) => el.classList.remove("wordactive"));
  docview.querySelectorAll(".hl").forEach((el) => el.remove());
  if (currentAudioUrl) {
    URL.revokeObjectURL(currentAudioUrl);
    currentAudioUrl = null;
  }
  try {
    player.pause();
  } catch {
    /* ignore */
  }
  player.removeAttribute("src");
  player.hidden = true;
  reader.scrollTop = 0;
  docview.scrollTop = 0;
  hideProgress();
  setStatus("");
}

function setReadAlongUI(on) {
  playing = on;
  readAlongBtn.textContent = on ? "⏹ Ferma" : "▶ Leggi con evidenziazione";
  readAlongBtn.classList.toggle("playing", on);
}

readAlongBtn.addEventListener("click", () => {
  if (playing) stopReadAlong();
  else startReadAlong(currentIndex);
});

resetBtn.addEventListener("click", resetReadAlong);

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
