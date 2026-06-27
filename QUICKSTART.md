# Quickstart (macOS)

## Run from source (recommended first)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
brew install lilypond
python app_ui.py
```

## Fast usage flow

1. Select `input_midi` as input folder.
2. Select `output_midi` as output folder.
3. Optional: enable PDF export and choose a PDF folder.
4. Click **Run batch**.
5. Check results table and logs.

## Build a local `.app`

```bash
./scripts/build_macos.sh
```
