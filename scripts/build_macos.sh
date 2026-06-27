#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

echo "Building MidiCleaner.app with PyInstaller..."
"$PYTHON_BIN" -m PyInstaller --noconfirm --clean "midi_cleaner_app.spec"

echo
echo "Build complete:"
echo "  $PROJECT_ROOT/dist/MidiCleaner.app"
echo
echo "If Gatekeeper blocks the unsigned app on another Mac:"
echo "  xattr -dr com.apple.quarantine \"$PROJECT_ROOT/dist/MidiCleaner.app\""

