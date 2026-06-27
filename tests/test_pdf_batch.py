from __future__ import annotations

from pathlib import Path

import pretty_midi

from midi_cleaner.score_export import export_directory_to_pdf


def write_midi(path: Path) -> None:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    instrument = pretty_midi.Instrument(program=0)
    instrument.notes.append(pretty_midi.Note(velocity=90, pitch=60, start=0.0, end=1.0))
    midi.instruments.append(instrument)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))


def test_pdf_batch_reports_failure_when_lilypond_missing(tmp_path: Path) -> None:
    midi_dir = tmp_path / "midi"
    pdf_dir = tmp_path / "pdf"
    write_midi(midi_dir / "a.mid")

    result = export_directory_to_pdf(
        midi_input_dir=midi_dir,
        pdf_output_dir=pdf_dir,
        lilypond_binary="definitely_missing_lilypond",
        recursive=True,
    )
    assert result.total_files == 1
    assert result.failed_count == 1
    assert result.results[0].success is False

