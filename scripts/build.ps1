# build.ps1 — Full VanillaDB production build (Windows)
#
# 1. Builds the Python sidecar via PyInstaller
# 2. Builds the Tauri app (which bundles the frontend + sidecar)
#
# Usage (from repo root):
#   .\scripts\build.ps1
#
# Output: src-tauri\target\release\bundle\

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== VanillaDB Production Build ===" -ForegroundColor Cyan

# Step 1: Build sidecar
Write-Host ""
Write-Host "[1/3] Building Python sidecar..." -ForegroundColor Yellow
& "$RepoRoot\scripts\build-sidecar.ps1"

# Step 2: Install JS deps
Write-Host ""
Write-Host "[2/3] Installing frontend dependencies..." -ForegroundColor Yellow
Set-Location $RepoRoot
npm ci --prefer-offline

# Step 3: Build Tauri
Write-Host ""
Write-Host "[3/3] Building Tauri app..." -ForegroundColor Yellow
npx tauri build

Write-Host ""
Write-Host "=== Build complete! ===" -ForegroundColor Green
Write-Host "Artifacts: src-tauri\target\release\bundle\" -ForegroundColor Green
