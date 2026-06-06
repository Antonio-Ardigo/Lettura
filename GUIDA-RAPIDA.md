# Lettura — Guida rapida (per tutti)

Lettura legge ad alta voce i tuoi documenti **PDF, EPUB e HTML** in italiano,
direttamente sul tuo computer. Funziona **senza internet** dopo la prima volta e
**senza account**.

## Installazione su Windows — 3 passi

### Passo 1 — Installa Python (una volta sola)
1. Vai su **https://www.python.org/downloads/**
2. Clicca il pulsante giallo **“Download Python”** e apri il file scaricato.
3. **MOLTO IMPORTANTE:** nella prima schermata metti la spunta su
   **“Add python.exe to PATH”**, poi clicca **Install Now**.
4. Attendi la fine e chiudi.

> Se Python è già installato, salta questo passo.

### Passo 2 — Scarica Lettura
1. Vai sulla pagina del progetto su GitHub.
2. Clicca il pulsante verde **“Code”** → **“Download ZIP”**.
3. Apri la cartella **Download**, fai clic destro sul file ZIP → **“Estrai
   tutto”** e scegli una posizione facile (es. il **Desktop**).

### Passo 3 — Avvia
1. Entra nella cartella estratta (`Lettura`).
2. Fai **doppio clic** su **`Avvia-Lettura.bat`**.
3. La prima volta prepara tutto da solo (qualche minuto: scarica i componenti).
   Le volte successive parte in pochi secondi.
4. Il **browser si apre da solo** su `http://127.0.0.1:8000`.

> ⚠️ Se Windows mostra un avviso blu “Windows ha protetto il PC”, clicca
> **“Ulteriori informazioni”** → **“Esegui comunque”** (succede perché il file
> non è firmato; è sicuro).

## Come si usa
1. **Trascina** un file PDF/EPUB/HTML nel riquadro (o clicca per sceglierlo).
2. Clicca **“Estrai testo”**.
3. Clicca **“▶ Leggi con evidenziazione”** — oppure clicca una frase per iniziare
   da lì. La frase letta viene evidenziata.
4. **“↺ Reimposta”** ferma tutto e torna all’inizio.
5. **“⬇ Scarica audio”** salva l’intero documento come file audio (WAV/MP3/M4B).

> La **prima lettura** scarica la voce (~90 MB, una volta sola), poi tutto
> funziona offline.

## Per fermare il programma
Chiudi la **finestra nera** (il “motore”) che si è aperta. Fatto.

## Problemi comuni
- **“Python non è installato”** → hai dimenticato la spunta *“Add python.exe to
  PATH”* nel Passo 1. Reinstalla Python mettendo la spunta, poi riprova.
- **La pagina non si apre subito** → aspetta qualche secondo e **aggiorna** la
  pagina del browser (tasto F5).
- **Errore “porta … 10048 / address already in use”** → Lettura è già aperto in
  un’altra finestra. Chiudi le finestre nere di Lettura e riavvia.
- **Una voce robotica o accenti strani su un PDF scansionato** → quel PDF è
  un’immagine; per leggerlo serve l’OCR (Tesseract), opzionale. I PDF/EPUB/HTML
  normali (con testo selezionabile) non ne hanno bisogno.

## Su Mac / Linux
Apri il Terminale nella cartella ed esegui:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app
```
Poi apri `http://127.0.0.1:8000`.
