@echo off
rem ============================================================
rem  Lettura - installazione e avvio con un solo doppio clic.
rem  NON servono diritti di amministratore.
rem  Prepara tutto la prima volta, poi avvia il programma.
rem ============================================================
setlocal
cd /d "%~dp0"
title Lettura

echo ============================================
echo               L E T T U R A
echo    Legge ad alta voce PDF, EPUB e HTML
echo ============================================
echo.

rem --- 1. Cerca Python sul computer ---
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo  Python non e' ancora installato su questo computer.
  echo.
  echo  COSA FARE:
  echo    1^) Apri questo indirizzo:  https://www.python.org/downloads/
  echo    2^) Scarica e avvia l'installazione di Python.
  echo    3^) IMPORTANTE: all'inizio spunta la casella
  echo       "Add python.exe to PATH", poi premi Install.
  echo    4^) Quando ha finito, fai di nuovo doppio clic su questo file.
  echo.
  pause
  exit /b 1
)

rem --- 2. Prepara l'ambiente (solo la prima volta) ---
if not exist ".venv\Scripts\python.exe" (
  echo Preparazione dell'ambiente in corso... ^(solo la prima volta^)
  %PY% -m venv .venv
  if errorlevel 1 (
    echo  Si e' verificato un errore nella preparazione. Riprova.
    pause
    exit /b 1
  )
)

rem --- 3. Installa i componenti necessari ---
echo Controllo dei componenti... ^(la prima volta puo' richiedere qualche minuto^)
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
  echo.
  echo  Errore durante l'installazione dei componenti.
  echo  Controlla la connessione a internet e riprova.
  pause
  exit /b 1
)

rem --- 4. Apri il browser tra qualche secondo, poi avvia ---
echo.
echo  Avvio di Lettura...
echo  Il browser si aprira' da solo tra pochi secondi su:
echo      http://127.0.0.1:8000
echo.
echo  Per FERMARE il programma: chiudi questa finestra nera.
echo.
start "Lettura" /min cmd /c "timeout /t 6 >nul && start http://127.0.0.1:8000"
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

echo.
echo  Lettura si e' chiuso. Puoi chiudere questa finestra.
pause
