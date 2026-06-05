"use strict";

const $ = (id) => document.getElementById(id);
const fileInput = $("file");
const fileDrop = $("filedrop");
const fileLabel = $("filelabel");
const extractBtn = $("extractBtn");
const resultCard = $("resultCard");
const meta = $("meta");
const reader = $("reader");
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
let sentences = [];
let fullText = "";
let playing = false;
let currentIndex = 0;
let currentAudioUrl = null;
let endedResolver = null;

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
    sentences = data.sentences || [];
    renderReader();
    meta.textContent =
      `${data.page_count} pagine · ${sentences.length} frasi · ${data.char_count} caratteri` +
      (data.ocr_used ? ` · OCR sulle pagine ${data.ocr_pages.join(", ")}` : "");
    resultCard.hidden = false;
    setStatus("");
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    extractBtn.disabled = false;
  }
});

// --- Reader rendering ---
function renderReader() {
  reader.innerHTML = "";
  currentIndex = 0;
  sentences.forEach((sentence, i) => {
    const span = document.createElement("span");
    span.className = "sentence";
    span.textContent = sentence + " ";
    span.dataset.index = String(i);
    span.addEventListener("click", () => {
      if (playing) stopReadAlong();
      startReadAlong(i);
    });
    reader.appendChild(span);
  });
}

function highlight(i) {
  reader
    .querySelectorAll(".sentence.active")
    .forEach((el) => el.classList.remove("active"));
  const el = reader.querySelector(`.sentence[data-index="${i}"]`);
  if (el) {
    el.classList.add("active");
    el.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

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

function playUrl(url) {
  return new Promise((resolve) => {
    endedResolver = resolve;
    player.src = url;
    player.hidden = false;
    player.onended = () => resolve("ended");
    player.play();
  });
}

// --- Read-along (sentence by sentence with highlighting) ---
async function startReadAlong(from) {
  if (playing || sentences.length === 0) return;
  playing = true;
  setReadAlongUI(true);
  setStatus("Generazione dell'audio… (la prima volta scarica il modello)");
  let i = from;
  for (; playing && i < sentences.length; i++) {
    currentIndex = i;
    highlight(i);
    let url;
    try {
      url = await synth(sentences[i]);
    } catch (err) {
      setStatus(err.message, true);
      break;
    }
    if (!playing) {
      URL.revokeObjectURL(url);
      break;
    }
    setStatus("");
    if (currentAudioUrl) URL.revokeObjectURL(currentAudioUrl);
    currentAudioUrl = url;
    await playUrl(url); // resolves on "ended" or when stopped
  }
  if (i >= sentences.length) currentIndex = 0; // finished naturally
  stopReadAlong();
}

function stopReadAlong() {
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

loadVoices();

