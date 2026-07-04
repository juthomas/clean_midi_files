#!/usr/bin/env bash
set -euo pipefail

APP_NAME="MidiCleaner"
DEST_APP="/Applications/${APP_NAME}.app"
SOURCE_PATH=""
DRY_RUN=0
MOUNT_POINT=""
TMP_DIR=""

print_usage() {
  echo "Usage: $0 [--dry-run] <path-to-.dmg|.zip|.app>"
  echo
  echo "Examples:"
  echo "  $0 ~/Downloads/MidiCleaner-macos.dmg"
  echo "  $0 ~/Downloads/MidiCleaner.app.zip"
  echo "  $0 --dry-run ~/Downloads/MidiCleaner-macos.dmg"
}

run_with_sudo_if_needed() {
  if [[ -w "/Applications" ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

cleanup_resources() {
  if [[ -n "${MOUNT_POINT:-}" && -d "$MOUNT_POINT" ]]; then
    hdiutil detach "$MOUNT_POINT" >/dev/null 2>&1 || true
  fi
  if [[ -n "${TMP_DIR:-}" && -d "$TMP_DIR" ]]; then
    rm -rf "$TMP_DIR"
  fi
}

resolve_source_app_path() {
  local src="$1"
  local ext="${src##*.}"
  local ext_lc
  ext_lc="$(printf "%s" "$ext" | tr '[:upper:]' '[:lower:]')"

  if [[ -d "$src" && "$src" == *.app ]]; then
    printf "%s\n" "$src"
    return 0
  fi

  if [[ "$ext_lc" == "dmg" ]]; then
    local plist_file
    plist_file="$(mktemp)"
    local app_path=""

    hdiutil attach "$src" -nobrowse -readonly -plist > "$plist_file"
    MOUNT_POINT="$(python3 - <<'PY' "$plist_file"
import plistlib
import sys

plist_path = sys.argv[1]
with open(plist_path, "rb") as f:
    data = plistlib.load(f)

for entity in data.get("system-entities", []):
    mp = entity.get("mount-point")
    if mp:
        print(mp)
        break
PY
)"
    rm -f "$plist_file"

    if [[ -z "$MOUNT_POINT" ]]; then
      echo "ERROR: Could not mount DMG or detect its mount point." >&2
      exit 1
    fi

    for candidate in "$MOUNT_POINT/${APP_NAME}.app" "$MOUNT_POINT"/*.app; do
      if [[ -d "$candidate" ]]; then
        app_path="$candidate"
        break
      fi
    done

    if [[ -z "$app_path" ]]; then
      echo "ERROR: No .app bundle found inside DMG: $src" >&2
      exit 1
    fi

    printf "%s\n" "$app_path"
    return 0
  fi

  if [[ "$ext_lc" == "zip" ]]; then
    TMP_DIR="$(mktemp -d)"
    local app_path=""

    ditto -x -k "$src" "$TMP_DIR"

    for candidate in "$TMP_DIR/${APP_NAME}.app" "$TMP_DIR"/*.app "$TMP_DIR"/*/*.app; do
      if [[ -d "$candidate" ]]; then
        app_path="$candidate"
        break
      fi
    done

    if [[ -z "$app_path" ]]; then
      echo "ERROR: No .app bundle found inside ZIP: $src" >&2
      exit 1
    fi

    printf "%s\n" "$app_path"
    return 0
  fi

  echo "ERROR: Unsupported input: $src (expected .dmg, .zip, or .app)" >&2
  exit 1
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: This installer script is for macOS only." >&2
  exit 1
fi
trap cleanup_resources EXIT

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi

if [[ $# -ne 1 ]]; then
  print_usage
  exit 1
fi

SOURCE_PATH="$1"
if [[ ! -e "$SOURCE_PATH" ]]; then
  echo "ERROR: Input file/folder not found: $SOURCE_PATH" >&2
  exit 1
fi

echo "Resolving app bundle from: $SOURCE_PATH"
SOURCE_APP_PATH="$(resolve_source_app_path "$SOURCE_PATH")"
echo "Found app: $SOURCE_APP_PATH"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "Dry-run mode: skipping install, quarantine cleanup, and launch."
  exit 0
fi

echo "Installing to: $DEST_APP"
run_with_sudo_if_needed rm -rf "$DEST_APP"
run_with_sudo_if_needed ditto "$SOURCE_APP_PATH" "$DEST_APP"

echo "Removing quarantine attributes..."
run_with_sudo_if_needed xattr -dr com.apple.quarantine "$DEST_APP" || true

echo "Launching app..."
open "$DEST_APP"

echo
echo "Done."
echo "If macOS still blocks it, try:"
echo "  System Settings > Privacy & Security > Open Anyway"
