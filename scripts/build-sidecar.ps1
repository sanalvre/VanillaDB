# build-sidecar.ps1 — Build the Python sidecar for Windows
# Produces: src-tauri/binaries/vanilla-sidecar-x86_64-pc-windows-msvc.exe
#
# Prerequisites: Python 3.10+, pyinstaller installed
#   pip install pyinstaller
#
# Usage (from repo root):
#   .\scripts\build-sidecar.ps1

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$SidecarDir = Join-Path $RepoRoot "sidecar"
$BinariesDir = Join-Path $RepoRoot "src-tauri\binaries"
$DistDir = Join-Path $SidecarDir "dist"

Write-Host "Building Vanilla sidecar for Windows..." -ForegroundColor Cyan

# Ensure pyinstaller is available
if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host "Installing pyinstaller..." -ForegroundColor Yellow
    pip install pyinstaller --quiet
}

# Install sidecar deps (core only — agents/ingestion are optional at runtime)
Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
pip install -r "$SidecarDir\requirements-build.txt" --quiet

# Run PyInstaller
Write-Host "Running PyInstaller..." -ForegroundColor Yellow
Set-Location $SidecarDir
pyinstaller vanilla-sidecar.spec --noconfirm --clean

# Get target triple
$Triple = "x86_64-pc-windows-msvc"
$SrcBin = Join-Path $DistDir "vanilla-sidecar.exe"
$DstBin = Join-Path $BinariesDir "vanilla-sidecar-$Triple.exe"

# Copy to binaries/
New-Item -ItemType Directory -Force -Path $BinariesDir | Out-Null
Copy-Item -Path $SrcBin -Destination $DstBin -Force

Write-Host "Sidecar binary written to: $DstBin" -ForegroundColor Green
Set-Location $RepoRoot
