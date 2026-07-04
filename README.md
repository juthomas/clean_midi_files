# MIDI Cleaner

Desktop + CLI tooling to clean piano MIDI files, then optionally export sheet music PDFs.

## 1) Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

For PDF export you also need LilyPond installed on macOS:

```bash
brew install lilypond
```

## 2) CLI usage (batch)

```bash
python clean_midi.py --input-dir input_midi --output-dir output_midi
```

Useful options:

- `--preset my_preset.json` loads a JSON config preset.
- CLI flags override preset values.
- `--dry-run` processes everything but does not write output files.
- Exit code is `1` when some files fail, `0` when all succeed, `2` for invalid configuration.

Example with preset + override:

```bash
python clean_midi.py \
  --preset preset.json \
  --input-dir input_midi \
  --output-dir output_midi \
  --time-unit beats \
  --dry-run
```

## 3) Desktop UI usage

```bash
python app_ui.py
```

From the UI you can:
- choose input and output folders,
- configure all cleaning parameters,
- toggle PDF export,
- choose PDF output folder,
- skip PDF export automatically if LilyPond is unavailable,
- save/load JSON presets,
- run batch processing and inspect per-file logs,
- cancel a running batch,
- reopen output/PDF folders directly.

Settings are persisted automatically between runs.

## 4) Build local macOS `.app` (unsigned)

```bash
./scripts/build_macos.sh
```

Output app:

- `dist/MidiCleaner.app`

To run on another Mac (unsigned app), Gatekeeper may block first launch:

```bash
xattr -dr com.apple.quarantine dist/MidiCleaner.app
```

Then right-click the app and choose **Open** once.

## 5) Build a distributable macOS DMG (free path)

Use the free release script to build/check the app bundle and create a DMG:

```bash
./scripts/release_macos_free.sh
```

Output artifact:

- `release/MidiCleaner-macos.dmg`

Optional: skip rebuild if `dist/MidiCleaner.app` already exists:

```bash
./scripts/release_macos_free.sh --skip-build
```

The script enforces key bundle checks before packaging:

- `dist/MidiCleaner.app/Contents/MacOS/MidiCleaner` must exist and be executable.
- `dist/MidiCleaner.app/Contents/Frameworks/Python3` must exist.
- A Python framework binary must exist under `Contents/Frameworks/Python3.framework/Versions/*/Python3`.

## 6) Build a signed + notarized DMG (Apple Developer)

Prerequisites on the build Mac:

- Apple paid Developer account.
- `Developer ID Application` certificate installed in Keychain.
- Xcode Command Line Tools (`xcode-select --install`).
- App-specific password for your Apple ID.

Set up a notarytool profile once:

```bash
xcrun notarytool store-credentials "midicleaner-notary" \
  --apple-id "you@example.com" \
  --team-id "YOUR_TEAM_ID" \
  --password "xxxx-xxxx-xxxx-xxxx"
```

Quick preflight checks:

```bash
security find-identity -v -p codesigning
xcrun notarytool history --keychain-profile "midicleaner-notary"
```

Run the notarized release script:

```bash
export APPLE_CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export APPLE_NOTARY_PROFILE="midicleaner-notary"
export APPLE_TEAM_ID="TEAMID" # optional but recommended
./scripts/release_macos_notarized.sh
```

Optional: skip rebuild if `dist/MidiCleaner.app` already exists:

```bash
./scripts/release_macos_notarized.sh --skip-build
```

Expected outputs:

- `release/MidiCleaner-macos-notarized.dmg` (distribute this one)
- `release/notary/MidiCleaner.app.notary.json`
- `release/notary/MidiCleaner.dmg.notary.json`

The script performs:

- app bundle checks,
- `codesign` on app,
- notarization + staple on app,
- DMG creation,
- `codesign` on DMG,
- notarization + staple on DMG,
- final Gatekeeper check via `spctl`.

Manual validation commands (optional):

```bash
xcrun stapler validate "dist/MidiCleaner.app"
xcrun stapler validate "release/MidiCleaner-macos-notarized.dmg"
spctl -a -vv --type open "release/MidiCleaner-macos-notarized.dmg"
```

Distribution note:

- This notarized pipeline is for direct download distribution outside the Mac App Store.
- Mac App Store distribution is a separate workflow (sandboxing + App Store Connect submission/review).

## 7) Client install flow (Finder only, no Terminal)

1. Open `MidiCleaner-macos.dmg`.
2. Drag `MidiCleaner.app` into `Applications`.
3. Eject the DMG.
4. Open `Applications`, then right-click `MidiCleaner` and choose **Open** (first launch only).
5. Confirm **Open** in the macOS security prompt.

After the first confirmation, next launches are usually normal double-clicks.

## 8) One-command Terminal fallback on target Mac

If Finder-only install is blocked, use this macOS-only helper:

```bash
bash ./scripts/install_macos_one_command.sh "/path/to/MidiCleaner-macos.dmg"
```

It will:

- mount/extract the input (`.dmg`, `.zip`, or `.app`),
- install `MidiCleaner.app` into `/Applications`,
- remove quarantine attributes,
- launch the app.

Quick check mode:

```bash
bash ./scripts/install_macos_one_command.sh --dry-run "/path/to/MidiCleaner-macos.dmg"
```

## 9) Known limitations without Apple paid notarization

- This project can ship a working UI app without Terminal usage on many Macs.
- Without Apple Developer ID + notarization, Gatekeeper behavior is not fully predictable across all client machines.
- Some users may still see stricter warnings depending on macOS version and local security policy.
- If you need near-universal smooth launch (`double-click` with minimal warnings), move to a notarized release pipeline.

## 10) Troubleshooting

- **`EOFError` / corrupted MIDI**: the batch skips invalid files and continues.
- **PDF export fails with LilyPond not found**:
  - install with `brew install lilypond`,
  - or set full binary path in UI / CLI (`/opt/homebrew/bin/lilypond`),
  - or enable "Skip PDF if LilyPond missing" in UI.
- **No files processed**: verify input folder contains `.mid` or `.midi`.
- **Input/output conflict**: input and output directories must be different.

