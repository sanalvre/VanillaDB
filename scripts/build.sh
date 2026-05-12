#!/usr/bin/env bash
# build.sh — Full VanillaDB production build (macOS / Linux)
#
# 1. Builds the Python sidecar via PyInstaller
# 2. Builds the Tauri app (which bundles the frontend + sidecar)
#
# Usage (from repo root):
#   bash scripts/build.sh
#
# Output: src-tauri/target/release/bundle/

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== VanillaDB Production Build ==="

# Step 1: Build the sidecar
echo ""
echo "[1/3] Building Python sidecar..."
bash "$REPO_ROOT/scripts/build-sidecar.sh"

# Step 2: Install JS deps
echo ""
echo "[2/3] Installing frontend dependencies..."
cd "$REPO_ROOT"
npm ci --prefer-offline

# Step 3: Build Tauri app
echo ""
echo "[3/3] Building Tauri app..."
npx tauri build

echo ""
echo "=== Build complete! ==="
echo "Artifacts: src-tauri/target/release/bundle/"
