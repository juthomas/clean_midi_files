#!/usr/bin/env python3
"""Batch MIDI cleaner CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from midi_cleaner.config import CleanerConfig
from midi_cleaner.core import format_stats, process_batch
from midi_cleaner.score_export import export_directory_to_pdf


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Clean MIDI files for more human-playable piano performance and "
            "write converted files to an output directory."
        )
    )
    parser.add_argument("--preset", type=Path, default=None, help="Optional JSON preset file.")
    parser.add_argument("--input-dir", type=Path, default=None, help="Input folder with MIDI files.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output folder where cleaned files are written (overwritten if present).",
    )
    parser.add_argument(
        "--time-unit",
        choices=("mixed", "seconds", "beats"),
        default=None,
        help=(
            "How to interpret timing thresholds. "
            "'mixed' keeps recommended behavior (human constraints in seconds, musical grid in beats), "
            "'seconds' forces delay thresholds as seconds, "
            "'beats' forces delay thresholds as beats (auto-converted per file)."
        ),
    )
    recursive_group = parser.add_mutually_exclusive_group()
    recursive_group.add_argument(
        "--recursive",
        action="store_const",
        const=True,
        default=None,
        help="Recursively search for MIDI files in input directory (default: enabled).",
    )
    recursive_group.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_const",
        const=False,
        help="Only process MIDI files in the top-level input directory.",
    )
    parser.add_argument("--split-pitch", type=int, default=None, help="Pitch threshold for left/right hand split.")
    parser.add_argument(
        "--hand-split-mode",
        choices=("cost_based", "threshold"),
        default=None,
        help="Hand assignment strategy: cost-based realistic split or historical threshold split.",
    )
    parser.add_argument("--hand-cost-movement-weight", type=float, default=None, help="Weight for hand movement cost.")
    parser.add_argument("--hand-cost-span-weight", type=float, default=None, help="Weight for hand span overflow cost.")
    parser.add_argument(
        "--hand-cost-overlap-weight",
        type=float,
        default=None,
        help="Weight for simultaneous overload cost.",
    )
    parser.add_argument(
        "--hand-cost-register-bias-weight",
        type=float,
        default=None,
        help="Weight for low-left / high-right register bias.",
    )
    parser.add_argument("--min-pitch", type=int, default=None, help="Minimum allowed MIDI pitch.")
    parser.add_argument("--max-pitch", type=int, default=None, help="Maximum allowed MIDI pitch.")
    parser.add_argument("--max-simultaneous-per-hand", type=int, default=None, help="Max simultaneous notes per hand.")
    parser.add_argument("--max-hand-span-semitones", type=int, default=None, help="Max hand span in semitones.")
    parser.add_argument(
        "--min-hand-move-delay-seconds",
        type=float,
        default=None,
        help=(
            "Minimal delay needed to move the hand between note groups. "
            "Notes ending less than this delay before a new note are treated as still active."
        ),
    )
    parser.add_argument("--max-duration-seconds", type=float, default=None, help="Max allowed note duration in seconds.")
    parser.add_argument(
        "--merge-gap-seconds",
        type=float,
        default=None,
        help="Merge same-pitch repetitions when time gap is <= this value.",
    )
    parser.add_argument(
        "--merge-min-duration-seconds",
        type=float,
        default=None,
        help="Only merge if previous note duration is at least this value.",
    )
    parser.add_argument(
        "--sustain-mode",
        choices=("adaptive", "periodic"),
        default=None,
        help="Sustain injection mode: adaptive to note spacing (default) or fixed periodic grid.",
    )
    parser.add_argument(
        "--sustain-every-beats",
        type=int,
        default=None,
        help="Inject sustain pedal cycles every N beats (used in periodic mode).",
    )
    parser.add_argument(
        "--sustain-gap-multiplier",
        type=float,
        default=None,
        help=(
            "Adaptive sustain: notes are considered in the same pedal phrase "
            "if the silence gap is <= median_gap * multiplier."
        ),
    )
    parser.add_argument(
        "--sustain-min-hold-seconds",
        type=float,
        default=None,
        help="Adaptive sustain: minimum duration to keep pedal on for each phrase.",
    )
    parser.add_argument(
        "--sustain-max-hold-seconds",
        type=float,
        default=None,
        help="Adaptive sustain: maximum duration to keep pedal on for each phrase.",
    )
    parser.add_argument(
        "--sustain-release-before-next-seconds",
        type=float,
        default=None,
        help="Release sustain this many seconds before the next cycle starts.",
    )
    dry_run_group = parser.add_mutually_exclusive_group()
    dry_run_group.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_const",
        const=True,
        default=None,
        help="Process files without writing output MIDI files.",
    )
    dry_run_group.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_const",
        const=False,
        help="Disable dry-run mode.",
    )
    parser.add_argument(
        "--pdf-only",
        action="store_true",
        help="Generate PDFs from an existing MIDI output folder without running cleaning.",
    )
    parser.add_argument(
        "--pdf-input-dir",
        type=Path,
        default=None,
        help="Source MIDI folder for PDF-only mode. Defaults to --output-dir when omitted.",
    )
    parser.add_argument(
        "--pdf-output-dir",
        type=Path,
        default=None,
        help="Destination folder for generated PDFs in PDF-only mode.",
    )
    parser.add_argument(
        "--lilypond-binary",
        type=str,
        default="lilypond",
        help="LilyPond binary name or absolute path used for PDF generation.",
    )
    return parser


def _load_preset_data(path: Path) -> Dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "cleaner_config" in raw and isinstance(raw["cleaner_config"], dict):
        return raw["cleaner_config"]
    if isinstance(raw, dict):
        return raw
    raise ValueError("Preset JSON must be an object.")


def config_from_args(args: argparse.Namespace) -> CleanerConfig:
    if args.preset is not None:
        if not args.preset.exists():
            raise ValueError(f"Preset not found: {args.preset}")
        config = CleanerConfig.from_json_dict(_load_preset_data(args.preset))
    else:
        config = CleanerConfig(
            input_dir=args.input_dir or Path(""),
            output_dir=args.output_dir or Path(""),
        )

    overrides = {
        "input_dir": args.input_dir,
        "output_dir": args.output_dir,
        "recursive": args.recursive,
        "time_unit": args.time_unit,
        "split_pitch": args.split_pitch,
        "hand_split_mode": args.hand_split_mode,
        "hand_cost_movement_weight": args.hand_cost_movement_weight,
        "hand_cost_span_weight": args.hand_cost_span_weight,
        "hand_cost_overlap_weight": args.hand_cost_overlap_weight,
        "hand_cost_register_bias_weight": args.hand_cost_register_bias_weight,
        "min_pitch": args.min_pitch,
        "max_pitch": args.max_pitch,
        "max_simultaneous_per_hand": args.max_simultaneous_per_hand,
        "max_hand_span_semitones": args.max_hand_span_semitones,
        "min_hand_move_delay_seconds": args.min_hand_move_delay_seconds,
        "max_duration_seconds": args.max_duration_seconds,
        "merge_gap_seconds": args.merge_gap_seconds,
        "merge_min_duration_seconds": args.merge_min_duration_seconds,
        "sustain_mode": args.sustain_mode,
        "sustain_every_beats": args.sustain_every_beats,
        "sustain_gap_multiplier": args.sustain_gap_multiplier,
        "sustain_min_hold_seconds": args.sustain_min_hold_seconds,
        "sustain_max_hold_seconds": args.sustain_max_hold_seconds,
        "sustain_release_before_next_seconds": args.sustain_release_before_next_seconds,
        "dry_run": args.dry_run,
    }
    for field_name, value in overrides.items():
        if value is not None:
            setattr(config, field_name, value)
    config.validate()
    return config


def run(args: argparse.Namespace) -> int:
    if args.pdf_only:
        midi_input_dir = args.pdf_input_dir or args.output_dir or args.input_dir
        if midi_input_dir is None:
            print("Error: --pdf-only requires --pdf-input-dir (or --output-dir).")
            return 2
        pdf_output_dir = args.pdf_output_dir or Path("output_pdf")
        input_dir = midi_input_dir.expanduser().resolve()
        output_dir = pdf_output_dir.expanduser().resolve()
        if not input_dir.exists() or not input_dir.is_dir():
            print(f"Error: PDF input directory not found: {input_dir}")
            return 2
        result = export_directory_to_pdf(
            midi_input_dir=input_dir,
            pdf_output_dir=output_dir,
            lilypond_binary=args.lilypond_binary,
            recursive=args.recursive if args.recursive is not None else True,
        )
        if result.total_files == 0:
            print(f"No .mid/.midi files found in: {input_dir}")
            return 0
        print(f"Found {result.total_files} MIDI file(s) for PDF export.")
        for item in result.results:
            rel = item.relative_path or item.midi_path.name
            if item.success:
                print(f"[INFO] {rel} -> OK")
            else:
                print(f"[WARNING] {rel} -> {item.error}")
        print(
            f"Done. PDFs written to: {output_dir} "
            f"(processed={result.processed_count}, failed={result.failed_count})."
        )
        return 1 if result.failed_count > 0 else 0

    try:
        config = config_from_args(args)
    except Exception as exc:
        print(f"Error: invalid configuration: {exc}")
        return 2

    input_dir = config.input_dir.expanduser().resolve()
    output_dir = config.output_dir.expanduser().resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        print(f"Error: input directory not found: {input_dir}")
        return 2
    if input_dir == output_dir:
        print("Error: input_dir and output_dir must be different.")
        return 2

    config.input_dir = input_dir
    config.output_dir = output_dir
    batch = process_batch(config)
    if batch.total_files == 0:
        print(f"No .mid/.midi files found in: {input_dir}")
        return 0

    if config.dry_run:
        print("Dry-run mode enabled: no output files will be written.")
    print(f"Found {batch.total_files} MIDI file(s).")
    for result in batch.results:
        if result.success and result.stats:
            print(format_stats(result.relative_path, result.stats))
        else:
            print(f"[WARNING] Skipping {result.relative_path}: {result.error}")

    print(
        f"Done. Cleaned files written to: {output_dir} "
        f"(processed={batch.processed_count}, failed={batch.failed_count})."
    )
    return 1 if batch.failed_count > 0 else 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
