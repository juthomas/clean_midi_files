from __future__ import annotations

from pathlib import Path

import pretty_midi
import pytest

from midi_cleaner.config import CleanerConfig
from midi_cleaner.core import build_timing_config


def test_config_validation_rejects_invalid_pitch_range(tmp_path: Path) -> None:
    config = CleanerConfig(
        input_dir=tmp_path / "in",
        output_dir=tmp_path / "out",
        min_pitch=90,
        max_pitch=60,
    )
    with pytest.raises(ValueError, match="min_pitch must be <="):
        config.validate()


def test_beats_time_unit_scales_thresholds() -> None:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)  # 0.5s per beat
    piano = pretty_midi.Instrument(program=0)
    piano.notes.append(pretty_midi.Note(velocity=90, pitch=60, start=0.0, end=2.0))
    midi.instruments.append(piano)

    config = CleanerConfig(
        input_dir=Path("input"),
        output_dir=Path("output"),
        time_unit="beats",
        min_hand_move_delay_seconds=2.0,
    )
    timing = build_timing_config(midi, config)
    assert timing.min_hand_move_delay_seconds == pytest.approx(1.0, rel=1e-2)


def test_config_validation_accepts_hybrid_sustain_mode(tmp_path: Path) -> None:
    config = CleanerConfig(
        input_dir=tmp_path / "in",
        output_dir=tmp_path / "out",
        sustain_mode="hybrid",
    )
    config.validate()


def test_config_validation_accepts_chordal_sustain_mode(tmp_path: Path) -> None:
    config = CleanerConfig(
        input_dir=tmp_path / "in",
        output_dir=tmp_path / "out",
        sustain_mode="chordal",
    )
    config.validate()


def test_config_validation_accepts_continuous_reactive_sustain_mode(tmp_path: Path) -> None:
    config = CleanerConfig(
        input_dir=tmp_path / "in",
        output_dir=tmp_path / "out",
        sustain_mode="continuous_reactive",
    )
    config.validate()


def test_config_validation_rejects_invalid_hybrid_release_factor(tmp_path: Path) -> None:
    config = CleanerConfig(
        input_dir=tmp_path / "in",
        output_dir=tmp_path / "out",
        sustain_mode="hybrid",
        sustain_hybrid_release_factor=0.0,
    )
    with pytest.raises(ValueError, match="sustain_hybrid_release_factor must be > 0"):
        config.validate()


def test_config_validation_rejects_invalid_chordal_base_chords(tmp_path: Path) -> None:
    config = CleanerConfig(
        input_dir=tmp_path / "in",
        output_dir=tmp_path / "out",
        sustain_mode="chordal",
        sustain_chordal_base_chords=0,
    )
    with pytest.raises(ValueError, match="sustain_chordal_base_chords must be >= 1"):
        config.validate()


def test_config_validation_rejects_invalid_continuous_reactivation_chords(tmp_path: Path) -> None:
    config = CleanerConfig(
        input_dir=tmp_path / "in",
        output_dir=tmp_path / "out",
        sustain_mode="continuous_reactive",
        sustain_continuous_reactivation_every_chords=0,
    )
    with pytest.raises(ValueError, match="sustain_continuous_reactivation_every_chords must be >= 1"):
        config.validate()

