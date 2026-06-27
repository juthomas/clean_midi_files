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

## 5) Troubleshooting

- **`EOFError` / corrupted MIDI**: the batch skips invalid files and continues.
- **PDF export fails with LilyPond not found**:
  - install with `brew install lilypond`,
  - or set full binary path in UI / CLI (`/opt/homebrew/bin/lilypond`),
  - or enable "Skip PDF if LilyPond missing" in UI.
- **No files processed**: verify input folder contains `.mid` or `.midi`.
- **Input/output conflict**: input and output directories must be different.

