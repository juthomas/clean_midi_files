#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

APP_NAME="MidiCleaner"
APP_BUNDLE="$PROJECT_ROOT/dist/${APP_NAME}.app"
EXECUTABLE_PATH="$APP_BUNDLE/Contents/MacOS/$APP_NAME"
PYTHON_LINK="$APP_BUNDLE/Contents/Frameworks/Python3"
PYTHON_FRAMEWORK_GLOB="$APP_BUNDLE/Contents/Frameworks/Python3.framework/Versions/"*
RELEASE_DIR="$PROJECT_ROOT/release"
DMG_NAME="${APP_NAME}-macos.dmg"
DMG_PATH="$RELEASE_DIR/$DMG_NAME"
VOLUME_NAME="${APP_NAME} Installer"

SKIP_BUILD=0
if [[ "${1:-}" == "--skip-build" ]]; then
  SKIP_BUILD=1
fi

if [[ "$SKIP_BUILD" -eq 0 ]]; then
  echo "Building ${APP_NAME}.app with PyInstaller..."
  "$PROJECT_ROOT/scripts/build_macos.sh"
else
  echo "Skipping build step (--skip-build)."
fi

echo "Running bundle integrity checks..."

if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "ERROR: Missing app bundle: $APP_BUNDLE" >&2
  exit 1
fi

if [[ ! -x "$EXECUTABLE_PATH" ]]; then
  echo "ERROR: Missing executable: $EXECUTABLE_PATH" >&2
  exit 1
fi

if [[ ! -e "$PYTHON_LINK" ]]; then
  echo "ERROR: Missing Python shared library link: $PYTHON_LINK" >&2
  exit 1
fi

if ! compgen -G "$PYTHON_FRAMEWORK_GLOB/Python3" > /dev/null; then
  echo "ERROR: Missing Python3 framework binary under Contents/Frameworks." >&2
  exit 1
fi

mkdir -p "$RELEASE_DIR"
rm -f "$DMG_PATH"

echo "Creating DMG: $DMG_PATH"
hdiutil create \
  -volname "$VOLUME_NAME" \
  -srcfolder "$APP_BUNDLE" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

if [[ ! -f "$DMG_PATH" ]]; then
  echo "ERROR: DMG was not created: $DMG_PATH" >&2
  exit 1
fi

echo
echo "Release complete:"
echo "  App: $APP_BUNDLE"
echo "  DMG: $DMG_PATH"
echo
echo "Client install flow (no Terminal required):"
echo "  1) Open DMG"
echo "  2) Drag ${APP_NAME}.app to Applications"
echo "  3) Eject DMG"
echo "  4) In Applications: right-click ${APP_NAME} > Open (first launch)"
