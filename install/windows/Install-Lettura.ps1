<#
.SYNOPSIS
    Install Lettura on Windows under C:\Program Files\Lettura.

.DESCRIPTION
    Copies this repository into the install directory, creates a Python
    virtual environment, installs the dependencies, optionally pre-downloads
    the Kokoro voice model, and adds a Start-Menu shortcut.

    Run from an elevated (Administrator) PowerShell, from inside a clone of the
    repository:

        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
        .\install\windows\Install-Lettura.ps1

.PARAMETER InstallDir
    Target directory. Default: C:\Program Files\Lettura

.PARAMETER SkipModel
    Skip pre-downloading the voice model (it will download on first run).
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "C:\Program Files\Lettura",
    [switch]$SkipModel
)

$ErrorActionPreference = "Stop"

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]$id
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Please run this script in an Administrator PowerShell (it writes to Program Files)."
    }
}

function Get-PythonLauncher {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return [pscustomobject]@{ Exe = "py"; Base = @("-3") }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return [pscustomobject]@{ Exe = "python"; Base = @() }
    }
    throw "Python 3.10+ was not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH')."
}

function Invoke-Checked {
    param([string]$Exe, [string[]]$Args)
    & $Exe @Args
    if ($LASTEXITCODE -ne 0) { throw "$Exe $($Args -join ' ') failed (exit $LASTEXITCODE)." }
}

Assert-Admin

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Get-PythonLauncher
Write-Host "Installing Lettura"
Write-Host "  source : $repoRoot"
Write-Host "  target : $InstallDir"
Write-Host "  python : $($python.Exe) $($python.Base -join ' ')"

# 1. Copy the application into the install directory (skip dev/cache dirs).
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$roboArgs = @(
    $repoRoot, $InstallDir, "/E",
    "/XD", ".git", ".venv", "__pycache__", "models",
    "/XF", "*.pyc",
    "/NFL", "/NDL", "/NJH", "/NJS", "/NP"
)
& robocopy @roboArgs | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed (exit $LASTEXITCODE)." }

# 2. Create the virtual environment.
$venv = Join-Path $InstallDir ".venv"
$venvPy = Join-Path $venv "Scripts\python.exe"
Write-Host "Creating virtual environment..."
Invoke-Checked $python.Exe ($python.Base + @("-m", "venv", $venv))

# 3. Install dependencies.
Write-Host "Installing dependencies (this can take a few minutes)..."
Invoke-Checked $venvPy @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")
Invoke-Checked $venvPy @("-m", "pip", "install", "-r", (Join-Path $InstallDir "requirements.txt"))

# 4. Pre-download the voice model so the first run is offline (optional).
if (-not $SkipModel) {
    $models = Join-Path $InstallDir "models"
    New-Item -ItemType Directory -Force -Path $models | Out-Null
    $base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
    foreach ($file in @("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")) {
        $dest = Join-Path $models $file
        if (-not (Test-Path $dest)) {
            Write-Host "Downloading $file ..."
            Invoke-WebRequest -Uri "$base/$file" -OutFile $dest
        }
    }
}

# 5. Launcher + Start-Menu shortcut.
Copy-Item (Join-Path $InstallDir "install\windows\Lettura.bat") (Join-Path $InstallDir "Lettura.bat") -Force
$startMenu = [Environment]::GetFolderPath("CommonStartMenu")
$shortcut = Join-Path $startMenu "Programs\Lettura.lnk"
$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut($shortcut)
$lnk.TargetPath = Join-Path $InstallDir "Lettura.bat"
$lnk.WorkingDirectory = $InstallDir
$lnk.Description = "Read Italian PDFs aloud"
$lnk.Save()

Write-Host ""
Write-Host "Lettura installed to $InstallDir" -ForegroundColor Green
Write-Host "Launch it from the Start Menu ('Lettura') or run:"
Write-Host "    `"$InstallDir\Lettura.bat`""
Write-Host "Then open http://127.0.0.1:8000"
