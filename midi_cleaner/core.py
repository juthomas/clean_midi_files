from __future__ import annotations

import statistics
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

import pretty_midi

from .config import CleanerConfig
from .errors import humanize_exception


@dataclass
class CleanStats:
    removed_out_of_range: int = 0
    trimmed_long_notes: int = 0
    merged_repetitions: int = 0
    truncated_for_playability: int = 0
    skipped_for_playability: int = 0
    sustain_events_added: int = 0
    eof_repaired: int = 0


@dataclass
class TimingConfig:
    min_hand_move_delay_seconds: float
    max_duration_seconds: float
    merge_gap_seconds: float
    merge_min_duration_seconds: float
    sustain_release_before_next_seconds: float
    sustain_min_hold_seconds: float
    sustain_max_hold_seconds: float
    sustain_hybrid_extra_hold_seconds: float
    sustain_hybrid_merge_gap_seconds: float
    sustain_chordal_onset_window_seconds: float
    sustain_continuous_window_seconds: float


@dataclass
class FileProcessResult:
    source_path: Path
    output_path: Path
    relative_path: Path
    success: bool
    stats: Optional[CleanStats] = None
    error: str = ""


@dataclass
class BatchProcessResult:
    total_files: int
    processed_count: int
    failed_count: int
    results: List[FileProcessResult]
    canceled: bool = False


def midi_files(input_dir: Path, recursive: bool) -> List[Path]:
    patterns = ("*.mid", "*.midi")
    files: List[Path] = []
    if recursive:
        for pattern in patterns:
            files.extend(input_dir.rglob(pattern))
    else:
        for pattern in patterns:
            files.extend(input_dir.glob(pattern))
    return sorted(p for p in files if p.is_file())


def _median_beat_duration_seconds(midi_obj: pretty_midi.PrettyMIDI) -> float:
    beats = midi_obj.get_beats()
    if len(beats) > 1:
        beat_diffs = [beats[i + 1] - beats[i] for i in range(len(beats) - 1)]
        positive = [d for d in beat_diffs if d > 0]
        if positive:
            return statistics.median(positive)
    initial_tempo = midi_obj.estimate_tempo()
    if initial_tempo > 0:
        return 60.0 / initial_tempo
    return 0.5


def build_timing_config(midi_obj: pretty_midi.PrettyMIDI, config: CleanerConfig) -> TimingConfig:
    if config.time_unit == "beats":
        scale = _median_beat_duration_seconds(midi_obj)
    else:
        scale = 1.0
    return TimingConfig(
        min_hand_move_delay_seconds=max(0.0, config.min_hand_move_delay_seconds * scale),
        max_duration_seconds=max(0.001, config.max_duration_seconds * scale),
        merge_gap_seconds=max(0.0, config.merge_gap_seconds * scale),
        merge_min_duration_seconds=max(0.0, config.merge_min_duration_seconds * scale),
        sustain_release_before_next_seconds=max(0.0, config.sustain_release_before_next_seconds * scale),
        sustain_min_hold_seconds=max(0.0, config.sustain_min_hold_seconds * scale),
        sustain_max_hold_seconds=max(0.0, config.sustain_max_hold_seconds * scale),
        sustain_hybrid_extra_hold_seconds=max(0.0, config.sustain_hybrid_extra_hold_seconds * scale),
        sustain_hybrid_merge_gap_seconds=max(0.0, config.sustain_hybrid_merge_gap_seconds * scale),
        sustain_chordal_onset_window_seconds=max(0.0, config.sustain_chordal_onset_window_seconds * scale),
        sustain_continuous_window_seconds=max(1.0, config.sustain_continuous_window_minutes * 60.0),
    )


def _try_load_pretty_midi_from_bytes(data: bytes) -> pretty_midi.PrettyMIDI | None:
    with tempfile.NamedTemporaryFile(suffix=".mid", delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            return pretty_midi.PrettyMIDI(tmp.name)
        except Exception:
            return None


def _attempt_repair_eof(input_file: Path) -> pretty_midi.PrettyMIDI | None:
    data = input_file.read_bytes()
    if not data:
        return None
    # Minimal salvage strategy: append end-of-track markers and try conservative truncations.
    eot = b"\x00\xFF\x2F\x00"
    candidates: List[bytes] = [data + eot]
    for trim in (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024):
        if len(data) > trim:
            candidates.append(data[:-trim] + eot)
    for candidate in candidates:
        repaired = _try_load_pretty_midi_from_bytes(candidate)
        if repaired is not None:
            return repaired
    return None


def load_midi_with_repair(input_file: Path) -> Tuple[pretty_midi.PrettyMIDI, bool]:
    try:
        return pretty_midi.PrettyMIDI(str(input_file)), False
    except EOFError as eof_error:
        repaired = _attempt_repair_eof(input_file)
        if repaired is not None:
            return repaired, True
        raise eof_error


def remove_out_of_range(notes: Sequence[pretty_midi.Note], min_pitch: int, max_pitch: int, stats: CleanStats) -> List[pretty_midi.Note]:
    kept: List[pretty_midi.Note] = []
    for note in notes:
        if min_pitch <= note.pitch <= max_pitch:
            kept.append(note)
        else:
            stats.removed_out_of_range += 1
    return kept


def trim_long_notes(notes: Sequence[pretty_midi.Note], max_duration: float, stats: CleanStats) -> List[pretty_midi.Note]:
    trimmed: List[pretty_midi.Note] = []
    for note in notes:
        duration = note.end - note.start
        if duration > max_duration:
            note.end = note.start + max_duration
            stats.trimmed_long_notes += 1
        if note.end > note.start:
            trimmed.append(note)
    return trimmed


def merge_repeated_notes(
    notes: Sequence[pretty_midi.Note], merge_gap_seconds: float, merge_min_duration_seconds: float, stats: CleanStats
) -> List[pretty_midi.Note]:
    by_pitch: dict[int, List[pretty_midi.Note]] = {}
    for note in notes:
        by_pitch.setdefault(note.pitch, []).append(note)

    merged_all: List[pretty_midi.Note] = []
    for pitch_notes in by_pitch.values():
        ordered = sorted(pitch_notes, key=lambda n: (n.start, n.end))
        if not ordered:
            continue
        merged_track: List[pretty_midi.Note] = [ordered[0]]
        for current in ordered[1:]:
            prev = merged_track[-1]
            gap = current.start - prev.end
            prev_duration = prev.end - prev.start
            if gap <= merge_gap_seconds and prev_duration >= merge_min_duration_seconds:
                prev.end = max(prev.end, current.end)
                prev.velocity = max(prev.velocity, current.velocity)
                stats.merged_repetitions += 1
            else:
                merged_track.append(current)
        merged_all.extend(merged_track)
    return sorted(merged_all, key=lambda n: (n.start, n.pitch, n.end))


def split_hands(notes: Sequence[pretty_midi.Note], split_pitch: int) -> Tuple[List[pretty_midi.Note], List[pretty_midi.Note]]:
    left: List[pretty_midi.Note] = []
    right: List[pretty_midi.Note] = []
    for note in notes:
        if note.pitch <= split_pitch:
            left.append(note)
        else:
            right.append(note)
    return left, right


def _hand_assignment_cost(
    note: pretty_midi.Note,
    hand: str,
    active_notes: Sequence[pretty_midi.Note],
    last_pitch: Optional[int],
    split_pitch: int,
    max_simultaneous_per_hand: int,
    max_hand_span_semitones: int,
    movement_weight: float,
    span_weight: float,
    overlap_weight: float,
    register_bias_weight: float,
) -> float:
    anchor_pitch = split_pitch - 12 if hand == "left" else split_pitch + 12
    reference_pitch = last_pitch if last_pitch is not None else anchor_pitch
    movement_cost = abs(note.pitch - reference_pitch) * movement_weight

    if hand == "left":
        register_distance = max(0, note.pitch - split_pitch)
    else:
        register_distance = max(0, split_pitch - note.pitch)
    register_cost = register_distance * register_bias_weight

    projected_count = len(active_notes) + 1
    overlap_excess = max(0, projected_count - max_simultaneous_per_hand)
    overlap_cost = overlap_excess * overlap_weight * 12.0

    pitches = [n.pitch for n in active_notes] + [note.pitch]
    span = max(pitches) - min(pitches) if pitches else 0
    span_excess = max(0, span - max_hand_span_semitones)
    span_cost = span_excess * span_weight
    return movement_cost + register_cost + overlap_cost + span_cost


def assign_hands_cost_based(
    notes: Sequence[pretty_midi.Note],
    split_pitch: int,
    max_simultaneous_per_hand: int,
    max_hand_span_semitones: int,
    min_hand_move_delay: float,
    movement_weight: float,
    span_weight: float,
    overlap_weight: float,
    register_bias_weight: float,
) -> Tuple[List[pretty_midi.Note], List[pretty_midi.Note]]:
    ordered = sorted(notes, key=lambda n: (n.start, n.pitch, n.end))
    left: List[pretty_midi.Note] = []
    right: List[pretty_midi.Note] = []
    left_active: List[pretty_midi.Note] = []
    right_active: List[pretty_midi.Note] = []
    last_left_pitch: Optional[int] = None
    last_right_pitch: Optional[int] = None

    for note in ordered:
        left_active = [n for n in left_active if (n.end + min_hand_move_delay) > note.start]
        right_active = [n for n in right_active if (n.end + min_hand_move_delay) > note.start]

        left_cost = _hand_assignment_cost(
            note=note,
            hand="left",
            active_notes=left_active,
            last_pitch=last_left_pitch,
            split_pitch=split_pitch,
            max_simultaneous_per_hand=max_simultaneous_per_hand,
            max_hand_span_semitones=max_hand_span_semitones,
            movement_weight=movement_weight,
            span_weight=span_weight,
            overlap_weight=overlap_weight,
            register_bias_weight=register_bias_weight,
        )
        right_cost = _hand_assignment_cost(
            note=note,
            hand="right",
            active_notes=right_active,
            last_pitch=last_right_pitch,
            split_pitch=split_pitch,
            max_simultaneous_per_hand=max_simultaneous_per_hand,
            max_hand_span_semitones=max_hand_span_semitones,
            movement_weight=movement_weight,
            span_weight=span_weight,
            overlap_weight=overlap_weight,
            register_bias_weight=register_bias_weight,
        )

        if left_cost < right_cost:
            target_hand = "left"
        elif right_cost < left_cost:
            target_hand = "right"
        else:
            target_hand = "left" if note.pitch <= split_pitch else "right"

        if target_hand == "left":
            left.append(note)
            left_active.append(note)
            last_left_pitch = note.pitch
        else:
            right.append(note)
            right_active.append(note)
            last_right_pitch = note.pitch
    return left, right


def _remove_note_from_active(
    note: pretty_midi.Note,
    active: List[pretty_midi.Note],
    current_start: float,
    min_hand_move_delay: float,
    current_note: pretty_midi.Note,
    stats: CleanStats,
) -> None:
    if note in active:
        active.remove(note)
    if note is current_note:
        note.end = note.start
        stats.skipped_for_playability += 1
        return
    target_end = current_start - min_hand_move_delay
    if note.end > target_end:
        note.end = max(note.start, target_end)
        stats.truncated_for_playability += 1


def enforce_hand_playability(
    notes: Sequence[pretty_midi.Note], max_simultaneous: int, max_span: int, min_hand_move_delay: float, stats: CleanStats
) -> List[pretty_midi.Note]:
    ordered = sorted(notes, key=lambda n: (n.start, -n.velocity, n.pitch))
    active: List[pretty_midi.Note] = []

    for note in ordered:
        active = [a for a in active if (a.end + min_hand_move_delay) > note.start]
        active.append(note)

        while len(active) > max_simultaneous:
            to_remove = min(active, key=lambda a: a.velocity)
            _remove_note_from_active(to_remove, active, note.start, min_hand_move_delay, note, stats)

        while active:
            min_pitch = min(a.pitch for a in active)
            max_pitch = max(a.pitch for a in active)
            if max_pitch - min_pitch <= max_span:
                break
            low_extremes = [a for a in active if a.pitch == min_pitch]
            high_extremes = [a for a in active if a.pitch == max_pitch]
            low_candidate = min(low_extremes, key=lambda a: a.velocity)
            high_candidate = min(high_extremes, key=lambda a: a.velocity)
            to_remove = low_candidate if low_candidate.velocity <= high_candidate.velocity else high_candidate
            _remove_note_from_active(to_remove, active, note.start, min_hand_move_delay, note, stats)

    playable = [n for n in ordered if n.end > n.start]
    return sorted(playable, key=lambda n: (n.start, n.pitch, n.end))


def enforce_playability(
    notes: Sequence[pretty_midi.Note],
    split_pitch: int,
    max_simultaneous_per_hand: int,
    max_hand_span_semitones: int,
    min_hand_move_delay: float,
    stats: CleanStats,
    hand_split_mode: str = "cost_based",
    hand_cost_movement_weight: float = 1.0,
    hand_cost_span_weight: float = 1.6,
    hand_cost_overlap_weight: float = 2.0,
    hand_cost_register_bias_weight: float = 0.45,
) -> List[pretty_midi.Note]:
    if hand_split_mode == "threshold":
        left, right = split_hands(notes, split_pitch=split_pitch)
    else:
        left, right = assign_hands_cost_based(
            notes=notes,
            split_pitch=split_pitch,
            max_simultaneous_per_hand=max_simultaneous_per_hand,
            max_hand_span_semitones=max_hand_span_semitones,
            min_hand_move_delay=min_hand_move_delay,
            movement_weight=hand_cost_movement_weight,
            span_weight=hand_cost_span_weight,
            overlap_weight=hand_cost_overlap_weight,
            register_bias_weight=hand_cost_register_bias_weight,
        )
    left_clean = enforce_hand_playability(left, max_simultaneous_per_hand, max_hand_span_semitones, min_hand_move_delay, stats)
    right_clean = enforce_hand_playability(
        right, max_simultaneous_per_hand, max_hand_span_semitones, min_hand_move_delay, stats
    )
    return sorted(left_clean + right_clean, key=lambda n: (n.start, n.pitch, n.end))


def _cycle_bounds(midi_obj: pretty_midi.PrettyMIDI, every_beats: int) -> List[Tuple[float, float]]:
    if every_beats <= 0:
        return []
    beats = midi_obj.get_beats()
    if len(beats) < every_beats + 1:
        return []
    starts = list(range(0, len(beats) - 1, every_beats))
    cycles: List[Tuple[float, float]] = []
    for idx in starts:
        start = beats[idx]
        if idx + every_beats < len(beats):
            end = beats[idx + every_beats]
        else:
            end = midi_obj.get_end_time()
        if end > start:
            cycles.append((start, end))
    return cycles


def _collect_periodic_sustain_intervals(
    midi_obj: pretty_midi.PrettyMIDI,
    every_beats: int,
    release_before_next_seconds: float,
    extend_sparse_cycles: bool = False,
    notes: Optional[Sequence[pretty_midi.Note]] = None,
    sparse_cycle_note_threshold: int = 2,
    max_sparse_cycle_group: int = 3,
    sparse_extra_hold_seconds: float = 0.0,
) -> List[Tuple[float, float]]:
    cycles = _cycle_bounds(midi_obj, every_beats)
    if not cycles:
        return []
    intervals: List[Tuple[float, float]] = []

    if not extend_sparse_cycles or not notes:
        for start, end in cycles:
            off = max(start, end - release_before_next_seconds)
            if off > start:
                intervals.append((start, off))
        return intervals

    sorted_notes = sorted(notes, key=lambda n: (n.start, n.end))
    counts: List[int] = []
    note_idx = 0
    for start, end in cycles:
        while note_idx < len(sorted_notes) and sorted_notes[note_idx].start < start:
            note_idx += 1
        look_idx = note_idx
        count = 0
        while look_idx < len(sorted_notes) and sorted_notes[look_idx].start < end:
            count += 1
            look_idx += 1
        counts.append(count)

    idx = 0
    while idx < len(cycles):
        start, end = cycles[idx]
        sparse = counts[idx] <= sparse_cycle_note_threshold
        if not sparse:
            off = max(start, end - release_before_next_seconds)
            if off > start:
                intervals.append((start, off))
            idx += 1
            continue

        group_end = idx
        while group_end + 1 < len(cycles):
            if (group_end - idx + 1) >= max_sparse_cycle_group:
                break
            if counts[group_end + 1] > sparse_cycle_note_threshold:
                break
            group_end += 1

        merged_start = cycles[idx][0]
        merged_cycle_end = cycles[group_end][1]
        merged_end = merged_cycle_end + sparse_extra_hold_seconds
        if group_end + 1 < len(cycles):
            next_cycle_start = cycles[group_end + 1][0]
            merged_end = min(merged_end, max(merged_start, next_cycle_start - release_before_next_seconds))
        if merged_end > merged_start:
            intervals.append((merged_start, merged_end))
        idx = group_end + 1
    return intervals


def _collect_adaptive_sustain_intervals(
    midi_obj: pretty_midi.PrettyMIDI,
    notes: Sequence[pretty_midi.Note],
    gap_multiplier: float,
    min_hold_seconds: float,
    max_hold_seconds: float,
    release_before_next_seconds: float,
) -> List[Tuple[float, float]]:
    notes = sorted(notes, key=lambda n: (n.start, n.end))
    if not notes:
        return []

    starts = [n.start for n in notes]
    consecutive_gaps = [starts[i + 1] - starts[i] for i in range(len(starts) - 1)]
    positive_gaps = [g for g in consecutive_gaps if g > 0]
    beats = midi_obj.get_beats()
    beat_diffs = [beats[i + 1] - beats[i] for i in range(len(beats) - 1)] if len(beats) > 1 else []
    fallback_gap = statistics.median(beat_diffs) if beat_diffs else 0.5
    median_gap = statistics.median(positive_gaps) if positive_gaps else fallback_gap
    phrase_gap_threshold = max(0.03, median_gap * max(0.1, gap_multiplier))

    phrases: List[List[pretty_midi.Note]] = []
    current_phrase = [notes[0]]
    current_end = notes[0].end
    adaptive_link_grace = max(0.02, min_hold_seconds * 0.55)
    melodic_bridge_gap = phrase_gap_threshold * 1.55

    for note in notes[1:]:
        silence_gap = note.start - current_end
        last_pitch = current_phrase[-1].pitch
        pitch_distance = abs(note.pitch - last_pitch)
        can_bridge_melodic = pitch_distance <= 7 and silence_gap <= melodic_bridge_gap
        can_bridge_dense = silence_gap <= max(phrase_gap_threshold, adaptive_link_grace)
        if can_bridge_dense or can_bridge_melodic:
            current_phrase.append(note)
            current_end = max(current_end, note.end)
        else:
            phrases.append(current_phrase)
            current_phrase = [note]
            current_end = note.end
    phrases.append(current_phrase)

    intervals: List[Tuple[float, float]] = []
    for idx, phrase in enumerate(phrases):
        phrase_start = phrase[0].start
        phrase_end = max(n.end for n in phrase)
        hold_end = phrase_end
        hold_end = max(hold_end, phrase_start + min_hold_seconds)
        hold_end = min(hold_end, phrase_start + max_hold_seconds)
        if idx + 1 < len(phrases):
            next_start = phrases[idx + 1][0].start
            hold_end = min(hold_end, max(phrase_start, next_start - release_before_next_seconds))
        if hold_end > phrase_start:
            intervals.append((phrase_start, hold_end))
    return intervals


def _collect_chordal_sustain_intervals(
    notes: Sequence[pretty_midi.Note],
    base_chords: int,
    density_sensitivity: float,
    onset_window_seconds: float,
    min_hold_seconds: float,
    max_hold_seconds: float,
    release_before_next_seconds: float,
) -> List[Tuple[float, float]]:
    ordered = sorted(notes, key=lambda n: (n.start, n.end, n.pitch))
    if not ordered:
        return []

    def _build_chords(source_notes: Sequence[pretty_midi.Note], onset_window: float) -> List[Tuple[float, float, set[int]]]:
        chord_events: List[Tuple[float, float, set[int]]] = []
        idx = 0
        while idx < len(source_notes):
            anchor_start = source_notes[idx].start
            chord_notes = [source_notes[idx]]
            idx += 1
            while idx < len(source_notes) and source_notes[idx].start <= (anchor_start + onset_window):
                chord_notes.append(source_notes[idx])
                idx += 1
            chord_start = min(n.start for n in chord_notes)
            chord_end = max(n.end for n in chord_notes)
            pitch_classes = {n.pitch % 12 for n in chord_notes}
            chord_events.append((chord_start, chord_end, pitch_classes))
        return chord_events

    onset_window = max(0.001, onset_window_seconds)
    chords = _build_chords(ordered, onset_window)
    if not chords:
        return []

    chord_onsets = [item[0] for item in chords]
    onset_gaps = [chord_onsets[i + 1] - chord_onsets[i] for i in range(len(chord_onsets) - 1) if chord_onsets[i + 1] > chord_onsets[i]]
    median_gap = statistics.median(onset_gaps) if onset_gaps else max(onset_window, 0.3)
    reference_density = 1.0 / max(0.03, median_gap)
    density_span = max(2, min(4, base_chords))

    def _local_density(chord_index: int) -> float:
        left = max(0, chord_index - density_span)
        right = min(len(chords) - 1, chord_index + density_span)
        if right == left:
            duration = max(0.03, chords[right][1] - chords[left][0])
        else:
            duration = max(0.03, chords[right][0] - chords[left][0])
        return (right - left + 1) / duration

    def _is_harmonic_change(previous: set[int], current: set[int]) -> bool:
        if not previous or not current:
            return False
        union = previous | current
        if not union:
            return False
        similarity = len(previous & current) / len(union)
        return similarity < 0.55

    trigger_indices: List[int] = [0]
    chords_since_trigger = 0
    for chord_index in range(1, len(chords)):
        chords_since_trigger += 1
        local_density = _local_density(chord_index)
        density_ratio = reference_density / max(0.03, local_density)
        x_local_float = base_chords * (density_ratio ** max(0.0, density_sensitivity))
        x_local = max(1, min(base_chords * 3, int(round(x_local_float))))

        prev_pc = chords[chord_index - 1][2]
        curr_pc = chords[chord_index][2]
        harmonic_change = _is_harmonic_change(prev_pc, curr_pc)

        near_refresh = chords_since_trigger >= max(1, x_local - 1)
        cadence_due = chords_since_trigger >= x_local
        if cadence_due or (harmonic_change and near_refresh):
            trigger_indices.append(chord_index)
            chords_since_trigger = 0
    if trigger_indices[-1] != (len(chords) - 1):
        trigger_indices.append(len(chords) - 1)

    intervals: List[Tuple[float, float]] = []
    for pos, chord_index in enumerate(trigger_indices):
        start, chord_end, _ = chords[chord_index]
        hold_end = max(chord_end, start + min_hold_seconds)
        hold_end = min(hold_end, start + max_hold_seconds)
        if pos + 1 < len(trigger_indices):
            next_start = chords[trigger_indices[pos + 1]][0]
            hold_end = min(hold_end, max(start, next_start - release_before_next_seconds))
        if hold_end > start:
            intervals.append((start, hold_end))
    return intervals


def _collect_continuous_reactive_sustain_intervals(
    notes: Sequence[pretty_midi.Note],
    reactivate_every_chords: int,
    analysis_window_seconds: float,
    onset_window_seconds: float,
    release_before_reactivate_seconds: float,
) -> List[Tuple[float, float]]:
    ordered = sorted(notes, key=lambda n: (n.start, n.end, n.pitch))
    if not ordered:
        return []

    onset_window = max(0.001, onset_window_seconds)
    chords: List[Tuple[float, float]] = []
    idx = 0
    while idx < len(ordered):
        anchor_start = ordered[idx].start
        chord_notes = [ordered[idx]]
        idx += 1
        while idx < len(ordered) and ordered[idx].start <= (anchor_start + onset_window):
            chord_notes.append(ordered[idx])
            idx += 1
        chord_start = min(n.start for n in chord_notes)
        chord_end = max(n.end for n in chord_notes)
        chords.append((chord_start, chord_end))
    if not chords:
        return []

    chord_onsets = [item[0] for item in chords]
    start_time = min(n.start for n in ordered)
    end_time = max(n.end for n in ordered)
    if end_time <= start_time:
        return []

    release_gap = max(0.01, release_before_reactivate_seconds)
    window_seconds = max(1.0, analysis_window_seconds)
    target_chords = max(1, reactivate_every_chords)

    def _local_rate(now_time: float) -> float:
        right = min(end_time, now_time + window_seconds)
        duration = max(0.25, right - now_time)
        count = sum(1 for onset in chord_onsets if now_time <= onset <= right)
        return count / duration if count > 0 else 0.0

    intervals: List[Tuple[float, float]] = []
    segment_start = start_time
    cursor_time = start_time
    while True:
        rate = _local_rate(cursor_time)
        if rate <= 0.0:
            break
        target_seconds = target_chords / rate
        next_target = cursor_time + max(0.05, target_seconds)
        next_onset = next((onset for onset in chord_onsets if onset >= next_target), None)
        if next_onset is None or next_onset >= end_time:
            break
        off_time = max(segment_start, next_onset - release_gap)
        if off_time > segment_start:
            intervals.append((segment_start, off_time))
        segment_start = next_onset
        cursor_time = next_onset
    if end_time > segment_start:
        intervals.append((segment_start, end_time))
    return intervals


def _merge_sustain_intervals(intervals: Sequence[Tuple[float, float]], merge_gap_seconds: float) -> List[Tuple[float, float]]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda item: (item[0], item[1]))
    merged: List[Tuple[float, float]] = []
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= (current_end + merge_gap_seconds):
            current_end = max(current_end, end)
        else:
            if current_end > current_start:
                merged.append((current_start, current_end))
            current_start, current_end = start, end
    if current_end > current_start:
        merged.append((current_start, current_end))
    return merged


def _enforce_min_release_gap(
    intervals: Sequence[Tuple[float, float]], min_release_gap_seconds: float
) -> List[Tuple[float, float]]:
    if not intervals:
        return []
    if min_release_gap_seconds <= 0:
        return list(intervals)

    ordered = sorted(intervals, key=lambda item: (item[0], item[1]))
    adjusted: List[Tuple[float, float]] = []
    for start, end in ordered:
        if end <= start:
            continue
        if not adjusted:
            adjusted.append((start, end))
            continue
        prev_start, prev_end = adjusted[-1]
        min_allowed_end = max(prev_start, start - min_release_gap_seconds)
        if prev_end > min_allowed_end:
            adjusted[-1] = (prev_start, min_allowed_end)
            prev_end = min_allowed_end
        if prev_end <= prev_start:
            adjusted.pop()
        if end > start:
            adjusted.append((start, end))
    return [(start, end) for start, end in adjusted if end > start]


def _split_intervals_by_max_duration(
    intervals: Sequence[Tuple[float, float]], max_duration_seconds: float, release_gap_seconds: float
) -> List[Tuple[float, float]]:
    if not intervals:
        return []
    if max_duration_seconds <= 0:
        return list(intervals)

    pieces: List[Tuple[float, float]] = []
    for start, end in sorted(intervals, key=lambda item: (item[0], item[1])):
        current_start = start
        while (end - current_start) > max_duration_seconds:
            split_end = current_start + max_duration_seconds
            if split_end > current_start:
                pieces.append((current_start, split_end))
            current_start = split_end + max(0.0, release_gap_seconds)
        if end > current_start:
            pieces.append((current_start, end))
    return pieces


def _write_sustain_intervals(
    instrument: pretty_midi.Instrument, intervals: Sequence[Tuple[float, float]], stats: CleanStats
) -> None:
    for start, end in intervals:
        if end <= start:
            continue
        instrument.control_changes.append(pretty_midi.ControlChange(number=64, value=127, time=start))
        instrument.control_changes.append(pretty_midi.ControlChange(number=64, value=0, time=end))
        stats.sustain_events_added += 2


def add_sustain_control_changes(
    midi_obj: pretty_midi.PrettyMIDI, instrument: pretty_midi.Instrument, timing: TimingConfig, config: CleanerConfig, stats: CleanStats
) -> None:
    instrument.control_changes = [cc for cc in instrument.control_changes if cc.number != 64]
    notes = sorted(instrument.notes, key=lambda n: (n.start, n.end))
    if not notes:
        return
    if config.sustain_mode == "periodic":
        intervals = _collect_periodic_sustain_intervals(
            midi_obj=midi_obj,
            every_beats=config.sustain_every_beats,
            release_before_next_seconds=timing.sustain_release_before_next_seconds,
        )
    elif config.sustain_mode == "chordal":
        chordal_intervals = _collect_chordal_sustain_intervals(
            notes=notes,
            base_chords=config.sustain_chordal_base_chords,
            density_sensitivity=config.sustain_chordal_density_sensitivity,
            onset_window_seconds=timing.sustain_chordal_onset_window_seconds,
            min_hold_seconds=timing.sustain_min_hold_seconds,
            max_hold_seconds=timing.sustain_max_hold_seconds,
            release_before_next_seconds=timing.sustain_release_before_next_seconds,
        )
        merged = _merge_sustain_intervals(
            chordal_intervals,
            merge_gap_seconds=min(0.04, max(0.0, timing.sustain_release_before_next_seconds * 0.35)),
        )
        split = _split_intervals_by_max_duration(
            merged,
            max_duration_seconds=max(timing.sustain_min_hold_seconds, timing.sustain_max_hold_seconds),
            release_gap_seconds=max(0.01, timing.sustain_release_before_next_seconds),
        )
        intervals = _enforce_min_release_gap(split, min_release_gap_seconds=max(0.01, timing.sustain_release_before_next_seconds))
    elif config.sustain_mode == "continuous_reactive":
        raw_intervals = _collect_continuous_reactive_sustain_intervals(
            notes=notes,
            reactivate_every_chords=config.sustain_continuous_reactivation_every_chords,
            analysis_window_seconds=timing.sustain_continuous_window_seconds,
            onset_window_seconds=timing.sustain_chordal_onset_window_seconds,
            release_before_reactivate_seconds=timing.sustain_release_before_next_seconds,
        )
        intervals = _enforce_min_release_gap(
            _merge_sustain_intervals(raw_intervals, merge_gap_seconds=0.0),
            min_release_gap_seconds=max(0.01, timing.sustain_release_before_next_seconds),
        )
    elif config.sustain_mode == "hybrid":
        cycles = _cycle_bounds(midi_obj, config.sustain_every_beats)
        cycle_durations = [end - start for start, end in cycles if end > start]
        median_cycle_duration = statistics.median(cycle_durations) if cycle_durations else 1.0
        hybrid_release = timing.sustain_release_before_next_seconds * config.sustain_hybrid_release_factor
        # Guardrail: keep merge strictly below release window, otherwise whole timeline can collapse into one interval.
        hybrid_merge_gap = min(timing.sustain_hybrid_merge_gap_seconds, max(0.0, hybrid_release * 0.45))
        max_sparse_block_cycles = min(2, max(1, config.sustain_hybrid_max_sparse_cycle_group))
        max_hybrid_continuous_duration = max(
            timing.sustain_min_hold_seconds,
            median_cycle_duration * max_sparse_block_cycles + timing.sustain_hybrid_extra_hold_seconds,
        )
        periodic_intervals = _collect_periodic_sustain_intervals(
            midi_obj=midi_obj,
            every_beats=config.sustain_every_beats,
            release_before_next_seconds=timing.sustain_release_before_next_seconds,
            extend_sparse_cycles=True,
            notes=notes,
            sparse_cycle_note_threshold=config.sustain_hybrid_sparse_cycle_note_threshold,
            max_sparse_cycle_group=config.sustain_hybrid_max_sparse_cycle_group,
            sparse_extra_hold_seconds=timing.sustain_hybrid_extra_hold_seconds,
        )
        adaptive_intervals = _collect_adaptive_sustain_intervals(
            midi_obj=midi_obj,
            notes=notes,
            gap_multiplier=config.sustain_gap_multiplier * config.sustain_hybrid_adaptive_gap_boost,
            min_hold_seconds=timing.sustain_min_hold_seconds,
            max_hold_seconds=max(
                timing.sustain_max_hold_seconds, timing.sustain_min_hold_seconds + timing.sustain_hybrid_extra_hold_seconds
            ),
            release_before_next_seconds=hybrid_release,
        )
        merged_intervals = _merge_sustain_intervals(
            periodic_intervals + adaptive_intervals,
            merge_gap_seconds=hybrid_merge_gap,
        )
        split_intervals = _split_intervals_by_max_duration(
            merged_intervals,
            max_duration_seconds=max_hybrid_continuous_duration,
            release_gap_seconds=max(0.01, hybrid_release),
        )
        intervals = _enforce_min_release_gap(split_intervals, min_release_gap_seconds=max(0.01, hybrid_release))
    else:
        intervals = _collect_adaptive_sustain_intervals(
            midi_obj=midi_obj,
            notes=notes,
            gap_multiplier=config.sustain_gap_multiplier,
            min_hold_seconds=timing.sustain_min_hold_seconds,
            max_hold_seconds=timing.sustain_max_hold_seconds,
            release_before_next_seconds=timing.sustain_release_before_next_seconds,
        )
    _write_sustain_intervals(instrument, intervals, stats)
    instrument.control_changes.sort(key=lambda cc: cc.time)


def clean_instrument_notes(instrument: pretty_midi.Instrument, timing: TimingConfig, config: CleanerConfig, stats: CleanStats) -> None:
    notes = sorted(instrument.notes, key=lambda n: (n.start, n.pitch, n.end))
    notes = remove_out_of_range(notes, config.min_pitch, config.max_pitch, stats)
    notes = trim_long_notes(notes, timing.max_duration_seconds, stats)
    notes = merge_repeated_notes(notes, timing.merge_gap_seconds, timing.merge_min_duration_seconds, stats)
    notes = enforce_playability(
        notes,
        split_pitch=config.split_pitch,
        max_simultaneous_per_hand=config.max_simultaneous_per_hand,
        max_hand_span_semitones=config.max_hand_span_semitones,
        min_hand_move_delay=timing.min_hand_move_delay_seconds,
        stats=stats,
        hand_split_mode=config.hand_split_mode,
        hand_cost_movement_weight=config.hand_cost_movement_weight,
        hand_cost_span_weight=config.hand_cost_span_weight,
        hand_cost_overlap_weight=config.hand_cost_overlap_weight,
        hand_cost_register_bias_weight=config.hand_cost_register_bias_weight,
    )
    instrument.notes = notes


def process_file(input_file: Path, output_file: Path, config: CleanerConfig) -> CleanStats:
    midi_obj, repaired = load_midi_with_repair(input_file)
    stats = CleanStats()
    if repaired:
        stats.eof_repaired = 1
    timing = build_timing_config(midi_obj, config)

    for instrument in midi_obj.instruments:
        if instrument.is_drum:
            continue
        clean_instrument_notes(instrument, timing, config, stats)
        add_sustain_control_changes(midi_obj, instrument, timing=timing, config=config, stats=stats)

    if not config.dry_run:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        midi_obj.write(str(output_file))
    return stats


def process_batch(
    config: CleanerConfig,
    on_file_complete: Optional[Callable[[FileProcessResult, int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> BatchProcessResult:
    config.validate()
    input_dir = config.input_dir.expanduser().resolve()
    output_dir = config.output_dir.expanduser().resolve()
    if input_dir == output_dir:
        raise ValueError("input_dir and output_dir must be different.")
    files = midi_files(input_dir, recursive=config.recursive)

    results: List[FileProcessResult] = []
    processed_count = 0
    failed_count = 0
    canceled = False

    for index, src in enumerate(files, start=1):
        if should_cancel and should_cancel():
            canceled = True
            break
        rel = src.relative_to(input_dir)
        dst = output_dir / rel
        try:
            stats = process_file(src, dst, config)
            result = FileProcessResult(
                source_path=src,
                output_path=dst,
                relative_path=rel,
                success=True,
                stats=stats,
            )
            processed_count += 1
        except Exception as exc:
            result = FileProcessResult(
                source_path=src,
                output_path=dst,
                relative_path=rel,
                success=False,
                error=humanize_exception(exc),
            )
            failed_count += 1
        results.append(result)
        if on_file_complete:
            on_file_complete(result, index, len(files))

    return BatchProcessResult(
        total_files=len(files),
        processed_count=processed_count,
        failed_count=failed_count,
        results=results,
        canceled=canceled,
    )


def format_stats(path: Path, stats: CleanStats) -> str:
    return (
        f"{path.name}: "
        f"removed_out_of_range={stats.removed_out_of_range}, "
        f"trimmed_long_notes={stats.trimmed_long_notes}, "
        f"merged_repetitions={stats.merged_repetitions}, "
        f"truncated_for_playability={stats.truncated_for_playability}, "
        f"skipped_for_playability={stats.skipped_for_playability}, "
        f"sustain_events_added={stats.sustain_events_added}, "
        f"eof_repaired={stats.eof_repaired}"
    )

