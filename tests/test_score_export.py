from __future__ import annotations

from pathlib import Path

from midi_cleaner.score_export import export_midi_to_pdf


def test_pdf_export_reports_missing_lilypond(simple_midi_file: Path, tmp_path: Path) -> None:
    result = export_midi_to_pdf(
        midi_path=simple_midi_file,
        pdf_path=tmp_path / "out.pdf",
        lilypond_binary="definitely_not_a_real_lilypond_binary",
    )
    assert not result.success
    assert "LilyPond not found" in result.error

