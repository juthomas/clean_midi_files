from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from music21 import converter

from .core import midi_files
from .errors import humanize_exception


@dataclass
class PdfExportResult:
    midi_path: Path
    pdf_path: Path
    success: bool
    error: str = ""
    relative_path: Path | None = None


@dataclass
class PdfBatchResult:
    total_files: int
    processed_count: int
    failed_count: int
    canceled: bool
    results: List[PdfExportResult]


def find_lilypond_binary(lilypond_binary: str = "lilypond") -> Path | None:
    raw = lilypond_binary.strip()
    if not raw:
        return None
    explicit = Path(raw).expanduser()
    if explicit.is_absolute() or "/" in raw:
        if explicit.exists() and explicit.is_file():
            return explicit.resolve()
        return None
    resolved = shutil.which(raw)
    return Path(resolved).resolve() if resolved else None


def export_midi_to_pdf(midi_path: Path, pdf_path: Path, lilypond_binary: str = "lilypond") -> PdfExportResult:
    lilypond_path = find_lilypond_binary(lilypond_binary)
    if lilypond_path is None:
        return PdfExportResult(
            midi_path=midi_path,
            pdf_path=pdf_path,
            success=False,
            error=f"LilyPond not found: {lilypond_binary}",
        )

    try:
        score = converter.parse(str(midi_path))
    except Exception as exc:
        return PdfExportResult(
            midi_path=midi_path,
            pdf_path=pdf_path,
            success=False,
            error=humanize_exception(exc),
        )

    if len(score.recurse().notes) == 0:
        return PdfExportResult(midi_path=midi_path, pdf_path=pdf_path, success=False, error="Pas de notes")

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="midi_pdf_") as tmpdir:
            tmp_dir = Path(tmpdir)
            ly_path = tmp_dir / "score.ly"
            score.write("lilypond", fp=str(ly_path))

            out_base = tmp_dir / "score"
            cmd = [str(lilypond_path), "-o", str(out_base), str(ly_path)]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            generated_pdf = out_base.with_suffix(".pdf")
            if proc.returncode != 0 or not generated_pdf.exists():
                err = proc.stderr.strip() or proc.stdout.strip() or "Unknown LilyPond error"
                return PdfExportResult(
                    midi_path=midi_path,
                    pdf_path=pdf_path,
                    success=False,
                    error=f"LilyPond failed ({' '.join(cmd)}): {err}",
                )
            pdf_path.write_bytes(generated_pdf.read_bytes())
            return PdfExportResult(midi_path=midi_path, pdf_path=pdf_path, success=True)
    except Exception as exc:
        return PdfExportResult(
            midi_path=midi_path,
            pdf_path=pdf_path,
            success=False,
            error=humanize_exception(exc),
        )


def export_directory_to_pdf(
    midi_input_dir: Path,
    pdf_output_dir: Path,
    lilypond_binary: str = "lilypond",
    recursive: bool = True,
    on_file_complete: Optional[Callable[[PdfExportResult, int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> PdfBatchResult:
    input_dir = midi_input_dir.expanduser().resolve()
    output_dir = pdf_output_dir.expanduser().resolve()
    files = midi_files(input_dir, recursive=recursive)

    processed_count = 0
    failed_count = 0
    canceled = False
    results: List[PdfExportResult] = []

    for index, src in enumerate(files, start=1):
        if should_cancel and should_cancel():
            canceled = True
            break
        rel = src.relative_to(input_dir)
        pdf_path = (output_dir / rel).with_suffix(".pdf")
        result = export_midi_to_pdf(src, pdf_path, lilypond_binary=lilypond_binary)
        result.relative_path = rel
        if result.success:
            processed_count += 1
        else:
            failed_count += 1
        results.append(result)
        if on_file_complete:
            on_file_complete(result, index, len(files))

    return PdfBatchResult(
        total_files=len(files),
        processed_count=processed_count,
        failed_count=failed_count,
        canceled=canceled,
        results=results,
    )

