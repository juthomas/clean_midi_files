from __future__ import annotations

from pathlib import Path

import pretty_midi

from midi_cleaner.config import CleanerConfig
from midi_cleaner.core import (
    CleanStats,
    add_sustain_control_changes,
    assign_hands_cost_based,
    build_timing_config,
    enforce_playability,
    process_batch,
    split_hands,
)


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


def _build_midi_with_single_instrument(notes: list[tuple[float, float, int]]) -> tuple[pretty_midi.PrettyMIDI, pretty_midi.Instrument]:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    instrument = pretty_midi.Instrument(program=0)
    for start, end, pitch in notes:
        instrument.notes.append(pretty_midi.Note(velocity=88, pitch=pitch, start=start, end=end))
    midi.instruments.append(instrument)
    return midi, instrument


def _cc64_count(instrument: pretty_midi.Instrument) -> int:
    return len([cc for cc in instrument.control_changes if cc.number == 64])


def _sustain_coverage_ratio(instrument: pretty_midi.Instrument, total_duration: float) -> float:
    if total_duration <= 0:
        return 0.0
    cc64 = sorted((cc for cc in instrument.control_changes if cc.number == 64), key=lambda cc: cc.time)
    sustain_on_time: float | None = None
    covered = 0.0
    for cc in cc64:
        if cc.value >= 64:
            if sustain_on_time is None:
                sustain_on_time = min(cc.time, total_duration)
        elif sustain_on_time is not None:
            covered += max(0.0, min(cc.time, total_duration) - sustain_on_time)
            sustain_on_time = None
    if sustain_on_time is not None:
        covered += max(0.0, total_duration - sustain_on_time)
    return min(1.0, covered / total_duration)


def _max_release_gap(instrument: pretty_midi.Instrument) -> float:
    cc64 = sorted((cc for cc in instrument.control_changes if cc.number == 64), key=lambda cc: cc.time)
    max_gap = 0.0
    for idx, cc in enumerate(cc64[:-1]):
        if cc.value == 0:
            next_cc = cc64[idx + 1]
            if next_cc.value >= 64:
                max_gap = max(max_gap, next_cc.time - cc.time)
    return max_gap


def _cc64_on_times(instrument: pretty_midi.Instrument) -> list[float]:
    return [cc.time for cc in sorted(instrument.control_changes, key=lambda cc: cc.time) if cc.number == 64 and cc.value >= 64]


def test_hybrid_merges_sparse_periodic_cycles() -> None:
    sparse_notes = [
        (0.00, 0.20, 48),
        (2.00, 2.20, 52),
        (4.00, 4.20, 55),
        (6.00, 6.20, 59),
    ]

    midi_periodic, inst_periodic = _build_midi_with_single_instrument(sparse_notes)
    periodic_cfg = CleanerConfig(
        input_dir=Path("in"),
        output_dir=Path("out"),
        sustain_mode="periodic",
        sustain_every_beats=2,
        sustain_release_before_next_seconds=0.05,
    )
    periodic_timing = build_timing_config(midi_periodic, periodic_cfg)
    add_sustain_control_changes(midi_periodic, inst_periodic, timing=periodic_timing, config=periodic_cfg, stats=CleanStats())

    midi_hybrid, inst_hybrid = _build_midi_with_single_instrument(sparse_notes)
    hybrid_cfg = CleanerConfig(
        input_dir=Path("in"),
        output_dir=Path("out"),
        sustain_mode="hybrid",
        sustain_every_beats=2,
        sustain_release_before_next_seconds=0.05,
        sustain_hybrid_sparse_cycle_note_threshold=1,
        sustain_hybrid_max_sparse_cycle_group=4,
        sustain_hybrid_extra_hold_seconds=0.3,
        sustain_hybrid_merge_gap_seconds=0.15,
    )
    hybrid_timing = build_timing_config(midi_hybrid, hybrid_cfg)
    add_sustain_control_changes(midi_hybrid, inst_hybrid, timing=hybrid_timing, config=hybrid_cfg, stats=CleanStats())

    assert _cc64_count(inst_hybrid) < _cc64_count(inst_periodic)
    total_duration = max(note.end for note in inst_hybrid.notes)
    hybrid_ratio = _sustain_coverage_ratio(inst_hybrid, total_duration)
    assert hybrid_ratio < 1.0
    assert _max_release_gap(inst_hybrid) >= 0.02


def test_adaptive_bridges_melodic_gap_for_connected_phrase() -> None:
    connected_notes = [
        (0.00, 0.08, 60),
        (0.13, 0.21, 62),
        (0.26, 0.34, 64),
        (0.46, 0.54, 65),
    ]
    midi, instrument = _build_midi_with_single_instrument(connected_notes)
    config = CleanerConfig(
        input_dir=Path("in"),
        output_dir=Path("out"),
        sustain_mode="adaptive",
        sustain_gap_multiplier=1.8,
        sustain_min_hold_seconds=0.2,
        sustain_max_hold_seconds=4.0,
    )
    timing = build_timing_config(midi, config)
    add_sustain_control_changes(midi, instrument, timing=timing, config=config, stats=CleanStats())

    # One connected phrase should produce one pedal on/off pair.
    assert _cc64_count(instrument) == 2


def test_hybrid_keeps_audible_releases_on_connected_pattern() -> None:
    connected_notes = [
        (0.00, 0.20, 60),
        (0.30, 0.50, 62),
        (0.60, 0.80, 64),
        (1.00, 1.20, 65),
        (1.30, 1.50, 67),
        (1.70, 1.90, 69),
        (2.10, 2.30, 71),
    ]
    midi, instrument = _build_midi_with_single_instrument(connected_notes)
    config = CleanerConfig(
        input_dir=Path("in"),
        output_dir=Path("out"),
        sustain_mode="hybrid",
        sustain_every_beats=2,
        sustain_gap_multiplier=1.8,
        sustain_min_hold_seconds=0.2,
        sustain_max_hold_seconds=4.0,
        sustain_release_before_next_seconds=0.08,
        sustain_hybrid_sparse_cycle_note_threshold=1,
        sustain_hybrid_max_sparse_cycle_group=2,
        sustain_hybrid_extra_hold_seconds=0.12,
        sustain_hybrid_adaptive_gap_boost=1.1,
        sustain_hybrid_release_factor=1.0,
        sustain_hybrid_merge_gap_seconds=0.03,
    )
    timing = build_timing_config(midi, config)
    add_sustain_control_changes(midi, instrument, timing=timing, config=config, stats=CleanStats())

    ratio = _sustain_coverage_ratio(instrument, max(note.end for note in instrument.notes))
    assert ratio < 0.98
    assert _max_release_gap(instrument) >= 0.02
    assert _cc64_count(instrument) >= 4


def test_chordal_mode_refreshes_more_in_dense_than_sparse() -> None:
    dense_notes = [
        (0.00, 0.14, 60),
        (0.18, 0.32, 64),
        (0.36, 0.50, 67),
        (0.54, 0.68, 62),
        (0.72, 0.86, 65),
        (0.90, 1.04, 69),
        (1.08, 1.22, 61),
    ]
    sparse_notes = [
        (0.00, 0.24, 60),
        (0.95, 1.19, 64),
        (1.90, 2.14, 67),
        (2.85, 3.09, 62),
        (3.80, 4.04, 65),
        (4.75, 4.99, 69),
        (5.70, 5.94, 61),
    ]
    dense_midi, dense_inst = _build_midi_with_single_instrument(dense_notes)
    sparse_midi, sparse_inst = _build_midi_with_single_instrument(sparse_notes)
    cfg = CleanerConfig(
        input_dir=Path("in"),
        output_dir=Path("out"),
        sustain_mode="chordal",
        sustain_chordal_base_chords=3,
        sustain_chordal_density_sensitivity=1.0,
        sustain_chordal_onset_window_seconds=0.05,
        sustain_min_hold_seconds=0.12,
        sustain_max_hold_seconds=1.5,
        sustain_release_before_next_seconds=0.07,
    )
    add_sustain_control_changes(
        dense_midi, dense_inst, timing=build_timing_config(dense_midi, cfg), config=cfg, stats=CleanStats()
    )
    add_sustain_control_changes(
        sparse_midi, sparse_inst, timing=build_timing_config(sparse_midi, cfg), config=cfg, stats=CleanStats()
    )
    dense_on = _cc64_on_times(dense_inst)
    sparse_on = _cc64_on_times(sparse_inst)
    assert len(dense_on) >= 2
    assert len(sparse_on) >= 2
    dense_avg_gap = sum(dense_on[i + 1] - dense_on[i] for i in range(len(dense_on) - 1)) / max(1, len(dense_on) - 1)
    sparse_avg_gap = sum(sparse_on[i + 1] - sparse_on[i] for i in range(len(sparse_on) - 1)) / max(1, len(sparse_on) - 1)
    assert dense_avg_gap < sparse_avg_gap


def test_chordal_mode_adapts_within_mixed_density_file() -> None:
    mixed_notes = [
        (0.00, 0.14, 60),
        (0.18, 0.32, 64),
        (0.36, 0.50, 67),
        (0.54, 0.68, 62),
        (1.70, 1.95, 65),
        (2.80, 3.05, 69),
        (3.90, 4.15, 71),
        (5.10, 5.35, 72),
    ]
    midi, instrument = _build_midi_with_single_instrument(mixed_notes)
    cfg = CleanerConfig(
        input_dir=Path("in"),
        output_dir=Path("out"),
        sustain_mode="chordal",
        sustain_chordal_base_chords=3,
        sustain_chordal_density_sensitivity=1.1,
        sustain_chordal_onset_window_seconds=0.05,
        sustain_min_hold_seconds=0.12,
        sustain_max_hold_seconds=1.6,
        sustain_release_before_next_seconds=0.07,
    )
    add_sustain_control_changes(midi, instrument, timing=build_timing_config(midi, cfg), config=cfg, stats=CleanStats())

    on_times = _cc64_on_times(instrument)
    early = [t for t in on_times if t < 1.2]
    late = [t for t in on_times if t >= 1.2]
    assert len(early) >= 2
    assert len(late) >= 2
    early_gap = sum(early[i + 1] - early[i] for i in range(len(early) - 1)) / max(1, len(early) - 1)
    late_gap = sum(late[i + 1] - late[i] for i in range(len(late) - 1)) / max(1, len(late) - 1)
    assert early_gap < late_gap


def test_chordal_mode_keeps_releases_audible() -> None:
    notes = [
        (0.00, 0.20, 60),
        (0.35, 0.55, 64),
        (0.70, 0.90, 67),
        (1.30, 1.50, 62),
        (1.65, 1.85, 65),
        (2.40, 2.60, 69),
    ]
    midi, instrument = _build_midi_with_single_instrument(notes)
    cfg = CleanerConfig(
        input_dir=Path("in"),
        output_dir=Path("out"),
        sustain_mode="chordal",
        sustain_chordal_base_chords=3,
        sustain_chordal_density_sensitivity=0.9,
        sustain_chordal_onset_window_seconds=0.05,
        sustain_min_hold_seconds=0.12,
        sustain_max_hold_seconds=1.2,
        sustain_release_before_next_seconds=0.08,
    )
    add_sustain_control_changes(midi, instrument, timing=build_timing_config(midi, cfg), config=cfg, stats=CleanStats())
    total_duration = max(note.end for note in instrument.notes)
    assert _sustain_coverage_ratio(instrument, total_duration) < 0.99
    assert _max_release_gap(instrument) >= 0.02


def test_continuous_reactive_mode_is_near_continuous_with_releases() -> None:
    notes = [
        (0.00, 0.18, 60),
        (0.25, 0.43, 64),
        (0.50, 0.68, 67),
        (1.10, 1.28, 62),
        (1.35, 1.53, 65),
        (2.00, 2.18, 69),
        (2.30, 2.48, 71),
    ]
    midi, instrument = _build_midi_with_single_instrument(notes)
    config = CleanerConfig(
        input_dir=Path("in"),
        output_dir=Path("out"),
        sustain_mode="continuous_reactive",
        sustain_continuous_reactivation_every_chords=2,
        sustain_continuous_window_minutes=0.2,
        sustain_chordal_onset_window_seconds=0.05,
        sustain_release_before_next_seconds=0.06,
    )
    timing = build_timing_config(midi, config)
    add_sustain_control_changes(midi, instrument, timing=timing, config=config, stats=CleanStats())

    total_duration = max(note.end for note in instrument.notes)
    ratio = _sustain_coverage_ratio(instrument, total_duration)
    assert ratio > 0.9
    assert _max_release_gap(instrument) >= 0.02


def test_continuous_reactive_dense_has_faster_reactivation_than_sparse() -> None:
    dense_notes = [
        (0.00, 0.12, 60),
        (0.16, 0.28, 62),
        (0.32, 0.44, 64),
        (0.48, 0.60, 65),
        (0.64, 0.76, 67),
        (0.80, 0.92, 69),
        (0.96, 1.08, 71),
    ]
    sparse_notes = [
        (0.00, 0.20, 60),
        (0.90, 1.10, 62),
        (1.80, 2.00, 64),
        (2.70, 2.90, 65),
        (3.60, 3.80, 67),
        (4.50, 4.70, 69),
        (5.40, 5.60, 71),
    ]
    dense_midi, dense_inst = _build_midi_with_single_instrument(dense_notes)
    sparse_midi, sparse_inst = _build_midi_with_single_instrument(sparse_notes)
    cfg = CleanerConfig(
        input_dir=Path("in"),
        output_dir=Path("out"),
        sustain_mode="continuous_reactive",
        sustain_continuous_reactivation_every_chords=2,
        sustain_continuous_window_minutes=0.3,
        sustain_chordal_onset_window_seconds=0.05,
        sustain_release_before_next_seconds=0.06,
    )
    add_sustain_control_changes(
        dense_midi, dense_inst, timing=build_timing_config(dense_midi, cfg), config=cfg, stats=CleanStats()
    )
    add_sustain_control_changes(
        sparse_midi, sparse_inst, timing=build_timing_config(sparse_midi, cfg), config=cfg, stats=CleanStats()
    )

    dense_on = _cc64_on_times(dense_inst)
    sparse_on = _cc64_on_times(sparse_inst)
    assert len(dense_on) >= 2
    assert len(sparse_on) >= 2
    dense_avg_gap = sum(dense_on[i + 1] - dense_on[i] for i in range(len(dense_on) - 1)) / max(1, len(dense_on) - 1)
    sparse_avg_gap = sum(sparse_on[i + 1] - sparse_on[i] for i in range(len(sparse_on) - 1)) / max(1, len(sparse_on) - 1)
    assert dense_avg_gap < sparse_avg_gap

