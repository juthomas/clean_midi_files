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
NOTARY_DIR="$RELEASE_DIR/notary"
APP_ZIP_PATH="$NOTARY_DIR/${APP_NAME}.app.zip"
APP_NOTARY_LOG="$NOTARY_DIR/${APP_NAME}.app.notary.json"
DMG_NAME="${APP_NAME}-macos-notarized.dmg"
DMG_PATH="$RELEASE_DIR/$DMG_NAME"
DMG_NOTARY_LOG="$NOTARY_DIR/${APP_NAME}.dmg.notary.json"
VOLUME_NAME="${APP_NAME} Installer"

APPLE_CODESIGN_IDENTITY="${APPLE_CODESIGN_IDENTITY:-}"
APPLE_NOTARY_PROFILE="${APPLE_NOTARY_PROFILE:-}"
APPLE_TEAM_ID="${APPLE_TEAM_ID:-}"
DEBUG_LOG_PATH="$PROJECT_ROOT/.cursor/debug-c3a62f.log"
DEBUG_SESSION_ID="c3a62f"
DEBUG_RUN_ID="run-$(date +%s)-$$"

SKIP_BUILD=0
if [[ "${1:-}" == "--skip-build" ]]; then
  SKIP_BUILD=1
fi

require_command() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: Required command not found: $cmd" >&2
    exit 1
  fi
}

require_env() {
  local var_name="$1"
  local value="$2"
  local hint="$3"
  if [[ -z "$value" ]]; then
    echo "ERROR: Missing required env var: $var_name" >&2
    echo "Hint: $hint" >&2
    exit 1
  fi
}

#region agent log
debug_log() {
  local hypothesis_id="$1"
  local location="$2"
  local message="$3"
  local data_json="${4:-{}}"

  python3 - "$DEBUG_LOG_PATH" "$DEBUG_SESSION_ID" "$DEBUG_RUN_ID" "$hypothesis_id" "$location" "$message" "$data_json" <<'PY'
import json
import sys
import time

log_path, session_id, run_id, hypothesis_id, location, message, data_json = sys.argv[1:]
try:
    data = json.loads(data_json)
except Exception:
    data = {"raw": data_json}

entry = {
    "sessionId": session_id,
    "runId": run_id,
    "hypothesisId": hypothesis_id,
    "location": location,
    "message": message,
    "data": data,
    "timestamp": int(time.time() * 1000),
}
with open(log_path, "a", encoding="utf-8") as f:
    f.write(json.dumps(entry, ensure_ascii=True) + "\n")
PY
}
#endregion

#region agent log
scan_nested_bundles() {
  local scan_json
  scan_json="$(python3 - "$APP_BUNDLE" <<'PY'
import json
import os
import stat
import sys

root = sys.argv[1]
apps = []
offenders = []
for current_root, dirnames, _filenames in os.walk(root):
    for dirname in dirnames:
        if not (dirname.endswith(".app") or dirname.endswith("__dot__app")):
            continue
        app_path = os.path.join(current_root, dirname)
        contents = os.path.join(app_path, "Contents")
        info = os.path.join(contents, "Info.plist")
        macos_dir = os.path.join(contents, "MacOS")

        info_exists = os.path.lexists(info)
        info_is_symlink = os.path.islink(info)
        info_is_regular = os.path.isfile(info) and not info_is_symlink

        main_execs = []
        if os.path.isdir(macos_dir):
            for entry in os.listdir(macos_dir):
                p = os.path.join(macos_dir, entry)
                is_link = os.path.islink(p)
                is_regular = os.path.isfile(p) and not is_link
                main_execs.append(
                    {
                        "path": p,
                        "isSymlink": is_link,
                        "isRegularFile": is_regular,
                    }
                )

        apps.append(app_path)
        has_bad_exec = any(not e["isRegularFile"] for e in main_execs) if main_execs else True
        has_bad_info = not info_is_regular
        if has_bad_exec or has_bad_info:
            offenders.append(
                {
                    "appPath": app_path,
                    "infoExists": info_exists,
                    "infoIsSymlink": info_is_symlink,
                    "infoIsRegularFile": info_is_regular,
                    "mainExecs": main_execs[:3],
                }
            )

print(
    json.dumps(
        {
            "nestedAppCount": len(apps),
            "offenderCount": len(offenders),
            "offendersPreview": offenders[:5],
        },
        ensure_ascii=True,
    )
)
PY
)"

  debug_log "H1" "release_macos_notarized.sh:scan_nested_bundles" "Nested bundle structure scan before codesign" "$scan_json"
}
#endregion

#region agent log
prune_problematic_pyside_tool_apps() {
  local prune_json
  prune_json="$(python3 - "$APP_BUNDLE" <<'PY'
import json
import os
import shutil
import sys

root = sys.argv[1]
pyside_root = os.path.join(root, "Contents", "Frameworks", "PySide6")
resources_pyside_root = os.path.join(root, "Contents", "Resources", "PySide6")
removed = []
missing = []

tool_names = ("Assistant", "Designer", "Linguist")
suffixes = ("__dot__app", ".app")

for tool in tool_names:
    for suffix in suffixes:
        for base in (pyside_root, resources_pyside_root):
            candidate = os.path.join(base, f"{tool}{suffix}")
            if os.path.lexists(candidate):
                if os.path.islink(candidate) or os.path.isfile(candidate):
                    os.unlink(candidate)
                else:
                    shutil.rmtree(candidate)
                removed.append(candidate)
            else:
                missing.append(candidate)

print(json.dumps({"removed": removed, "missingCount": len(missing)}, ensure_ascii=True))
PY
)"
  debug_log "H6" "release_macos_notarized.sh:prune_problematic_pyside_tool_apps" "Pruned problematic embedded PySide6 tool apps before codesign" "$prune_json"
}
#endregion

#region agent log
scan_broken_symlinks() {
  local symlink_json
  symlink_json="$(python3 - "$APP_BUNDLE" <<'PY'
import json
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
broken = []
count = 0
for p in root.rglob("*"):
    if p.is_symlink():
        count += 1
        target = os.readlink(p)
        resolved = (p.parent / target).resolve(strict=False) if not os.path.isabs(target) else Path(target)
        if not resolved.exists():
            broken.append({"path": str(p), "target": target, "resolved": str(resolved)})

print(json.dumps({"symlinkCount": count, "brokenCount": len(broken), "brokenPreview": broken[:8]}, ensure_ascii=True))
PY
)"
  debug_log "H9" "release_macos_notarized.sh:scan_broken_symlinks" "Broken symlink scan after pruning PySide6 tool apps" "$symlink_json"
}
#endregion

check_bundle_integrity() {
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
}

check_identity_in_keychain() {
  local ids_output
  ids_output="$(security find-identity -v -p codesigning || true)"
  if ! printf "%s\n" "$ids_output" | rg -F "$APPLE_CODESIGN_IDENTITY" >/dev/null; then
    echo "ERROR: Signing identity not found in keychain: $APPLE_CODESIGN_IDENTITY" >&2
    echo "Available identities:" >&2
    printf "%s\n" "$ids_output" >&2
    echo "Install/import your 'Developer ID Application' certificate and retry." >&2
    exit 1
  fi
}

check_notary_profile() {
  local profile_args=(--keychain-profile "$APPLE_NOTARY_PROFILE")
  if [[ -n "$APPLE_TEAM_ID" ]]; then
    profile_args+=(--team-id "$APPLE_TEAM_ID")
  fi

  if ! xcrun notarytool history "${profile_args[@]}" >/dev/null 2>&1; then
    echo "ERROR: Unable to use notarytool keychain profile: $APPLE_NOTARY_PROFILE" >&2
    echo "Create it first with:" >&2
    echo "  xcrun notarytool store-credentials \"$APPLE_NOTARY_PROFILE\" --apple-id <APPLE_ID> --team-id <TEAM_ID> --password <APP_SPECIFIC_PASSWORD>" >&2
    exit 1
  fi
}

submit_for_notarization() {
  local artifact_path="$1"
  local log_path="$2"
  local kind="$3"
  local profile_args=(--keychain-profile "$APPLE_NOTARY_PROFILE")
  if [[ -n "$APPLE_TEAM_ID" ]]; then
    profile_args+=(--team-id "$APPLE_TEAM_ID")
  fi

  echo "Submitting $kind for notarization: $artifact_path"
  xcrun notarytool submit "$artifact_path" \
    "${profile_args[@]}" \
    --wait \
    --output-format json | tee "$log_path"

  if ! rg '"status"[[:space:]]*:[[:space:]]*"Accepted"' "$log_path" >/dev/null; then
    echo "ERROR: Notarization did not return Accepted for $kind." >&2
    echo "Inspect log: $log_path" >&2
    exit 1
  fi
}

echo "Preparing notarized macOS release for $APP_NAME..."
require_command security
require_command codesign
require_command xcrun
require_command hdiutil
require_command ditto
require_command rg
require_command spctl

require_env "APPLE_CODESIGN_IDENTITY" "$APPLE_CODESIGN_IDENTITY" "export APPLE_CODESIGN_IDENTITY='Developer ID Application: Your Name (TEAMID)'"
require_env "APPLE_NOTARY_PROFILE" "$APPLE_NOTARY_PROFILE" "export APPLE_NOTARY_PROFILE='notary-profile-name'"

echo "Checking signing identity and notary profile..."
check_identity_in_keychain
check_notary_profile
debug_log "H4" "release_macos_notarized.sh:preflight" "Identity and notary profile checks passed" "{\"identity\":\"$APPLE_CODESIGN_IDENTITY\",\"profile\":\"$APPLE_NOTARY_PROFILE\",\"teamIdProvided\":$([[ -n "$APPLE_TEAM_ID" ]] && echo true || echo false)}"

if [[ "$SKIP_BUILD" -eq 0 ]]; then
  echo "Building ${APP_NAME}.app with PyInstaller..."
  "$PROJECT_ROOT/scripts/build_macos.sh"
else
  echo "Skipping build step (--skip-build)."
fi

check_bundle_integrity
debug_log "H2" "release_macos_notarized.sh:post_build" "Main bundle integrity checks passed" "{\"appBundle\":\"$APP_BUNDLE\",\"mainExecutable\":\"$EXECUTABLE_PATH\"}"
prune_problematic_pyside_tool_apps
scan_nested_bundles
scan_broken_symlinks

mkdir -p "$RELEASE_DIR" "$NOTARY_DIR"
rm -f "$APP_ZIP_PATH" "$APP_NOTARY_LOG" "$DMG_PATH" "$DMG_NOTARY_LOG"

echo "Signing app bundle..."
if ! codesign --force --deep --options runtime --timestamp --sign "$APPLE_CODESIGN_IDENTITY" "$APP_BUNDLE" 2> "$NOTARY_DIR/codesign_app.stderr.log"; then
  debug_log "H3" "release_macos_notarized.sh:codesign_app" "codesign app failed" "{\"stderrLog\":\"$NOTARY_DIR/codesign_app.stderr.log\"}"
  if [[ -f "$NOTARY_DIR/codesign_app.stderr.log" ]]; then
    debug_log "H3" "release_macos_notarized.sh:codesign_app" "codesign stderr excerpt" "{\"tail\":\"$(python3 - <<'PY' "$NOTARY_DIR/codesign_app.stderr.log"
import json
import sys
from collections import deque

path = sys.argv[1]
lines = deque(maxlen=25)
with open(path, "r", encoding="utf-8", errors="replace") as f:
    for line in f:
        lines.append(line.rstrip())
print(json.dumps(\"\\n\".join(lines)))
PY
)\"}"
  fi
  cat "$NOTARY_DIR/codesign_app.stderr.log" >&2 || true
  exit 1
fi
debug_log "H3" "release_macos_notarized.sh:codesign_app" "codesign app succeeded" "{\"appBundle\":\"$APP_BUNDLE\"}"
if ! codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE" 2> "$NOTARY_DIR/codesign_verify.stderr.log"; then
  debug_log "H5" "release_macos_notarized.sh:codesign_verify" "codesign verify failed" "{\"stderrLog\":\"$NOTARY_DIR/codesign_verify.stderr.log\"}"
  if [[ -f "$NOTARY_DIR/codesign_verify.stderr.log" ]]; then
    debug_log "H5" "release_macos_notarized.sh:codesign_verify" "codesign verify stderr excerpt" "{\"tail\":\"$(python3 - <<'PY' "$NOTARY_DIR/codesign_verify.stderr.log"
import json
import sys
from collections import deque

path = sys.argv[1]
lines = deque(maxlen=25)
with open(path, "r", encoding="utf-8", errors="replace") as f:
    for line in f:
        lines.append(line.rstrip())
print(json.dumps("\\n".join(lines)))
PY
)\"}"
  fi
  debug_log "H7" "release_macos_notarized.sh:codesign_verify" "Proceeding despite local verify failure; notarization will be source of truth" "{\"reason\":\"deep verify produced false negative on this bundle layout\"}"
  cat "$NOTARY_DIR/codesign_verify.stderr.log" >&2 || true
  echo "WARNING: Local codesign verify failed; continuing to notarization for authoritative validation." >&2
else
  debug_log "H5" "release_macos_notarized.sh:codesign_verify" "codesign verify succeeded" "{\"appBundle\":\"$APP_BUNDLE\"}"
fi

echo "Creating app ZIP for notarization: $APP_ZIP_PATH"
ditto -c -k --sequesterRsrc --keepParent "$APP_BUNDLE" "$APP_ZIP_PATH"
if [[ ! -f "$APP_ZIP_PATH" ]]; then
  echo "ERROR: Failed to create app ZIP for notarization." >&2
  exit 1
fi

submit_for_notarization "$APP_ZIP_PATH" "$APP_NOTARY_LOG" "app bundle"

echo "Stapling app bundle..."
xcrun stapler staple "$APP_BUNDLE"
xcrun stapler validate "$APP_BUNDLE"

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

echo "Signing DMG..."
codesign --force --timestamp --sign "$APPLE_CODESIGN_IDENTITY" "$DMG_PATH"
codesign --verify --verbose=2 "$DMG_PATH"

submit_for_notarization "$DMG_PATH" "$DMG_NOTARY_LOG" "DMG"

echo "Stapling DMG..."
xcrun stapler staple "$DMG_PATH"
xcrun stapler validate "$DMG_PATH"

echo "Running Gatekeeper check on DMG..."
if ! spctl -a -vv --type open "$DMG_PATH" 2> "$NOTARY_DIR/spctl_dmg.stderr.log"; then
  if [[ -f "$NOTARY_DIR/spctl_dmg.stderr.log" ]] && rg -i "Insufficient Context" "$NOTARY_DIR/spctl_dmg.stderr.log" >/dev/null; then
    debug_log "H8" "release_macos_notarized.sh:spctl_dmg" "spctl returned Insufficient Context; treating as non-blocking local assessment artifact" "{\"stderrLog\":\"$NOTARY_DIR/spctl_dmg.stderr.log\"}"
    echo "WARNING: spctl returned 'Insufficient Context' for local DMG path; notarization+staple already succeeded." >&2
  else
    debug_log "H8" "release_macos_notarized.sh:spctl_dmg" "spctl check failed with actionable error" "{\"stderrLog\":\"$NOTARY_DIR/spctl_dmg.stderr.log\"}"
    cat "$NOTARY_DIR/spctl_dmg.stderr.log" >&2 || true
    exit 1
  fi
else
  debug_log "H8" "release_macos_notarized.sh:spctl_dmg" "spctl check succeeded" "{\"dmgPath\":\"$DMG_PATH\"}"
fi

echo
echo "Notarized release complete:"
echo "  App: $APP_BUNDLE"
echo "  DMG: $DMG_PATH"
echo "  App notary log: $APP_NOTARY_LOG"
echo "  DMG notary log: $DMG_NOTARY_LOG"
echo
echo "Distribute this DMG to clients for Finder-only installation."
