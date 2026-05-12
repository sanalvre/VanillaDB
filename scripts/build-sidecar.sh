#!/usr/bin/env bash
# build-sidecar.sh — Build the Python sidecar for macOS or Linux
#
# Produces:
#   macOS ARM:  src-tauri/binaries/vanilla-sidecar-aarch64-apple-darwin
#   macOS x64:  src-tauri/binaries/vanilla-sidecar-x86_64-apple-darwin
#   Linux x64:  src-tauri/binaries/vanilla-sidecar-x86_64-unknown-linux-gnu
#
# Prerequisites: Python 3.10+, pyinstaller
#   pip install pyinstaller
#
# Usage (from repo root):
#   bash scripts/build-sidecar.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIDECAR_DIR="$REPO_ROOT/sidecar"
BINARIES_DIR="$REPO_ROOT/src-tauri/binaries"
DIST_DIR="$SIDECAR_DIR/dist"

echo "Building Vanilla sidecar..."

# Detect target triple
OS="$(uname -s)"
ARCH="$(uname -m)"

if [[ "$OS" == "Darwin" ]]; then
    if [[ "$ARCH" == "arm64" ]]; then
        TRIPLE="aarch64-apple-darwin"
    else
        TRIPLE="x86_64-apple-darwin"
    fi
elif [[ "$OS" == "Linux" ]]; then
    TRIPLE="x86_64-unknown-linux-gnu"
else
    echo "Unsupported OS: $OS"
    exit 1
fi

echo "Target triple: $TRIPLE"

# Ensure pyinstaller
if ! command -v pyinstaller &>/dev/null; then
    echo "Installing pyinstaller..."
    pip install pyinstaller --quiet
fi

# Install sidecar deps
echo "Installing Python dependencies..."
pip install -r "$SIDECAR_DIR/requirements-build.txt" --quiet

# Run PyInstaller
echo "Running PyInstaller..."
cd "$SIDECAR_DIR"
pyinstaller vanilla-sidecar.spec --noconfirm --clean

# Copy binary with platform triple appended
mkdir -p "$BINARIES_DIR"
cp "$DIST_DIR/vanilla-sidecar" "$BINARIES_DIR/vanilla-sidecar-$TRIPLE"
chmod +x "$BINARIES_DIR/vanilla-sidecar-$TRIPLE"

echo "Sidecar binary written to: $BINARIES_DIR/vanilla-sidecar-$TRIPLE"
cd "$REPO_ROOT"
