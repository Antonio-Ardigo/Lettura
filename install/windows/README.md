# Install Lettura on Windows

Sets up Lettura under `C:\Program Files\Lettura` with a Start-Menu shortcut.

> Built and tested from a Linux dev environment — the Python app is
> cross-platform, but the Windows install flow itself hasn't been run on a
> Windows machine. If something trips, the notes at the bottom cover the usual
> suspects.

## Prerequisites

- **Windows 10/11**
- **Python 3.10+** — install from <https://www.python.org/downloads/> and tick
  **"Add python.exe to PATH"**.
- The app code — clone the repository (or download it as a ZIP and extract).

## Install

1. Open **PowerShell as Administrator** (right-click → *Run as administrator*).
2. `cd` into your clone of the repository, e.g.:
   ```powershell
   cd $HOME\Lettura
   ```
3. Allow the script to run for this session, then run it:
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\install\windows\Install-Lettura.ps1
   ```

The installer copies the app to `C:\Program Files\Lettura`, creates a virtual
environment, installs dependencies, pre-downloads the Kokoro voice model
(~90 MB, so the first run is offline), and adds a **Lettura** Start-Menu
shortcut.

Custom location or skip the model download:

```powershell
.\install\windows\Install-Lettura.ps1 -InstallDir "D:\Apps\Lettura" -SkipModel
```

## Run

- Start **Lettura** from the Start Menu, or run `C:\Program Files\Lettura\Lettura.bat`.
- A console opens (the server) and your browser opens **http://127.0.0.1:8000**.
- Close the console window to stop it.

## Optional / troubleshooting

- **Scanned PDFs (OCR)** — install Tesseract with the Italian language pack
  (UB-Mannheim build: <https://github.com/UB-Mannheim/tesseract/wiki>) and make
  sure `tesseract.exe` is on PATH. Digital PDFs don't need it.
- **MP3 / M4B export** — works out of the box (ffmpeg ships via `imageio-ffmpeg`).
- **An error mentioning `espeak`** — install espeak-ng for Windows from
  <https://github.com/espeak-ng/espeak-ng/releases> (the `.msi`), then relaunch.
- **"running scripts is disabled"** — you skipped the `Set-ExecutionPolicy`
  line in step 3; run it and retry.
