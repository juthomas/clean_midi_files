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

## 2) CLI usage

```bash
python clean_midi.py --input-dir input_midi --output-dir output_midi
```

You can still use all existing tuning flags (sustain mode, time unit, etc.).

## 3) Desktop UI usage

```bash
python app_ui.py
```

From the UI you can:
- choose input and output folders,
- configure all cleaning parameters,
- toggle PDF export,
- choose PDF output folder,
- save/load JSON presets,
- run batch processing and inspect per-file logs.

