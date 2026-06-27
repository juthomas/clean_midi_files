from __future__ import annotations

from pathlib import Path

import pretty_midi
import pytest


def write_simple_midi(path: Path, pitch: int = 60, start: float = 0.0, end: float = 1.0) -> None:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    piano = pretty_midi.Instrument(program=0)
    piano.notes.append(pretty_midi.Note(velocity=90, pitch=pitch, start=start, end=end))
    midi.instruments.append(piano)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))


@pytest.fixture
def simple_midi_file(tmp_path: Path) -> Path:
    path = tmp_path / "simple.mid"
    write_simple_midi(path, pitch=60, start=0.0, end=2.0)
    return path

