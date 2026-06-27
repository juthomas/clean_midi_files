#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QSettings, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from midi_cleaner.config import CleanerConfig
from midi_cleaner.core import FileProcessResult, format_stats, process_batch

LOG_COLORS = {
    "INFO": QColor("#89D185"),
    "WARNING": QColor("#F5C16C"),
    "ERROR": QColor("#F28B82"),
}

SUSTAIN_PROFILE_CUSTOM = "custom"
SUSTAIN_PROFILES = {
    "natural": {
        "sustain_mode": "adaptive",
        "sustain_every_beats": 4,
        "sustain_gap_multiplier": 1.8,
        "sustain_min_hold_seconds": 0.2,
        "sustain_max_hold_seconds": 8.0,
        "sustain_release_before_next_seconds": 0.05,
        "sustain_hybrid_sparse_cycle_note_threshold": 2,
        "sustain_hybrid_max_sparse_cycle_group": 3,
        "sustain_hybrid_extra_hold_seconds": 0.25,
        "sustain_hybrid_adaptive_gap_boost": 1.25,
        "sustain_hybrid_release_factor": 0.6,
        "sustain_hybrid_merge_gap_seconds": 0.08,
        "sustain_chordal_base_chords": 3,
        "sustain_chordal_density_sensitivity": 0.75,
        "sustain_chordal_onset_window_seconds": 0.05,
        "sustain_continuous_reactivation_every_chords": 3,
        "sustain_continuous_window_minutes": 1.0,
    },
    "hybrid_musical": {
        "sustain_mode": "hybrid",
        "sustain_every_beats": 4,
        "sustain_gap_multiplier": 1.7,
        "sustain_min_hold_seconds": 0.2,
        "sustain_max_hold_seconds": 5.5,
        "sustain_release_before_next_seconds": 0.08,
        "sustain_hybrid_sparse_cycle_note_threshold": 1,
        "sustain_hybrid_max_sparse_cycle_group": 2,
        "sustain_hybrid_extra_hold_seconds": 0.12,
        "sustain_hybrid_adaptive_gap_boost": 1.12,
        "sustain_hybrid_release_factor": 1.0,
        "sustain_hybrid_merge_gap_seconds": 0.02,
        "sustain_chordal_base_chords": 3,
        "sustain_chordal_density_sensitivity": 0.75,
        "sustain_chordal_onset_window_seconds": 0.05,
        "sustain_continuous_reactivation_every_chords": 3,
        "sustain_continuous_window_minutes": 1.0,
    },
    "periodic_rhythm": {
        "sustain_mode": "periodic",
        "sustain_every_beats": 4,
        "sustain_gap_multiplier": 1.8,
        "sustain_min_hold_seconds": 0.2,
        "sustain_max_hold_seconds": 8.0,
        "sustain_release_before_next_seconds": 0.08,
        "sustain_hybrid_sparse_cycle_note_threshold": 2,
        "sustain_hybrid_max_sparse_cycle_group": 3,
        "sustain_hybrid_extra_hold_seconds": 0.25,
        "sustain_hybrid_adaptive_gap_boost": 1.25,
        "sustain_hybrid_release_factor": 0.6,
        "sustain_hybrid_merge_gap_seconds": 0.08,
        "sustain_chordal_base_chords": 3,
        "sustain_chordal_density_sensitivity": 0.75,
        "sustain_chordal_onset_window_seconds": 0.05,
        "sustain_continuous_reactivation_every_chords": 3,
        "sustain_continuous_window_minutes": 1.0,
    },
    "dry": {
        "sustain_mode": "adaptive",
        "sustain_every_beats": 4,
        "sustain_gap_multiplier": 0.6,
        "sustain_min_hold_seconds": 0.03,
        "sustain_max_hold_seconds": 0.12,
        "sustain_release_before_next_seconds": 0.03,
        "sustain_hybrid_sparse_cycle_note_threshold": 0,
        "sustain_hybrid_max_sparse_cycle_group": 1,
        "sustain_hybrid_extra_hold_seconds": 0.0,
        "sustain_hybrid_adaptive_gap_boost": 1.0,
        "sustain_hybrid_release_factor": 1.0,
        "sustain_hybrid_merge_gap_seconds": 0.0,
        "sustain_chordal_base_chords": 2,
        "sustain_chordal_density_sensitivity": 0.4,
        "sustain_chordal_onset_window_seconds": 0.04,
        "sustain_continuous_reactivation_every_chords": 2,
        "sustain_continuous_window_minutes": 1.0,
    },
    "chordal_adaptive": {
        "sustain_mode": "chordal",
        "sustain_every_beats": 4,
        "sustain_gap_multiplier": 1.8,
        "sustain_min_hold_seconds": 0.15,
        "sustain_max_hold_seconds": 4.0,
        "sustain_release_before_next_seconds": 0.06,
        "sustain_hybrid_sparse_cycle_note_threshold": 1,
        "sustain_hybrid_max_sparse_cycle_group": 2,
        "sustain_hybrid_extra_hold_seconds": 0.12,
        "sustain_hybrid_adaptive_gap_boost": 1.0,
        "sustain_hybrid_release_factor": 1.0,
        "sustain_hybrid_merge_gap_seconds": 0.02,
        "sustain_chordal_base_chords": 3,
        "sustain_chordal_density_sensitivity": 0.85,
        "sustain_chordal_onset_window_seconds": 0.05,
        "sustain_continuous_reactivation_every_chords": 3,
        "sustain_continuous_window_minutes": 1.0,
    },
    "continuous_reactive": {
        "sustain_mode": "continuous_reactive",
        "sustain_every_beats": 4,
        "sustain_gap_multiplier": 1.8,
        "sustain_min_hold_seconds": 0.12,
        "sustain_max_hold_seconds": 8.0,
        "sustain_release_before_next_seconds": 0.05,
        "sustain_hybrid_sparse_cycle_note_threshold": 1,
        "sustain_hybrid_max_sparse_cycle_group": 2,
        "sustain_hybrid_extra_hold_seconds": 0.1,
        "sustain_hybrid_adaptive_gap_boost": 1.0,
        "sustain_hybrid_release_factor": 1.0,
        "sustain_hybrid_merge_gap_seconds": 0.0,
        "sustain_chordal_base_chords": 3,
        "sustain_chordal_density_sensitivity": 0.8,
        "sustain_chordal_onset_window_seconds": 0.05,
        "sustain_continuous_reactivation_every_chords": 3,
        "sustain_continuous_window_minutes": 1.0,
    },
}


def normalize_log_line(raw_line: str) -> tuple[str, str]:
    line = raw_line.strip()
    if line.startswith("[WARN]"):
        line = line.replace("[WARN]", "[WARNING]", 1)
    level = "INFO"
    if line.startswith("[ERROR]"):
        level = "ERROR"
    elif line.startswith("[WARNING]"):
        level = "WARNING"
    elif line.startswith("[INFO]"):
        level = "INFO"
    else:
        line = f"[INFO] {line}"

    content = line.split("]", 1)[1].strip() if "]" in line else line
    if level == "INFO":
        padded = f"[INFO]         {content}"
    elif level == "WARNING":
        padded = f"[WARNING] {content}"
    else:
        padded = f"[ERROR]   {content}"
    return level, padded


class StatusTableItem(QTableWidgetItem):
    def __lt__(self, other: object) -> bool:
        if isinstance(other, QTableWidgetItem):
            self_key = self.data(256)  # Qt.UserRole
            other_key = other.data(256)
            if self_key is not None and other_key is not None:
                return self_key < other_key
        return super().__lt__(other)


class CleanerWorker(QObject):
    progress = Signal(int, int)
    log = Signal(str)
    row = Signal(str, str, str)
    done = Signal(int, int, int, bool)

    def __init__(self, config: CleanerConfig, cancel_event: threading.Event) -> None:
        super().__init__()
        self.config = config
        self.cancel_event = cancel_event

    def run(self) -> None:
        def on_file_complete(result: FileProcessResult, index: int, total: int) -> None:
            self.progress.emit(index, total)
            if result.success and result.stats:
                midi_status = "OK"
                detail = format_stats(result.relative_path, result.stats)
                self.row.emit(str(result.relative_path), midi_status, detail)
                self.log.emit(f"[INFO] {detail}")
            else:
                midi_status = "FAILED"
                detail = result.error
                self.row.emit(str(result.relative_path), midi_status, detail)
                self.log.emit(f"[WARNING] {result.relative_path}: {result.error}")

        batch = process_batch(
            self.config,
            on_file_complete=on_file_complete,
            should_cancel=self.cancel_event.is_set,
        )
        self.done.emit(
            batch.total_files,
            batch.processed_count,
            batch.failed_count,
            batch.canceled,
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Nettoyeur MIDI")
        self.resize(1200, 820)
        self._thread: Optional[QThread] = None
        self._worker: Optional[CleanerWorker] = None
        self._cancel_event = threading.Event()
        self._applying_sustain_profile = False
        self.settings = QSettings("punkhazard", "MidiCleaner")
        self._build_ui()
        self._load_defaults()
        self._load_settings()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)

        path_group = QGroupBox("Dossiers")
        path_layout = QGridLayout(path_group)
        self.input_edit = QLineEdit()
        self.output_edit = QLineEdit()
        input_btn = QPushButton("Parcourir...")
        output_btn = QPushButton("Parcourir...")
        input_btn.clicked.connect(lambda: self._pick_directory(self.input_edit))
        output_btn.clicked.connect(lambda: self._pick_directory(self.output_edit))
        path_layout.addWidget(QLabel("Dossier source MIDI"), 0, 0)
        path_layout.addWidget(self.input_edit, 0, 1)
        path_layout.addWidget(input_btn, 0, 2)
        path_layout.addWidget(QLabel("Dossier sortie MIDI"), 1, 0)
        path_layout.addWidget(self.output_edit, 1, 1)
        path_layout.addWidget(output_btn, 1, 2)
        root_layout.addWidget(path_group)

        options_layout = QHBoxLayout()
        options_layout.addWidget(self._build_general_group())
        options_layout.addWidget(self._build_playability_group())
        options_layout.addWidget(self._build_sustain_group())
        root_layout.addLayout(options_layout)

        buttons_layout = QHBoxLayout()
        self.run_btn = QPushButton("Lancer nettoyage")
        self.run_btn.clicked.connect(self._run_batch)
        self.cancel_btn = QPushButton("Annuler")
        self.cancel_btn.clicked.connect(self._cancel_batch)
        self.cancel_btn.setEnabled(False)
        self.save_preset_btn = QPushButton("Sauver preset")
        self.load_preset_btn = QPushButton("Charger preset")
        self.open_output_btn = QPushButton("Ouvrir dossier MIDI")
        self.save_preset_btn.clicked.connect(self._save_preset)
        self.load_preset_btn.clicked.connect(self._load_preset)
        self.open_output_btn.clicked.connect(lambda: self._open_folder(Path(self.output_edit.text().strip())))
        buttons_layout.addWidget(self.run_btn)
        buttons_layout.addWidget(self.cancel_btn)
        buttons_layout.addWidget(self.save_preset_btn)
        buttons_layout.addWidget(self.load_preset_btn)
        buttons_layout.addWidget(self.open_output_btn)
        buttons_layout.addStretch(1)
        root_layout.addLayout(buttons_layout)

        self.progress_label = QLabel("0 / 0")
        root_layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        root_layout.addWidget(self.progress_bar)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Fichier", "Statut MIDI", "Details"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.sortItems(0, Qt.AscendingOrder)
        root_layout.addWidget(self.table, stretch=2)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        root_layout.addWidget(self.log_output, stretch=1)
        self.setCentralWidget(root)

    def _build_general_group(self) -> QGroupBox:
        group = QGroupBox("Parametres generaux")
        form = QFormLayout(group)
        self.recursive_check = QCheckBox("Inclure sous-dossiers")
        self.recursive_check.setChecked(True)
        self.time_unit_combo = QComboBox()
        self.time_unit_combo.addItem("Mixte (musical + physique)", "mixed")
        self.time_unit_combo.addItem("Secondes (tout en temps reel)", "seconds")
        self.time_unit_combo.addItem("Temps musicaux (beats)", "beats")
        self.time_unit_combo.setToolTip(
            "Mixte: contraintes humaines en secondes + grille musicale en beats. "
            "Secondes: tous les delais en secondes. Beats: tous les delais interpretes en beats."
        )
        self.time_unit_combo.currentIndexChanged.connect(self._refresh_time_unit_labels)
        self.split_pitch = QSpinBox()
        self.split_pitch.setRange(0, 127)
        self.hand_split_mode_combo = QComboBox()
        self.hand_split_mode_combo.addItem("Affectation cost-based (recommande)", "cost_based")
        self.hand_split_mode_combo.addItem("Seuil fixe historique", "threshold")
        self.hand_split_mode_combo.setToolTip(
            "Cost-based: repartition plus realiste pour un pianiste. "
            "Threshold: coupe rigide autour de split_pitch."
        )
        self.min_pitch = QSpinBox()
        self.min_pitch.setRange(0, 127)
        self.max_pitch = QSpinBox()
        self.max_pitch.setRange(0, 127)
        self.max_duration = QDoubleSpinBox()
        self.max_duration.setDecimals(3)
        self.max_duration.setRange(0.001, 9999.0)
        self.max_duration.setSingleStep(0.05)
        self.max_duration.setToolTip("Seconds in mixed/seconds mode, beats in beats mode")
        form.addRow(self.recursive_check)
        form.addRow("Separation main gauche/droite (pitch MIDI)", self.split_pitch)
        form.addRow("Pitch minimum autorise (0-127)", self.min_pitch)
        form.addRow("Pitch maximum autorise (0-127)", self.max_pitch)
        self.label_max_duration = QLabel("Duree max d'une note")
        form.addRow(self.label_max_duration, self.max_duration)
        return group

    def _build_playability_group(self) -> QGroupBox:
        group = QGroupBox("Jouabilite")
        form = QFormLayout(group)
        self.max_simultaneous = QSpinBox()
        self.max_simultaneous.setRange(1, 10)
        self.max_hand_span = QSpinBox()
        self.max_hand_span.setRange(1, 48)
        self.min_move_delay = QDoubleSpinBox()
        self.min_move_delay.setDecimals(3)
        self.min_move_delay.setRange(0.0, 60.0)
        self.min_move_delay.setSingleStep(0.01)
        self.min_move_delay.setToolTip("Seconds in mixed/seconds mode, beats in beats mode")
        self.merge_gap = QDoubleSpinBox()
        self.merge_gap.setDecimals(3)
        self.merge_gap.setRange(0.0, 60.0)
        self.merge_gap.setSingleStep(0.01)
        self.merge_gap.setToolTip("Seconds in mixed/seconds mode, beats in beats mode")
        self.merge_min_duration = QDoubleSpinBox()
        self.merge_min_duration.setDecimals(3)
        self.merge_min_duration.setRange(0.0, 60.0)
        self.merge_min_duration.setSingleStep(0.01)
        self.merge_min_duration.setToolTip("Seconds in mixed/seconds mode, beats in beats mode")
        form.addRow("Notes max simultanees par main (notes)", self.max_simultaneous)
        form.addRow("Ecart max main (demi-tons)", self.max_hand_span)
        self.label_min_move_delay = QLabel("Delai mini pour bouger la main")
        self.label_merge_gap = QLabel("Gap max fusion des repetitions")
        self.label_merge_min_duration = QLabel("Duree mini pour fusion")
        form.addRow(self.label_min_move_delay, self.min_move_delay)
        form.addRow(self.label_merge_gap, self.merge_gap)
        form.addRow(self.label_merge_min_duration, self.merge_min_duration)
        return group

    def _build_sustain_group(self) -> QGroupBox:
        group = QGroupBox("Sustain")
        form = QFormLayout(group)
        self.sustain_profile_combo = QComboBox()
        self.sustain_profile_combo.addItem("Personnalise", SUSTAIN_PROFILE_CUSTOM)
        self.sustain_profile_combo.addItem("Naturel (recommande)", "natural")
        self.sustain_profile_combo.addItem("Hybride musical", "hybrid_musical")
        self.sustain_profile_combo.addItem("Accord adaptatif", "chordal_adaptive")
        self.sustain_profile_combo.addItem("Continu reactif accords", "continuous_reactive")
        self.sustain_profile_combo.addItem("Periodique rythmique", "periodic_rhythm")
        self.sustain_profile_combo.addItem("Sec / discret", "dry")
        self.sustain_profile_combo.currentIndexChanged.connect(self._on_sustain_profile_changed)
        self.show_advanced_sustain = QCheckBox("Afficher reglages avances sustain")
        self.show_advanced_sustain.setChecked(False)
        self.show_advanced_sustain.toggled.connect(self._set_sustain_advanced_visible)

        self.sustain_mode = QComboBox()
        self.sustain_mode.addItem("Adaptatif", "adaptive")
        self.sustain_mode.addItem("Periodique", "periodic")
        self.sustain_mode.addItem("Hybride (recommande)", "hybrid")
        self.sustain_mode.addItem("Accords adaptatif", "chordal")
        self.sustain_mode.addItem("Continu reactif accords", "continuous_reactive")
        self.sustain_every_beats = QSpinBox()
        self.sustain_every_beats.setRange(1, 64)
        self.sustain_gap_multiplier = QDoubleSpinBox()
        self.sustain_gap_multiplier.setRange(0.1, 20.0)
        self.sustain_gap_multiplier.setSingleStep(0.1)
        self.sustain_min_hold = QDoubleSpinBox()
        self.sustain_min_hold.setRange(0.0, 60.0)
        self.sustain_min_hold.setSingleStep(0.05)
        self.sustain_max_hold = QDoubleSpinBox()
        self.sustain_max_hold.setRange(0.0, 120.0)
        self.sustain_max_hold.setSingleStep(0.1)
        self.sustain_release = QDoubleSpinBox()
        self.sustain_release.setRange(0.0, 60.0)
        self.sustain_release.setSingleStep(0.01)
        self.sustain_release.setToolTip("Seconds in mixed/seconds mode, beats in beats mode")
        self.sustain_hybrid_sparse_threshold = QSpinBox()
        self.sustain_hybrid_sparse_threshold.setRange(0, 64)
        self.sustain_hybrid_sparse_group = QSpinBox()
        self.sustain_hybrid_sparse_group.setRange(1, 16)
        self.sustain_hybrid_extra_hold = QDoubleSpinBox()
        self.sustain_hybrid_extra_hold.setRange(0.0, 60.0)
        self.sustain_hybrid_extra_hold.setSingleStep(0.05)
        self.sustain_hybrid_adaptive_boost = QDoubleSpinBox()
        self.sustain_hybrid_adaptive_boost.setRange(0.1, 10.0)
        self.sustain_hybrid_adaptive_boost.setSingleStep(0.05)
        self.sustain_hybrid_release_factor = QDoubleSpinBox()
        self.sustain_hybrid_release_factor.setRange(0.05, 3.0)
        self.sustain_hybrid_release_factor.setSingleStep(0.05)
        self.sustain_hybrid_merge_gap = QDoubleSpinBox()
        self.sustain_hybrid_merge_gap.setRange(0.0, 10.0)
        self.sustain_hybrid_merge_gap.setSingleStep(0.01)
        self.sustain_chordal_base_chords = QSpinBox()
        self.sustain_chordal_base_chords.setRange(1, 32)
        self.sustain_chordal_density_sensitivity = QDoubleSpinBox()
        self.sustain_chordal_density_sensitivity.setRange(0.0, 3.0)
        self.sustain_chordal_density_sensitivity.setSingleStep(0.05)
        self.sustain_chordal_onset_window = QDoubleSpinBox()
        self.sustain_chordal_onset_window.setRange(0.0, 2.0)
        self.sustain_chordal_onset_window.setSingleStep(0.01)
        self.sustain_continuous_reactivate_chords = QSpinBox()
        self.sustain_continuous_reactivate_chords.setRange(1, 64)
        self.sustain_continuous_window_minutes = QDoubleSpinBox()
        self.sustain_continuous_window_minutes.setRange(0.1, 60.0)
        self.sustain_continuous_window_minutes.setSingleStep(0.1)

        self.label_sustain_min_hold = QLabel("Duree min sustain")
        self.label_sustain_max_hold = QLabel("Duree max sustain")
        self.label_sustain_release = QLabel("Relache sustain avant prochain")
        self.label_sustain_hybrid_extra_hold = QLabel("Hybride: tenue supplementaire sparse")
        self.label_sustain_hybrid_merge_gap = QLabel("Hybride: gap fusion intervalles")
        self.label_sustain_mode = QLabel("Mode sustain")
        self.label_sustain_every_beats = QLabel("Sustain tous les N beats (beats)")
        self.label_sustain_gap_multiplier = QLabel("Multiplicateur gap sustain")
        self.label_sustain_hybrid_sparse_threshold = QLabel("Hybride: seuil sparse (notes/cycle)")
        self.label_sustain_hybrid_sparse_group = QLabel("Hybride: max cycles sparse fusionnes")
        self.label_sustain_hybrid_adaptive_boost = QLabel("Hybride: boost gap adaptatif (x)")
        self.label_sustain_hybrid_release_factor = QLabel("Hybride: facteur release (x)")
        self.label_sustain_chordal_base_chords = QLabel("Accords adaptatif: repedalage ~X accords")
        self.label_sustain_chordal_density_sensitivity = QLabel("Accords adaptatif: sensibilite densite")
        self.label_sustain_chordal_onset_window = QLabel("Accords adaptatif: fenetre regroupement accords")
        self.label_sustain_continuous_reactivate_chords = QLabel("Continu reactif: reactivation tous les X accords")
        self.label_sustain_continuous_window_minutes = QLabel("Continu reactif: fenetre moyenne (minutes)")

        form.addRow(self.label_sustain_chordal_base_chords, self.sustain_chordal_base_chords)
        form.addRow(self.label_sustain_chordal_density_sensitivity, self.sustain_chordal_density_sensitivity)
        form.addRow(self.label_sustain_chordal_onset_window, self.sustain_chordal_onset_window)
        form.addRow(self.label_sustain_continuous_reactivate_chords, self.sustain_continuous_reactivate_chords)
        form.addRow(self.label_sustain_continuous_window_minutes, self.sustain_continuous_window_minutes)
        form.addRow(self.label_sustain_min_hold, self.sustain_min_hold)
        form.addRow(self.label_sustain_max_hold, self.sustain_max_hold)
        form.addRow(self.label_sustain_release, self.sustain_release)

        self.sustain_advanced_widget = QWidget()
        advanced_form = QFormLayout(self.sustain_advanced_widget)
        advanced_form.addRow(self.label_sustain_every_beats, self.sustain_every_beats)
        advanced_form.addRow(self.label_sustain_gap_multiplier, self.sustain_gap_multiplier)
        advanced_form.addRow(self.label_sustain_hybrid_sparse_threshold, self.sustain_hybrid_sparse_threshold)
        advanced_form.addRow(self.label_sustain_hybrid_sparse_group, self.sustain_hybrid_sparse_group)
        advanced_form.addRow(self.label_sustain_hybrid_extra_hold, self.sustain_hybrid_extra_hold)
        advanced_form.addRow(self.label_sustain_hybrid_adaptive_boost, self.sustain_hybrid_adaptive_boost)
        advanced_form.addRow(self.label_sustain_hybrid_release_factor, self.sustain_hybrid_release_factor)
        advanced_form.addRow(self.label_sustain_hybrid_merge_gap, self.sustain_hybrid_merge_gap)

        self.sustain_mode.currentIndexChanged.connect(self._refresh_sustain_control_visibility)
        self.sustain_mode.currentIndexChanged.connect(self._mark_sustain_profile_custom)
        for spin in (
            self.sustain_every_beats,
            self.sustain_gap_multiplier,
            self.sustain_min_hold,
            self.sustain_max_hold,
            self.sustain_release,
            self.sustain_hybrid_sparse_threshold,
            self.sustain_hybrid_sparse_group,
            self.sustain_hybrid_extra_hold,
            self.sustain_hybrid_adaptive_boost,
            self.sustain_hybrid_release_factor,
            self.sustain_hybrid_merge_gap,
            self.sustain_chordal_base_chords,
            self.sustain_chordal_density_sensitivity,
            self.sustain_chordal_onset_window,
            self.sustain_continuous_reactivate_chords,
            self.sustain_continuous_window_minutes,
        ):
            spin.valueChanged.connect(self._mark_sustain_profile_custom)

        self._set_sustain_advanced_visible(False)
        self._refresh_sustain_control_visibility()
        return group

    def _load_defaults(self) -> None:
        project_dir = Path(__file__).resolve().parent
        default_input = project_dir / "input_midi" if (project_dir / "input_midi").exists() else Path.home() / "input_midi"
        default_output = project_dir / "output_midi"
        config = CleanerConfig(input_dir=default_input, output_dir=default_output)
        self._set_ui_from_config(config)
        self._refresh_time_unit_labels()

    def _build_config_from_ui(self) -> CleanerConfig:
        config = CleanerConfig(
            input_dir=Path(self.input_edit.text().strip()),
            output_dir=Path(self.output_edit.text().strip()),
            recursive=self.recursive_check.isChecked(),
            time_unit="mixed",
            split_pitch=self.split_pitch.value(),
            hand_split_mode="cost_based",
            min_pitch=self.min_pitch.value(),
            max_pitch=self.max_pitch.value(),
            max_simultaneous_per_hand=self.max_simultaneous.value(),
            max_hand_span_semitones=self.max_hand_span.value(),
            min_hand_move_delay_seconds=self.min_move_delay.value(),
            max_duration_seconds=self.max_duration.value(),
            merge_gap_seconds=self.merge_gap.value(),
            merge_min_duration_seconds=self.merge_min_duration.value(),
            sustain_mode="continuous_reactive",
            sustain_every_beats=self.sustain_every_beats.value(),
            sustain_gap_multiplier=self.sustain_gap_multiplier.value(),
            sustain_min_hold_seconds=self.sustain_min_hold.value(),
            sustain_max_hold_seconds=self.sustain_max_hold.value(),
            sustain_release_before_next_seconds=self.sustain_release.value(),
            sustain_hybrid_sparse_cycle_note_threshold=self.sustain_hybrid_sparse_threshold.value(),
            sustain_hybrid_max_sparse_cycle_group=self.sustain_hybrid_sparse_group.value(),
            sustain_hybrid_extra_hold_seconds=self.sustain_hybrid_extra_hold.value(),
            sustain_hybrid_adaptive_gap_boost=self.sustain_hybrid_adaptive_boost.value(),
            sustain_hybrid_release_factor=self.sustain_hybrid_release_factor.value(),
            sustain_hybrid_merge_gap_seconds=self.sustain_hybrid_merge_gap.value(),
            sustain_chordal_base_chords=self.sustain_chordal_base_chords.value(),
            sustain_chordal_density_sensitivity=self.sustain_chordal_density_sensitivity.value(),
            sustain_chordal_onset_window_seconds=self.sustain_chordal_onset_window.value(),
            sustain_continuous_reactivation_every_chords=3,
            sustain_continuous_window_minutes=2.0,
        )
        self._enforce_frozen_ui_values(config)
        config.validate()
        return config

    def _set_ui_from_config(self, config: CleanerConfig) -> None:
        self.input_edit.setText(str(config.input_dir))
        self.output_edit.setText(str(config.output_dir))
        self.recursive_check.setChecked(config.recursive)
        idx = self.time_unit_combo.findData(config.time_unit)
        if idx >= 0:
            self.time_unit_combo.setCurrentIndex(idx)
        self.split_pitch.setValue(config.split_pitch)
        split_idx = self.hand_split_mode_combo.findData(config.hand_split_mode)
        if split_idx >= 0:
            self.hand_split_mode_combo.setCurrentIndex(split_idx)
        self.min_pitch.setValue(config.min_pitch)
        self.max_pitch.setValue(config.max_pitch)
        self.max_simultaneous.setValue(config.max_simultaneous_per_hand)
        self.max_hand_span.setValue(config.max_hand_span_semitones)
        self.min_move_delay.setValue(config.min_hand_move_delay_seconds)
        self.max_duration.setValue(config.max_duration_seconds)
        self.merge_gap.setValue(config.merge_gap_seconds)
        self.merge_min_duration.setValue(config.merge_min_duration_seconds)
        s_idx = self.sustain_mode.findData(config.sustain_mode)
        if s_idx >= 0:
            self.sustain_mode.setCurrentIndex(s_idx)
        self.sustain_every_beats.setValue(config.sustain_every_beats)
        self.sustain_gap_multiplier.setValue(config.sustain_gap_multiplier)
        self.sustain_min_hold.setValue(config.sustain_min_hold_seconds)
        self.sustain_max_hold.setValue(config.sustain_max_hold_seconds)
        self.sustain_release.setValue(config.sustain_release_before_next_seconds)
        self.sustain_hybrid_sparse_threshold.setValue(config.sustain_hybrid_sparse_cycle_note_threshold)
        self.sustain_hybrid_sparse_group.setValue(config.sustain_hybrid_max_sparse_cycle_group)
        self.sustain_hybrid_extra_hold.setValue(config.sustain_hybrid_extra_hold_seconds)
        self.sustain_hybrid_adaptive_boost.setValue(config.sustain_hybrid_adaptive_gap_boost)
        self.sustain_hybrid_release_factor.setValue(config.sustain_hybrid_release_factor)
        self.sustain_hybrid_merge_gap.setValue(config.sustain_hybrid_merge_gap_seconds)
        self.sustain_chordal_base_chords.setValue(config.sustain_chordal_base_chords)
        self.sustain_chordal_density_sensitivity.setValue(config.sustain_chordal_density_sensitivity)
        self.sustain_chordal_onset_window.setValue(config.sustain_chordal_onset_window_seconds)
        self.sustain_continuous_reactivate_chords.setValue(config.sustain_continuous_reactivation_every_chords)
        self.sustain_continuous_window_minutes.setValue(config.sustain_continuous_window_minutes)
        self._enforce_frozen_ui_values()
        self._refresh_time_unit_labels()
        self._refresh_sustain_control_visibility()
        self._sync_sustain_profile_from_values()

    def _enforce_frozen_ui_values(self, config: Optional[CleanerConfig] = None) -> None:
        if config is not None:
            config.time_unit = "mixed"
            config.hand_split_mode = "cost_based"
            config.sustain_mode = "continuous_reactive"
            config.sustain_continuous_reactivation_every_chords = 3
            config.sustain_continuous_window_minutes = 2.0

        self.time_unit_combo.setCurrentIndex(self.time_unit_combo.findData("mixed"))
        self.hand_split_mode_combo.setCurrentIndex(self.hand_split_mode_combo.findData("cost_based"))
        self.sustain_mode.setCurrentIndex(self.sustain_mode.findData("continuous_reactive"))
        self.sustain_continuous_reactivate_chords.setValue(3)
        self.sustain_continuous_window_minutes.setValue(2.0)

    def _refresh_time_unit_labels(self, _index: int = -1) -> None:
        unit_mode = str(self.time_unit_combo.currentData())
        if unit_mode == "beats":
            unit = "beats"
            mode_hint = "Interprete en beats"
        elif unit_mode == "seconds":
            unit = "secondes"
            mode_hint = "Interprete en secondes"
        else:
            unit = "secondes"
            mode_hint = "Mode mixte: ces champs restent en secondes (la grille periodique utilise les beats)"

        self.label_max_duration.setText(f"Duree max d'une note ({unit})")
        self.label_min_move_delay.setText(f"Delai mini pour bouger la main ({unit})")
        self.label_merge_gap.setText(f"Gap max fusion des repetitions ({unit})")
        self.label_merge_min_duration.setText(f"Duree mini pour fusion ({unit})")
        self.label_sustain_min_hold.setText(f"Duree min sustain ({unit})")
        self.label_sustain_max_hold.setText(f"Duree max sustain ({unit})")
        self.label_sustain_release.setText(f"Relache sustain avant prochain ({unit})")
        self.label_sustain_hybrid_extra_hold.setText(f"Hybride: tenue supplementaire sparse ({unit})")
        self.label_sustain_hybrid_merge_gap.setText(f"Hybride: gap fusion intervalles ({unit})")
        self.label_sustain_chordal_onset_window.setText(f"Accords adaptatif: fenetre regroupement accords ({unit})")

        common_tooltip = (
            f"{mode_hint}. Unite actuelle: {unit}. "
            "Champ influence par 'Unite temporelle'."
        )
        self.max_duration.setToolTip(common_tooltip)
        self.min_move_delay.setToolTip(common_tooltip)
        self.merge_gap.setToolTip(common_tooltip)
        self.merge_min_duration.setToolTip(common_tooltip)
        self.sustain_min_hold.setToolTip(common_tooltip)
        self.sustain_max_hold.setToolTip(common_tooltip)
        self.sustain_release.setToolTip(common_tooltip)
        self.sustain_hybrid_extra_hold.setToolTip(common_tooltip)
        self.sustain_hybrid_merge_gap.setToolTip(common_tooltip)
        self.sustain_chordal_onset_window.setToolTip(common_tooltip)

    def _set_sustain_advanced_visible(self, visible: bool) -> None:
        self.sustain_advanced_widget.setVisible(visible)

    def _on_sustain_profile_changed(self, _index: int) -> None:
        if self._applying_sustain_profile:
            return
        profile_id = str(self.sustain_profile_combo.currentData())
        if profile_id == SUSTAIN_PROFILE_CUSTOM:
            return
        self._apply_sustain_profile(profile_id)

    def _apply_sustain_profile(self, profile_id: str) -> None:
        profile = SUSTAIN_PROFILES.get(profile_id)
        if profile is None:
            return
        self._applying_sustain_profile = True
        try:
            mode_idx = self.sustain_mode.findData(profile["sustain_mode"])
            if mode_idx >= 0:
                self.sustain_mode.setCurrentIndex(mode_idx)
            self.sustain_every_beats.setValue(int(profile["sustain_every_beats"]))
            self.sustain_gap_multiplier.setValue(float(profile["sustain_gap_multiplier"]))
            self.sustain_min_hold.setValue(float(profile["sustain_min_hold_seconds"]))
            self.sustain_max_hold.setValue(float(profile["sustain_max_hold_seconds"]))
            self.sustain_release.setValue(float(profile["sustain_release_before_next_seconds"]))
            self.sustain_hybrid_sparse_threshold.setValue(int(profile["sustain_hybrid_sparse_cycle_note_threshold"]))
            self.sustain_hybrid_sparse_group.setValue(int(profile["sustain_hybrid_max_sparse_cycle_group"]))
            self.sustain_hybrid_extra_hold.setValue(float(profile["sustain_hybrid_extra_hold_seconds"]))
            self.sustain_hybrid_adaptive_boost.setValue(float(profile["sustain_hybrid_adaptive_gap_boost"]))
            self.sustain_hybrid_release_factor.setValue(float(profile["sustain_hybrid_release_factor"]))
            self.sustain_hybrid_merge_gap.setValue(float(profile["sustain_hybrid_merge_gap_seconds"]))
            self.sustain_chordal_base_chords.setValue(int(profile["sustain_chordal_base_chords"]))
            self.sustain_chordal_density_sensitivity.setValue(float(profile["sustain_chordal_density_sensitivity"]))
            self.sustain_chordal_onset_window.setValue(float(profile["sustain_chordal_onset_window_seconds"]))
            self.sustain_continuous_reactivate_chords.setValue(int(profile["sustain_continuous_reactivation_every_chords"]))
            self.sustain_continuous_window_minutes.setValue(float(profile["sustain_continuous_window_minutes"]))
        finally:
            self._applying_sustain_profile = False
        self._refresh_sustain_control_visibility()

    def _mark_sustain_profile_custom(self, *_args) -> None:
        if self._applying_sustain_profile:
            return
        idx = self.sustain_profile_combo.findData(SUSTAIN_PROFILE_CUSTOM)
        if idx >= 0 and self.sustain_profile_combo.currentIndex() != idx:
            self._applying_sustain_profile = True
            try:
                self.sustain_profile_combo.setCurrentIndex(idx)
            finally:
                self._applying_sustain_profile = False

    def _refresh_sustain_control_visibility(self, _index: int = -1) -> None:
        mode = str(self.sustain_mode.currentData())
        is_hybrid = mode == "hybrid"
        is_chordal = mode == "chordal"
        is_continuous_reactive = mode == "continuous_reactive"
        uses_periodic_grid = mode in {"periodic", "hybrid"}
        uses_adaptive = mode in {"adaptive", "hybrid"}
        uses_hold_window = mode in {"adaptive", "hybrid", "chordal", "continuous_reactive"}

        self.label_sustain_every_beats.setVisible(uses_periodic_grid)
        self.sustain_every_beats.setVisible(uses_periodic_grid)

        self.label_sustain_gap_multiplier.setVisible(uses_adaptive)
        self.sustain_gap_multiplier.setVisible(uses_adaptive)
        self.label_sustain_min_hold.setVisible(uses_hold_window)
        self.sustain_min_hold.setVisible(uses_hold_window)
        self.label_sustain_max_hold.setVisible(uses_hold_window)
        self.sustain_max_hold.setVisible(uses_hold_window)

        for label, widget in (
            (self.label_sustain_hybrid_sparse_threshold, self.sustain_hybrid_sparse_threshold),
            (self.label_sustain_hybrid_sparse_group, self.sustain_hybrid_sparse_group),
            (self.label_sustain_hybrid_extra_hold, self.sustain_hybrid_extra_hold),
            (self.label_sustain_hybrid_adaptive_boost, self.sustain_hybrid_adaptive_boost),
            (self.label_sustain_hybrid_release_factor, self.sustain_hybrid_release_factor),
            (self.label_sustain_hybrid_merge_gap, self.sustain_hybrid_merge_gap),
        ):
            label.setVisible(is_hybrid)
            widget.setVisible(is_hybrid)

        self.label_sustain_chordal_base_chords.setVisible(is_chordal)
        self.sustain_chordal_base_chords.setVisible(is_chordal)
        self.label_sustain_chordal_density_sensitivity.setVisible(is_chordal)
        self.sustain_chordal_density_sensitivity.setVisible(is_chordal)
        self.label_sustain_chordal_onset_window.setVisible(is_chordal)
        self.sustain_chordal_onset_window.setVisible(is_chordal)
        self.label_sustain_continuous_reactivate_chords.setVisible(is_continuous_reactive)
        self.sustain_continuous_reactivate_chords.setVisible(is_continuous_reactive)
        self.label_sustain_continuous_window_minutes.setVisible(is_continuous_reactive)
        self.sustain_continuous_window_minutes.setVisible(is_continuous_reactive)

    def _sync_sustain_profile_from_values(self) -> None:
        current = {
            "sustain_mode": str(self.sustain_mode.currentData()),
            "sustain_every_beats": self.sustain_every_beats.value(),
            "sustain_gap_multiplier": self.sustain_gap_multiplier.value(),
            "sustain_min_hold_seconds": self.sustain_min_hold.value(),
            "sustain_max_hold_seconds": self.sustain_max_hold.value(),
            "sustain_release_before_next_seconds": self.sustain_release.value(),
            "sustain_hybrid_sparse_cycle_note_threshold": self.sustain_hybrid_sparse_threshold.value(),
            "sustain_hybrid_max_sparse_cycle_group": self.sustain_hybrid_sparse_group.value(),
            "sustain_hybrid_extra_hold_seconds": self.sustain_hybrid_extra_hold.value(),
            "sustain_hybrid_adaptive_gap_boost": self.sustain_hybrid_adaptive_boost.value(),
            "sustain_hybrid_release_factor": self.sustain_hybrid_release_factor.value(),
            "sustain_hybrid_merge_gap_seconds": self.sustain_hybrid_merge_gap.value(),
            "sustain_chordal_base_chords": self.sustain_chordal_base_chords.value(),
            "sustain_chordal_density_sensitivity": self.sustain_chordal_density_sensitivity.value(),
            "sustain_chordal_onset_window_seconds": self.sustain_chordal_onset_window.value(),
            "sustain_continuous_reactivation_every_chords": self.sustain_continuous_reactivate_chords.value(),
            "sustain_continuous_window_minutes": self.sustain_continuous_window_minutes.value(),
        }
        matched_profile = SUSTAIN_PROFILE_CUSTOM
        for profile_id, profile_values in SUSTAIN_PROFILES.items():
            if str(profile_values["sustain_mode"]) != str(current["sustain_mode"]):
                continue
            if int(profile_values["sustain_every_beats"]) != int(current["sustain_every_beats"]):
                continue
            if int(profile_values["sustain_hybrid_sparse_cycle_note_threshold"]) != int(
                current["sustain_hybrid_sparse_cycle_note_threshold"]
            ):
                continue
            if int(profile_values["sustain_hybrid_max_sparse_cycle_group"]) != int(
                current["sustain_hybrid_max_sparse_cycle_group"]
            ):
                continue
            if int(profile_values["sustain_chordal_base_chords"]) != int(current["sustain_chordal_base_chords"]):
                continue
            if int(profile_values["sustain_continuous_reactivation_every_chords"]) != int(
                current["sustain_continuous_reactivation_every_chords"]
            ):
                continue
            float_keys = (
                "sustain_gap_multiplier",
                "sustain_min_hold_seconds",
                "sustain_max_hold_seconds",
                "sustain_release_before_next_seconds",
                "sustain_hybrid_extra_hold_seconds",
                "sustain_hybrid_adaptive_gap_boost",
                "sustain_hybrid_release_factor",
                "sustain_hybrid_merge_gap_seconds",
                "sustain_chordal_density_sensitivity",
                "sustain_chordal_onset_window_seconds",
                "sustain_continuous_window_minutes",
            )
            if all(abs(float(profile_values[k]) - float(current[k])) < 1e-6 for k in float_keys):
                matched_profile = profile_id
                break

        profile_idx = self.sustain_profile_combo.findData(matched_profile)
        if profile_idx >= 0:
            self._applying_sustain_profile = True
            try:
                self.sustain_profile_combo.setCurrentIndex(profile_idx)
            finally:
                self._applying_sustain_profile = False

    def _pick_directory(self, target: QLineEdit) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose directory", target.text() or str(Path.cwd()))
        if chosen:
            target.setText(chosen)

    def _append_log(self, line: str) -> None:
        level, formatted = normalize_log_line(line)
        at_bottom = self._is_log_at_bottom()
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        char_format = QTextCharFormat()
        char_format.setForeground(LOG_COLORS[level])
        cursor.insertText(formatted + "\n", char_format)
        if at_bottom:
            self._scroll_log_to_bottom()

    def _is_log_at_bottom(self) -> bool:
        bar = self.log_output.verticalScrollBar()
        return bar.value() >= (bar.maximum() - 2)

    def _scroll_log_to_bottom(self) -> None:
        bar = self.log_output.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _open_folder(self, folder: Path) -> None:
        if not str(folder).strip():
            return
        target = folder.expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _add_result_row(self, file_path: str, midi_status: str, details: str) -> None:
        midi_rank = 1 if midi_status == "FAILED" else 0
        combined_rank = (midi_rank, file_path)

        self.table.setSortingEnabled(False)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(file_path))
        midi_item = StatusTableItem(midi_status)
        midi_item.setData(256, combined_rank)
        self.table.setItem(row, 1, midi_item)
        self.table.setItem(row, 2, QTableWidgetItem(details))
        self.table.setSortingEnabled(True)
        self.table.scrollToItem(self.table.item(row, 0))

    def _set_running(self, running: bool) -> None:
        self.run_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.save_preset_btn.setEnabled(not running)
        self.load_preset_btn.setEnabled(not running)
        self.open_output_btn.setEnabled(not running)

    def _cancel_batch(self) -> None:
        if self._thread and self._thread.isRunning():
            self._cancel_event.set()
            self._append_log("[WARNING] Annulation demandee...")

    def _run_batch(self) -> None:
        try:
            config = self._build_config_from_ui()
        except Exception as exc:
            QMessageBox.critical(self, "Configuration invalide", str(exc))
            return
        input_dir = config.input_dir.expanduser().resolve()
        output_dir = config.output_dir.expanduser().resolve()
        if not input_dir.exists() or not input_dir.is_dir():
            QMessageBox.critical(self, "Source invalide", f"Dossier source introuvable:\n{input_dir}")
            return
        if input_dir == output_dir:
            QMessageBox.critical(self, "Sortie invalide", "Les dossiers source et sortie doivent etre differents.")
            return
        config.input_dir = input_dir
        config.output_dir = output_dir
        self.table.setRowCount(0)
        self.table.sortItems(0, Qt.AscendingOrder)
        self.log_output.clear()
        self.progress_bar.setValue(0)
        self.progress_label.setText("0 / 0")
        self._set_running(True)
        self._cancel_event.clear()
        self._persist_settings()
        self._append_log("[INFO] Demarrage nettoyage MIDI...")

        self._thread = QThread(self)
        self._worker = CleanerWorker(config=config, cancel_event=self._cancel_event)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self._append_log)
        self._worker.row.connect(self._add_result_row)
        self._worker.done.connect(self._on_done)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    def _on_progress(self, current: int, total: int) -> None:
        if total <= 0:
            self.progress_bar.setValue(0)
            self.progress_label.setText("0 / 0")
            return
        self.progress_bar.setValue(int((current / total) * 100))
        self.progress_label.setText(f"{current} / {total}")

    def _on_done(self, total: int, processed: int, failed: int, canceled: bool) -> None:
        self._set_running(False)
        summary_prefix = "Annule" if canceled else "Termine"
        self._append_log(f"{summary_prefix}. total={total}, processed={processed}, failed={failed}")
        QMessageBox.information(
            self,
            "Traitement termine",
            (
                f"Status: {summary_prefix}\n"
                f"Files: {total}\n"
                f"Processed: {processed}\n"
                f"Failed: {failed}"
            ),
        )
        self._thread = None
        self._worker = None

    def _save_preset(self) -> None:
        config = self._build_config_from_ui()
        preset = {
            "cleaner_config": config.as_json_dict(),
        }
        target, _ = QFileDialog.getSaveFileName(self, "Save preset", "preset.json", "JSON (*.json)")
        if not target:
            return
        Path(target).write_text(json.dumps(preset, indent=2), encoding="utf-8")
        self._append_log(f"Preset saved: {target}")

    def _load_preset(self) -> None:
        src, _ = QFileDialog.getOpenFileName(self, "Load preset", "", "JSON (*.json)")
        if not src:
            return
        try:
            data = json.loads(Path(src).read_text(encoding="utf-8"))
            config = CleanerConfig.from_json_dict(data["cleaner_config"])
            self._set_ui_from_config(config)
            self._append_log(f"Preset loaded: {src}")
            self._persist_settings()
        except Exception as exc:
            QMessageBox.critical(self, "Load preset failed", str(exc))

    def _persist_settings(self) -> None:
        config = self._build_config_from_ui()
        self.settings.setValue("cleaner_config", json.dumps(config.as_json_dict()))

    def _load_settings(self) -> None:
        raw_cfg = self.settings.value("cleaner_config", "")
        if raw_cfg:
            try:
                cfg = CleanerConfig.from_json_dict(json.loads(str(raw_cfg)))
                self._set_ui_from_config(cfg)
            except Exception:
                pass

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self._persist_settings()
        except Exception:
            pass
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()

