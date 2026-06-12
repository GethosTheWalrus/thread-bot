#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required on macOS: https://brew.sh" >&2
  exit 1
fi

brew update
brew install python@3.12 pkg-config portaudio

BREW_PYTHON="$(brew --prefix python@3.12)/bin/python3"
"$BREW_PYTHON" -m pip install --upgrade pip wheel setuptools
"$BREW_PYTHON" -m pip install --no-deps reachy-mini==1.8.1 libusb_package==1.0.26.1
"$BREW_PYTHON" -m pip install -r "$ROOT_DIR/backend/requirements-reachy.txt"

echo
echo "Done. Use this python when running the Reachy worker/bridge:"
echo "$(brew --prefix python@3.12)/bin/python3"
