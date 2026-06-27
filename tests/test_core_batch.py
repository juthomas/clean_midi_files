from __future__ import annotations

from pathlib import Path

import pretty_midi

from midi_cleaner.config import CleanerConfig
from midi_cleaner.core import CleanStats, assign_hands_cost_based, enforce_playability, process_batch, split_hands


def write_simple_midi(path: Path, pitch: int = 60, start: float = 0.0, end: float = 1.0) -> None:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    piano = pretty_midi.Instrument(program=0)
    piano.notes.append(pretty_midi.Note(velocity=90, pitch=pitch, start=start, end=end))
    midi.instruments.append(piano)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))


def test_process_batch_continues_on_corrupted_file(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir(parents=True, exist_ok=True)

    write_simple_midi(input_dir / "ok.mid", pitch=64, start=0.0, end=1.0)
    (input_dir / "broken.mid").write_bytes(b"not-a-midi")

    config = CleanerConfig(input_dir=input_dir, output_dir=output_dir)
    result = process_batch(config)

    assert result.total_files == 2
    assert result.processed_count == 1
    assert result.failed_count == 1
    assert any(r.success for r in result.results)
    assert any(not r.success for r in result.results)
    assert (output_dir / "ok.mid").exists()


def test_playability_limits_simultaneous_notes_and_span() -> None:
    notes = [
        pretty_midi.Note(velocity=80, pitch=36, start=0.0, end=1.0),
        pretty_midi.Note(velocity=70, pitch=40, start=0.0, end=1.0),
        pretty_midi.Note(velocity=60, pitch=45, start=0.0, end=1.0),
        pretty_midi.Note(velocity=50, pitch=52, start=0.0, end=1.0),
    ]
    stats = CleanStats()
    playable = enforce_playability(
        notes,
        split_pitch=60,
        max_simultaneous_per_hand=3,
        max_hand_span_semitones=12,
        min_hand_move_delay=0.05,
        stats=stats,
        hand_split_mode="threshold",
    )
    overlapping = [n for n in playable if n.start <= 0.0 < n.end]
    assert len(overlapping) <= 3
    if overlapping:
        span = max(n.pitch for n in overlapping) - min(n.pitch for n in overlapping)
        assert span <= 12


def test_cost_based_split_can_assign_boundary_note_to_right() -> None:
    notes = [
        pretty_midi.Note(velocity=80, pitch=40, start=0.00, end=0.20),
        pretty_midi.Note(velocity=80, pitch=61, start=0.02, end=0.22),
        pretty_midi.Note(velocity=80, pitch=60, start=0.04, end=0.24),
    ]
    left, right = assign_hands_cost_based(
        notes=notes,
        split_pitch=60,
        max_simultaneous_per_hand=3,
        max_hand_span_semitones=12,
        min_hand_move_delay=0.01,
        movement_weight=1.0,
        span_weight=1.6,
        overlap_weight=2.0,
        register_bias_weight=0.45,
    )
    assert any(n.pitch == 60 for n in right)
    assert any(n.pitch == 40 for n in left)


def test_threshold_mode_keeps_boundary_note_on_left() -> None:
    notes = [
        pretty_midi.Note(velocity=80, pitch=60, start=0.00, end=0.20),
        pretty_midi.Note(velocity=80, pitch=61, start=0.01, end=0.21),
    ]
    left, right = split_hands(notes, split_pitch=60)
    assert any(n.pitch == 60 for n in left)
    assert all(n.pitch > 60 for n in right)

