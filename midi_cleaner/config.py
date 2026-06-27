from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass
class CleanerConfig:
    input_dir: Path
    output_dir: Path
    recursive: bool = True
    time_unit: str = "mixed"
    split_pitch: int = 60
    min_pitch: int = 33
    max_pitch: int = 96
    max_simultaneous_per_hand: int = 3
    max_hand_span_semitones: int = 12
    min_hand_move_delay_seconds: float = 0.08
    max_duration_seconds: float = 4.0
    merge_gap_seconds: float = 0.12
    merge_min_duration_seconds: float = 0.35
    sustain_mode: str = "adaptive"
    sustain_every_beats: int = 4
    sustain_gap_multiplier: float = 1.8
    sustain_min_hold_seconds: float = 0.2
    sustain_max_hold_seconds: float = 8.0
    sustain_release_before_next_seconds: float = 0.05
    sustain_hybrid_sparse_cycle_note_threshold: int = 2
    sustain_hybrid_max_sparse_cycle_group: int = 3
    sustain_hybrid_extra_hold_seconds: float = 0.25
    sustain_hybrid_adaptive_gap_boost: float = 1.25
    sustain_hybrid_release_factor: float = 0.6
    sustain_hybrid_merge_gap_seconds: float = 0.08
    sustain_chordal_base_chords: int = 3
    sustain_chordal_density_sensitivity: float = 0.75
    sustain_chordal_onset_window_seconds: float = 0.05
    sustain_continuous_reactivation_every_chords: int = 3
    sustain_continuous_window_minutes: float = 1.0
    dry_run: bool = False
    hand_split_mode: str = "cost_based"
    hand_cost_movement_weight: float = 1.0
    hand_cost_span_weight: float = 1.6
    hand_cost_overlap_weight: float = 2.0
    hand_cost_register_bias_weight: float = 0.45

    def validate(self) -> None:
        if not str(self.input_dir).strip():
            raise ValueError("input_dir is required.")
        if not str(self.output_dir).strip():
            raise ValueError("output_dir is required.")
        if self.time_unit not in {"mixed", "seconds", "beats"}:
            raise ValueError("time_unit must be one of: mixed, seconds, beats.")
        if self.hand_split_mode not in {"cost_based", "threshold"}:
            raise ValueError("hand_split_mode must be one of: cost_based, threshold.")
        if self.sustain_mode not in {"adaptive", "periodic", "hybrid", "chordal", "continuous_reactive"}:
            raise ValueError("sustain_mode must be one of: adaptive, periodic, hybrid, chordal, continuous_reactive.")
        if not (0 <= self.min_pitch <= 127 and 0 <= self.max_pitch <= 127):
            raise ValueError("min_pitch and max_pitch must be between 0 and 127.")
        if self.min_pitch > self.max_pitch:
            raise ValueError("min_pitch must be <= max_pitch.")
        if not (0 <= self.split_pitch <= 127):
            raise ValueError("split_pitch must be between 0 and 127.")
        if self.max_simultaneous_per_hand < 1:
            raise ValueError("max_simultaneous_per_hand must be >= 1.")
        if self.max_hand_span_semitones < 0:
            raise ValueError("max_hand_span_semitones must be >= 0.")

        non_negative_fields = {
            "min_hand_move_delay_seconds": self.min_hand_move_delay_seconds,
            "max_duration_seconds": self.max_duration_seconds,
            "merge_gap_seconds": self.merge_gap_seconds,
            "merge_min_duration_seconds": self.merge_min_duration_seconds,
            "sustain_every_beats": float(self.sustain_every_beats),
            "sustain_gap_multiplier": self.sustain_gap_multiplier,
            "sustain_min_hold_seconds": self.sustain_min_hold_seconds,
            "sustain_max_hold_seconds": self.sustain_max_hold_seconds,
            "sustain_release_before_next_seconds": self.sustain_release_before_next_seconds,
            "sustain_hybrid_sparse_cycle_note_threshold": float(self.sustain_hybrid_sparse_cycle_note_threshold),
            "sustain_hybrid_max_sparse_cycle_group": float(self.sustain_hybrid_max_sparse_cycle_group),
            "sustain_hybrid_extra_hold_seconds": self.sustain_hybrid_extra_hold_seconds,
            "sustain_hybrid_adaptive_gap_boost": self.sustain_hybrid_adaptive_gap_boost,
            "sustain_hybrid_release_factor": self.sustain_hybrid_release_factor,
            "sustain_hybrid_merge_gap_seconds": self.sustain_hybrid_merge_gap_seconds,
            "sustain_chordal_base_chords": float(self.sustain_chordal_base_chords),
            "sustain_chordal_density_sensitivity": self.sustain_chordal_density_sensitivity,
            "sustain_chordal_onset_window_seconds": self.sustain_chordal_onset_window_seconds,
            "sustain_continuous_reactivation_every_chords": float(self.sustain_continuous_reactivation_every_chords),
            "sustain_continuous_window_minutes": self.sustain_continuous_window_minutes,
            "hand_cost_movement_weight": self.hand_cost_movement_weight,
            "hand_cost_span_weight": self.hand_cost_span_weight,
            "hand_cost_overlap_weight": self.hand_cost_overlap_weight,
            "hand_cost_register_bias_weight": self.hand_cost_register_bias_weight,
        }
        for field_name, value in non_negative_fields.items():
            if value < 0:
                raise ValueError(f"{field_name} must be >= 0.")
        if self.sustain_every_beats < 1:
            raise ValueError("sustain_every_beats must be >= 1.")
        if self.sustain_hybrid_sparse_cycle_note_threshold < 0:
            raise ValueError("sustain_hybrid_sparse_cycle_note_threshold must be >= 0.")
        if self.sustain_hybrid_max_sparse_cycle_group < 1:
            raise ValueError("sustain_hybrid_max_sparse_cycle_group must be >= 1.")
        if self.sustain_hybrid_adaptive_gap_boost <= 0:
            raise ValueError("sustain_hybrid_adaptive_gap_boost must be > 0.")
        if self.sustain_hybrid_release_factor <= 0:
            raise ValueError("sustain_hybrid_release_factor must be > 0.")
        if self.sustain_chordal_base_chords < 1:
            raise ValueError("sustain_chordal_base_chords must be >= 1.")
        if self.sustain_chordal_density_sensitivity < 0:
            raise ValueError("sustain_chordal_density_sensitivity must be >= 0.")
        if self.sustain_continuous_reactivation_every_chords < 1:
            raise ValueError("sustain_continuous_reactivation_every_chords must be >= 1.")
        if self.sustain_max_hold_seconds < self.sustain_min_hold_seconds:
            raise ValueError("sustain_max_hold_seconds must be >= sustain_min_hold_seconds.")

    def as_json_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["input_dir"] = str(self.input_dir)
        data["output_dir"] = str(self.output_dir)
        return data

    @classmethod
    def from_json_dict(cls, data: Dict[str, Any]) -> "CleanerConfig":
        return cls(
            input_dir=Path(data["input_dir"]),
            output_dir=Path(data["output_dir"]),
            recursive=bool(data.get("recursive", True)),
            time_unit=str(data.get("time_unit", "mixed")),
            split_pitch=int(data.get("split_pitch", 60)),
            min_pitch=int(data.get("min_pitch", 33)),
            max_pitch=int(data.get("max_pitch", 96)),
            max_simultaneous_per_hand=int(data.get("max_simultaneous_per_hand", 3)),
            max_hand_span_semitones=int(data.get("max_hand_span_semitones", 12)),
            min_hand_move_delay_seconds=float(data.get("min_hand_move_delay_seconds", 0.08)),
            max_duration_seconds=float(data.get("max_duration_seconds", 4.0)),
            merge_gap_seconds=float(data.get("merge_gap_seconds", 0.12)),
            merge_min_duration_seconds=float(data.get("merge_min_duration_seconds", 0.35)),
            sustain_mode=str(data.get("sustain_mode", "adaptive")),
            sustain_every_beats=int(data.get("sustain_every_beats", 4)),
            sustain_gap_multiplier=float(data.get("sustain_gap_multiplier", 1.8)),
            sustain_min_hold_seconds=float(data.get("sustain_min_hold_seconds", 0.2)),
            sustain_max_hold_seconds=float(data.get("sustain_max_hold_seconds", 8.0)),
            sustain_release_before_next_seconds=float(data.get("sustain_release_before_next_seconds", 0.05)),
            sustain_hybrid_sparse_cycle_note_threshold=int(data.get("sustain_hybrid_sparse_cycle_note_threshold", 2)),
            sustain_hybrid_max_sparse_cycle_group=int(data.get("sustain_hybrid_max_sparse_cycle_group", 3)),
            sustain_hybrid_extra_hold_seconds=float(data.get("sustain_hybrid_extra_hold_seconds", 0.25)),
            sustain_hybrid_adaptive_gap_boost=float(data.get("sustain_hybrid_adaptive_gap_boost", 1.25)),
            sustain_hybrid_release_factor=float(data.get("sustain_hybrid_release_factor", 0.6)),
            sustain_hybrid_merge_gap_seconds=float(data.get("sustain_hybrid_merge_gap_seconds", 0.08)),
            sustain_chordal_base_chords=int(data.get("sustain_chordal_base_chords", 3)),
            sustain_chordal_density_sensitivity=float(data.get("sustain_chordal_density_sensitivity", 0.75)),
            sustain_chordal_onset_window_seconds=float(data.get("sustain_chordal_onset_window_seconds", 0.05)),
            sustain_continuous_reactivation_every_chords=int(data.get("sustain_continuous_reactivation_every_chords", 3)),
            sustain_continuous_window_minutes=float(data.get("sustain_continuous_window_minutes", 1.0)),
            dry_run=bool(data.get("dry_run", False)),
            hand_split_mode=str(data.get("hand_split_mode", "cost_based")),
            hand_cost_movement_weight=float(data.get("hand_cost_movement_weight", 1.0)),
            hand_cost_span_weight=float(data.get("hand_cost_span_weight", 1.6)),
            hand_cost_overlap_weight=float(data.get("hand_cost_overlap_weight", 2.0)),
            hand_cost_register_bias_weight=float(data.get("hand_cost_register_bias_weight", 0.45)),
        )

