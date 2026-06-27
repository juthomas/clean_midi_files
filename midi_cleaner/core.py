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


def _inject_periodic_sustain(
    midi_obj: pretty_midi.PrettyMIDI,
    instrument: pretty_midi.Instrument,
    every_beats: int,
    release_before_next_seconds: float,
    stats: CleanStats,
) -> None:
    if every_beats <= 0:
        return
    beats = midi_obj.get_beats()
    if len(beats) < every_beats + 1:
        return

    cycle_starts = list(range(0, len(beats) - 1, every_beats))
    for idx in cycle_starts:
        on_time = beats[idx]
        if idx + every_beats < len(beats):
            cycle_end = beats[idx + every_beats]
        else:
            cycle_end = midi_obj.get_end_time()
        off_time = max(on_time, cycle_end - release_before_next_seconds)
        instrument.control_changes.append(pretty_midi.ControlChange(number=64, value=127, time=on_time))
        instrument.control_changes.append(pretty_midi.ControlChange(number=64, value=0, time=off_time))
        stats.sustain_events_added += 2


def _inject_adaptive_sustain(
    midi_obj: pretty_midi.PrettyMIDI,
    instrument: pretty_midi.Instrument,
    gap_multiplier: float,
    min_hold_seconds: float,
    max_hold_seconds: float,
    release_before_next_seconds: float,
    stats: CleanStats,
) -> None:
    notes = sorted(instrument.notes, key=lambda n: (n.start, n.end))
    if not notes:
        return

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
    for note in notes[1:]:
        silence_gap = note.start - current_end
        if silence_gap <= phrase_gap_threshold:
            current_phrase.append(note)
            current_end = max(current_end, note.end)
        else:
            phrases.append(current_phrase)
            current_phrase = [note]
            current_end = note.end
    phrases.append(current_phrase)

    for idx, phrase in enumerate(phrases):
        phrase_start = phrase[0].start
        phrase_end = max(n.end for n in phrase)
        hold_end = phrase_end
        hold_end = max(hold_end, phrase_start + min_hold_seconds)
        hold_end = min(hold_end, phrase_start + max_hold_seconds)
        if idx + 1 < len(phrases):
            next_start = phrases[idx + 1][0].start
            hold_end = min(hold_end, max(phrase_start, next_start - release_before_next_seconds))
        if hold_end <= phrase_start:
            continue
        instrument.control_changes.append(pretty_midi.ControlChange(number=64, value=127, time=phrase_start))
        instrument.control_changes.append(pretty_midi.ControlChange(number=64, value=0, time=hold_end))
        stats.sustain_events_added += 2


def add_sustain_control_changes(
    midi_obj: pretty_midi.PrettyMIDI, instrument: pretty_midi.Instrument, timing: TimingConfig, config: CleanerConfig, stats: CleanStats
) -> None:
    instrument.control_changes = [cc for cc in instrument.control_changes if cc.number != 64]
    if config.sustain_mode == "periodic":
        _inject_periodic_sustain(
            midi_obj=midi_obj,
            instrument=instrument,
            every_beats=config.sustain_every_beats,
            release_before_next_seconds=timing.sustain_release_before_next_seconds,
            stats=stats,
        )
    else:
        _inject_adaptive_sustain(
            midi_obj=midi_obj,
            instrument=instrument,
            gap_multiplier=config.sustain_gap_multiplier,
            min_hold_seconds=timing.sustain_min_hold_seconds,
            max_hold_seconds=timing.sustain_max_hold_seconds,
            release_before_next_seconds=timing.sustain_release_before_next_seconds,
            stats=stats,
        )
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

