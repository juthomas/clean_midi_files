#!/usr/bin/env python3
"""Batch MIDI cleaner CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from midi_cleaner.config import CleanerConfig
from midi_cleaner.core import format_stats, process_batch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Clean MIDI files for more human-playable piano performance and "
            "write converted files to an output directory."
        )
    )
    parser.add_argument("--input-dir", required=True, type=Path, help="Input folder with MIDI files.")
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Output folder where cleaned files are written (overwritten if present).",
    )
    parser.add_argument(
        "--time-unit",
        choices=("mixed", "seconds", "beats"),
        default="mixed",
        help=(
            "How to interpret timing thresholds. "
            "'mixed' keeps recommended behavior (human constraints in seconds, musical grid in beats), "
            "'seconds' forces delay thresholds as seconds, "
            "'beats' forces delay thresholds as beats (auto-converted per file)."
        ),
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        default=True,
        help="Recursively search for MIDI files in input directory (default: enabled).",
    )
    parser.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_false",
        help="Only process MIDI files in the top-level input directory.",
    )
    parser.add_argument("--split-pitch", type=int, default=60, help="Pitch threshold for left/right hand split.")
    parser.add_argument("--min-pitch", type=int, default=33, help="Minimum allowed MIDI pitch.")
    parser.add_argument("--max-pitch", type=int, default=96, help="Maximum allowed MIDI pitch.")
    parser.add_argument("--max-simultaneous-per-hand", type=int, default=3, help="Max simultaneous notes per hand.")
    parser.add_argument("--max-hand-span-semitones", type=int, default=12, help="Max hand span in semitones.")
    parser.add_argument(
        "--min-hand-move-delay-seconds",
        type=float,
        default=0.08,
        help=(
            "Minimal delay needed to move the hand between note groups. "
            "Notes ending less than this delay before a new note are treated as still active."
        ),
    )
    parser.add_argument("--max-duration-seconds", type=float, default=4.0, help="Max allowed note duration in seconds.")
    parser.add_argument(
        "--merge-gap-seconds",
        type=float,
        default=0.12,
        help="Merge same-pitch repetitions when time gap is <= this value.",
    )
    parser.add_argument(
        "--merge-min-duration-seconds",
        type=float,
        default=0.35,
        help="Only merge if previous note duration is at least this value.",
    )
    parser.add_argument(
        "--sustain-mode",
        choices=("adaptive", "periodic"),
        default="adaptive",
        help="Sustain injection mode: adaptive to note spacing (default) or fixed periodic grid.",
    )
    parser.add_argument(
        "--sustain-every-beats",
        type=int,
        default=4,
        help="Inject sustain pedal cycles every N beats (used in periodic mode).",
    )
    parser.add_argument(
        "--sustain-gap-multiplier",
        type=float,
        default=1.8,
        help=(
            "Adaptive sustain: notes are considered in the same pedal phrase "
            "if the silence gap is <= median_gap * multiplier."
        ),
    )
    parser.add_argument(
        "--sustain-min-hold-seconds",
        type=float,
        default=0.2,
        help="Adaptive sustain: minimum duration to keep pedal on for each phrase.",
    )
    parser.add_argument(
        "--sustain-max-hold-seconds",
        type=float,
        default=8.0,
        help="Adaptive sustain: maximum duration to keep pedal on for each phrase.",
    )
    parser.add_argument(
        "--sustain-release-before-next-seconds",
        type=float,
        default=0.05,
        help="Release sustain this many seconds before the next cycle starts.",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> CleanerConfig:
    return CleanerConfig(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        recursive=args.recursive,
        time_unit=args.time_unit,
        split_pitch=args.split_pitch,
        min_pitch=args.min_pitch,
        max_pitch=args.max_pitch,
        max_simultaneous_per_hand=args.max_simultaneous_per_hand,
        max_hand_span_semitones=args.max_hand_span_semitones,
        min_hand_move_delay_seconds=args.min_hand_move_delay_seconds,
        max_duration_seconds=args.max_duration_seconds,
        merge_gap_seconds=args.merge_gap_seconds,
        merge_min_duration_seconds=args.merge_min_duration_seconds,
        sustain_mode=args.sustain_mode,
        sustain_every_beats=args.sustain_every_beats,
        sustain_gap_multiplier=args.sustain_gap_multiplier,
        sustain_min_hold_seconds=args.sustain_min_hold_seconds,
        sustain_max_hold_seconds=args.sustain_max_hold_seconds,
        sustain_release_before_next_seconds=args.sustain_release_before_next_seconds,
    )


def run(args: argparse.Namespace) -> int:
    config = config_from_args(args)
    input_dir = config.input_dir.expanduser().resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        print(f"Error: input directory not found: {input_dir}")
        return 2

    batch = process_batch(config)
    if batch.total_files == 0:
        print(f"No .mid/.midi files found in: {input_dir}")
        return 0

    print(f"Found {batch.total_files} MIDI file(s).")
    for result in batch.results:
        if result.success and result.stats:
            print(format_stats(result.relative_path, result.stats))
        else:
            print(f"[WARN] Skipping {result.relative_path}: {result.error}")

    output_dir = config.output_dir.expanduser().resolve()
    print(
        f"Done. Cleaned files written to: {output_dir} "
        f"(processed={batch.processed_count}, failed={batch.failed_count})."
    )
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
