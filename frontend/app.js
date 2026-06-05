"use strict";

const $ = (id) => document.getElementById(id);
const fileInput = $("file");
const fileDrop = $("filedrop");
const fileLabel = $("filelabel");
const extractBtn = $("extractBtn");
const resultCard = $("resultCard");
const meta = $("meta");
const textArea = $("text");
const voiceSelect = $("voice");
const speed = $("speed");
const speedVal = $("speedval");
const speakBtn = $("speakBtn");
const player = $("player");
const statusEl = $("status");

let selectedFile = null;

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
  extractBtn.disabled = true;
  setStatus("Estrazione del testo in corso…");
  try {
    const form = new FormData();
    form.append("file", selectedFile);
    const res = await fetch("/api/extract", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Estrazione non riuscita.");
    textArea.value = data.text;
    meta.textContent =
      `${data.page_count} pagine · ${data.char_count} caratteri` +
      (data.ocr_used ? ` · OCR usato sulle pagine ${data.ocr_pages.join(", ")}` : "");
    resultCard.hidden = false;
    setStatus("");
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    extractBtn.disabled = false;
  }
});

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
    /* health/voices endpoint unavailable; leave selector empty */
  }
}

speed.addEventListener("input", () => {
  speedVal.textContent = `${Number(speed.value).toFixed(1)}×`;
});

// --- Speak ---
speakBtn.addEventListener("click", async () => {
  const text = textArea.value.trim();
  if (!text) {
    setStatus("Non c'è testo da leggere.", true);
    return;
  }
  speakBtn.disabled = true;
  setStatus("Generazione dell'audio in corso… (la prima volta scarica il modello)");
  try {
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
    const blob = await res.blob();
    player.src = URL.createObjectURL(blob);
    player.hidden = false;
    player.play();
    setStatus("");
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    speakBtn.disabled = false;
  }
});

loadVoices();
