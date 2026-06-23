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
        )

