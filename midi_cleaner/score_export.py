from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from music21 import converter


@dataclass
class PdfExportResult:
    midi_path: Path
    pdf_path: Path
    success: bool
    error: str = ""


def export_midi_to_pdf(midi_path: Path, pdf_path: Path, lilypond_binary: str = "lilypond") -> PdfExportResult:
    try:
        score = converter.parse(str(midi_path))
    except Exception as exc:
        return PdfExportResult(midi_path=midi_path, pdf_path=pdf_path, success=False, error=f"Parse failed: {exc}")

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="midi_pdf_") as tmpdir:
            tmp_dir = Path(tmpdir)
            ly_path = tmp_dir / "score.ly"
            score.write("lilypond", fp=str(ly_path))

            out_base = tmp_dir / "score"
            cmd = [lilypond_binary, "-o", str(out_base), str(ly_path)]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            generated_pdf = out_base.with_suffix(".pdf")
            if proc.returncode != 0 or not generated_pdf.exists():
                err = proc.stderr.strip() or proc.stdout.strip() or "Unknown LilyPond error"
                return PdfExportResult(midi_path=midi_path, pdf_path=pdf_path, success=False, error=err)
            pdf_path.write_bytes(generated_pdf.read_bytes())
            return PdfExportResult(midi_path=midi_path, pdf_path=pdf_path, success=True)
    except Exception as exc:
        return PdfExportResult(midi_path=midi_path, pdf_path=pdf_path, success=False, error=f"Export failed: {exc}")

