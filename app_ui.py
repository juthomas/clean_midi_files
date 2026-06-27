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
from midi_cleaner.score_export import (
    export_directory_to_pdf,
    export_midi_to_pdf,
    find_lilypond_binary,
)


@dataclass
class PdfOptions:
    enabled: bool
    output_dir: Path
    lilypond_binary: str
    skip_if_missing: bool


LOG_COLORS = {
    "INFO": QColor("#89D185"),
    "WARNING": QColor("#F5C16C"),
    "ERROR": QColor("#F28B82"),
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
    row = Signal(str, str, str, str)
    done = Signal(int, int, int, int, int, bool)

    def __init__(self, config: CleanerConfig, pdf_options: PdfOptions, cancel_event: threading.Event) -> None:
        super().__init__()
        self.config = config
        self.pdf_options = pdf_options
        self.cancel_event = cancel_event

    def run(self) -> None:
        pdf_ok = 0
        pdf_failed = 0
        pdf_enabled = self.pdf_options.enabled
        lilypond_resolved = find_lilypond_binary(self.pdf_options.lilypond_binary) if pdf_enabled else None
        if pdf_enabled and lilypond_resolved is None:
            if self.pdf_options.skip_if_missing:
                self.log.emit(
                    f"[WARNING] LilyPond not found ({self.pdf_options.lilypond_binary}). "
                    "Skipping PDF export for this run."
                )
                pdf_enabled = False
            else:
                self.log.emit(f"[ERROR] LilyPond not found: {self.pdf_options.lilypond_binary}")

        def on_file_complete(result: FileProcessResult, index: int, total: int) -> None:
            nonlocal pdf_ok, pdf_failed
            self.progress.emit(index, total)
            if result.success and result.stats:
                midi_status = "OK"
                detail = format_stats(result.relative_path, result.stats)
                pdf_status = "-"
                if pdf_enabled:
                    pdf_path = (self.pdf_options.output_dir / result.relative_path).with_suffix(".pdf")
                    pdf_result = export_midi_to_pdf(
                        midi_path=result.output_path,
                        pdf_path=pdf_path,
                        lilypond_binary=str(lilypond_resolved),
                    )
                    if pdf_result.success:
                        pdf_status = "OK"
                        pdf_ok += 1
                    else:
                        pdf_status = "FAILED"
                        pdf_failed += 1
                        detail = f"{detail} | pdf_error={pdf_result.error}"
                self.row.emit(str(result.relative_path), midi_status, pdf_status, detail)
                self.log.emit(f"[INFO] {detail}")
            else:
                midi_status = "FAILED"
                pdf_status = "-"
                detail = result.error
                self.row.emit(str(result.relative_path), midi_status, pdf_status, detail)
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
            pdf_ok,
            pdf_failed,
            batch.canceled,
        )


class PdfOnlyWorker(QObject):
    progress = Signal(int, int)
    log = Signal(str)
    row = Signal(str, str, str, str)
    done = Signal(int, int, int, int, int, bool)

    def __init__(self, midi_input_dir: Path, pdf_options: PdfOptions, recursive: bool, cancel_event: threading.Event) -> None:
        super().__init__()
        self.midi_input_dir = midi_input_dir
        self.pdf_options = pdf_options
        self.recursive = recursive
        self.cancel_event = cancel_event

    def run(self) -> None:
        pdf_ok = 0
        pdf_failed = 0
        lilypond_resolved = find_lilypond_binary(self.pdf_options.lilypond_binary)
        if lilypond_resolved is None:
            if self.pdf_options.skip_if_missing:
                self.log.emit(
                    f"[WARNING] LilyPond not found ({self.pdf_options.lilypond_binary}). "
                    "PDF generation skipped."
                )
                self.done.emit(0, 0, 0, 0, 0, False)
                return
            self.log.emit(f"[ERROR] LilyPond not found: {self.pdf_options.lilypond_binary}")
            self.done.emit(0, 0, 0, 0, 0, False)
            return

        def on_file_complete(item, index: int, total: int) -> None:
            nonlocal pdf_ok, pdf_failed
            self.progress.emit(index, total)
            rel = str(item.relative_path or item.midi_path.name)
            midi_status = "N/A"
            if item.success:
                pdf_status = "OK"
                pdf_ok += 1
                detail = f"[INFO] {rel} -> PDF OK"
            else:
                pdf_status = "FAILED"
                pdf_failed += 1
                detail = f"[WARNING] {rel}: {item.error}"
            self.row.emit(rel, midi_status, pdf_status, detail.replace("[INFO] ", "").replace("[WARNING] ", ""))
            self.log.emit(detail)

        batch = export_directory_to_pdf(
            midi_input_dir=self.midi_input_dir,
            pdf_output_dir=self.pdf_options.output_dir,
            lilypond_binary=str(lilypond_resolved),
            recursive=self.recursive,
            on_file_complete=on_file_complete,
            should_cancel=self.cancel_event.is_set,
        )
        self.done.emit(
            batch.total_files,
            batch.processed_count,
            batch.failed_count,
            pdf_ok,
            pdf_failed,
            batch.canceled,
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Nettoyeur MIDI")
        self.resize(1200, 820)
        self._thread: Optional[QThread] = None
        self._worker: Optional[CleanerWorker] = None
        self._pdf_worker: Optional[PdfOnlyWorker] = None
        self._cancel_event = threading.Event()
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
        self.pdf_output_edit = QLineEdit()
        input_btn = QPushButton("Parcourir...")
        output_btn = QPushButton("Parcourir...")
        pdf_output_btn = QPushButton("Parcourir...")
        input_btn.clicked.connect(lambda: self._pick_directory(self.input_edit))
        output_btn.clicked.connect(lambda: self._pick_directory(self.output_edit))
        pdf_output_btn.clicked.connect(lambda: self._pick_directory(self.pdf_output_edit))
        path_layout.addWidget(QLabel("Dossier source MIDI"), 0, 0)
        path_layout.addWidget(self.input_edit, 0, 1)
        path_layout.addWidget(input_btn, 0, 2)
        path_layout.addWidget(QLabel("Dossier sortie MIDI"), 1, 0)
        path_layout.addWidget(self.output_edit, 1, 1)
        path_layout.addWidget(output_btn, 1, 2)
        path_layout.addWidget(QLabel("Dossier sortie Partition PDF"), 2, 0)
        path_layout.addWidget(self.pdf_output_edit, 2, 1)
        path_layout.addWidget(pdf_output_btn, 2, 2)
        root_layout.addWidget(path_group)

        options_layout = QHBoxLayout()
        options_layout.addWidget(self._build_general_group())
        options_layout.addWidget(self._build_playability_group())
        options_layout.addWidget(self._build_sustain_group())
        root_layout.addLayout(options_layout)
        root_layout.addWidget(self._build_pdf_group())

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

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Fichier", "Statut MIDI", "Statut PDF", "Details"])
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
        form.addRow("Unite temporelle", self.time_unit_combo)
        form.addRow("Separation main gauche/droite (pitch MIDI)", self.split_pitch)
        form.addRow("Strategie separation mains", self.hand_split_mode_combo)
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
        self.sustain_mode = QComboBox()
        self.sustain_mode.addItem("Adaptatif", "adaptive")
        self.sustain_mode.addItem("Periodique", "periodic")
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
        form.addRow("Mode sustain", self.sustain_mode)
        form.addRow("Sustain tous les N beats (beats)", self.sustain_every_beats)
        form.addRow("Multiplicateur gap sustain", self.sustain_gap_multiplier)
        self.label_sustain_min_hold = QLabel("Duree min sustain")
        self.label_sustain_max_hold = QLabel("Duree max sustain")
        self.label_sustain_release = QLabel("Relache sustain avant prochain")
        form.addRow(self.label_sustain_min_hold, self.sustain_min_hold)
        form.addRow(self.label_sustain_max_hold, self.sustain_max_hold)
        form.addRow(self.label_sustain_release, self.sustain_release)
        return group

    def _build_pdf_group(self) -> QGroupBox:
        group = QGroupBox("Generation Partition PDF")
        form = QFormLayout(group)
        self.pdf_enabled = QCheckBox("Exporter PDF pendant nettoyage")
        self.pdf_enabled.setChecked(False)
        self.pdf_skip_if_missing = QCheckBox("Ignorer PDF si LilyPond absent")
        self.pdf_skip_if_missing.setChecked(True)
        self.lilypond_binary = QLineEdit()
        self.lilypond_binary.setToolTip("Nom ou chemin complet du binaire LilyPond")
        self.pdf_only_btn = QPushButton("Generer PDF depuis sorties MIDI")
        self.pdf_only_btn.clicked.connect(self._run_pdf_only)
        self.open_pdf_output_btn = QPushButton("Ouvrir dossier Partition PDF")
        self.open_pdf_output_btn.clicked.connect(lambda: self._open_folder(Path(self.pdf_output_edit.text().strip())))
        form.addRow(self.pdf_enabled)
        form.addRow(self.pdf_skip_if_missing)
        form.addRow("Binaire LilyPond", self.lilypond_binary)
        form.addRow(self.pdf_only_btn)
        form.addRow(self.open_pdf_output_btn)
        return group

    def _load_defaults(self) -> None:
        project_dir = Path(__file__).resolve().parent
        default_input = project_dir / "input_midi" if (project_dir / "input_midi").exists() else Path.home() / "input_midi"
        default_output = project_dir / "output_midi"
        config = CleanerConfig(input_dir=default_input, output_dir=default_output)
        self._set_ui_from_config(config)
        self.pdf_output_edit.setText(str((project_dir / "output_pdf").resolve()))
        self.lilypond_binary.setText("lilypond")
        self._refresh_time_unit_labels()

    def _build_config_from_ui(self) -> CleanerConfig:
        config = CleanerConfig(
            input_dir=Path(self.input_edit.text().strip()),
            output_dir=Path(self.output_edit.text().strip()),
            recursive=self.recursive_check.isChecked(),
            time_unit=str(self.time_unit_combo.currentData()),
            split_pitch=self.split_pitch.value(),
            hand_split_mode=str(self.hand_split_mode_combo.currentData()),
            min_pitch=self.min_pitch.value(),
            max_pitch=self.max_pitch.value(),
            max_simultaneous_per_hand=self.max_simultaneous.value(),
            max_hand_span_semitones=self.max_hand_span.value(),
            min_hand_move_delay_seconds=self.min_move_delay.value(),
            max_duration_seconds=self.max_duration.value(),
            merge_gap_seconds=self.merge_gap.value(),
            merge_min_duration_seconds=self.merge_min_duration.value(),
            sustain_mode=str(self.sustain_mode.currentData()),
            sustain_every_beats=self.sustain_every_beats.value(),
            sustain_gap_multiplier=self.sustain_gap_multiplier.value(),
            sustain_min_hold_seconds=self.sustain_min_hold.value(),
            sustain_max_hold_seconds=self.sustain_max_hold.value(),
            sustain_release_before_next_seconds=self.sustain_release.value(),
        )
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
        self._refresh_time_unit_labels()

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

    def _add_result_row(self, file_path: str, midi_status: str, pdf_status: str, details: str) -> None:
        midi_rank = 1 if midi_status == "FAILED" else 0
        pdf_rank = 1 if pdf_status == "FAILED" else 0
        combined_rank = (midi_rank, pdf_rank, file_path)

        self.table.setSortingEnabled(False)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(file_path))
        midi_item = StatusTableItem(midi_status)
        midi_item.setData(256, combined_rank)
        pdf_item = StatusTableItem(pdf_status)
        pdf_item.setData(256, (pdf_rank, midi_rank, file_path))
        self.table.setItem(row, 1, midi_item)
        self.table.setItem(row, 2, pdf_item)
        self.table.setItem(row, 3, QTableWidgetItem(details))
        self.table.setSortingEnabled(True)
        self.table.scrollToItem(self.table.item(row, 0))

    def _set_running(self, running: bool) -> None:
        self.run_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.pdf_only_btn.setEnabled(not running)
        self.save_preset_btn.setEnabled(not running)
        self.load_preset_btn.setEnabled(not running)
        self.open_output_btn.setEnabled(not running)
        self.open_pdf_output_btn.setEnabled(not running)

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
        pdf_options = PdfOptions(
            enabled=self.pdf_enabled.isChecked(),
            output_dir=Path(self.pdf_output_edit.text().strip() or str(Path.home() / "output_pdf")).expanduser().resolve(),
            lilypond_binary=self.lilypond_binary.text().strip() or "lilypond",
            skip_if_missing=self.pdf_skip_if_missing.isChecked(),
        )
        if pdf_options.enabled and find_lilypond_binary(pdf_options.lilypond_binary) is None and not pdf_options.skip_if_missing:
            QMessageBox.critical(
                self,
                "LilyPond absent",
                f"LilyPond introuvable: {pdf_options.lilypond_binary}\nActive le mode skip ou installe LilyPond.",
            )
            return
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
        self._worker = CleanerWorker(config=config, pdf_options=pdf_options, cancel_event=self._cancel_event)
        self._pdf_worker = None
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

    def _run_pdf_only(self) -> None:
        midi_input_dir = Path(self.output_edit.text().strip()).expanduser().resolve()
        if not midi_input_dir.exists() or not midi_input_dir.is_dir():
            QMessageBox.critical(self, "Source PDF invalide", f"Dossier MIDI source introuvable:\n{midi_input_dir}")
            return
        pdf_options = PdfOptions(
            enabled=True,
            output_dir=Path(self.pdf_output_edit.text().strip() or str(Path.home() / "output_pdf")).expanduser().resolve(),
            lilypond_binary=self.lilypond_binary.text().strip() or "lilypond",
            skip_if_missing=self.pdf_skip_if_missing.isChecked(),
        )
        if find_lilypond_binary(pdf_options.lilypond_binary) is None and not pdf_options.skip_if_missing:
            QMessageBox.critical(
                self,
                "LilyPond absent",
                f"LilyPond introuvable: {pdf_options.lilypond_binary}",
            )
            return
        self.table.setRowCount(0)
        self.table.sortItems(0, Qt.AscendingOrder)
        self.log_output.clear()
        self.progress_bar.setValue(0)
        self.progress_label.setText("0 / 0")
        self._set_running(True)
        self._cancel_event.clear()
        self._persist_settings()
        self._append_log(f"[INFO] Demarrage generation PDF depuis {midi_input_dir}")

        self._thread = QThread(self)
        self._worker = None
        self._pdf_worker = PdfOnlyWorker(
            midi_input_dir=midi_input_dir,
            pdf_options=pdf_options,
            recursive=self.recursive_check.isChecked(),
            cancel_event=self._cancel_event,
        )
        self._pdf_worker.moveToThread(self._thread)
        self._thread.started.connect(self._pdf_worker.run)
        self._pdf_worker.progress.connect(self._on_progress)
        self._pdf_worker.log.connect(self._append_log)
        self._pdf_worker.row.connect(self._add_result_row)
        self._pdf_worker.done.connect(self._on_done)
        self._pdf_worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._pdf_worker.deleteLater)
        self._thread.start()

    def _on_progress(self, current: int, total: int) -> None:
        if total <= 0:
            self.progress_bar.setValue(0)
            self.progress_label.setText("0 / 0")
            return
        self.progress_bar.setValue(int((current / total) * 100))
        self.progress_label.setText(f"{current} / {total}")

    def _on_done(self, total: int, processed: int, failed: int, pdf_ok: int, pdf_failed: int, canceled: bool) -> None:
        self._set_running(False)
        summary_prefix = "Annule" if canceled else "Termine"
        self._append_log(
            f"{summary_prefix}. total={total}, processed={processed}, failed={failed}, "
            f"pdf_ok={pdf_ok}, pdf_failed={pdf_failed}"
        )
        QMessageBox.information(
            self,
            "Traitement termine",
            (
                f"Status: {summary_prefix}\n"
                f"Files: {total}\n"
                f"Processed: {processed}\n"
                f"Failed: {failed}\n"
                f"PDF ok: {pdf_ok}\n"
                f"PDF failed: {pdf_failed}"
            ),
        )
        self._thread = None
        self._worker = None
        self._pdf_worker = None

    def _save_preset(self) -> None:
        config = self._build_config_from_ui()
        preset = {
            "cleaner_config": config.as_json_dict(),
            "pdf_enabled": self.pdf_enabled.isChecked(),
            "pdf_output_dir": self.pdf_output_edit.text().strip(),
            "lilypond_binary": self.lilypond_binary.text().strip(),
            "pdf_skip_if_missing": self.pdf_skip_if_missing.isChecked(),
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
            self.pdf_enabled.setChecked(bool(data.get("pdf_enabled", False)))
            self.pdf_output_edit.setText(str(data.get("pdf_output_dir", "output_pdf")))
            self.lilypond_binary.setText(str(data.get("lilypond_binary", "lilypond")))
            self.pdf_skip_if_missing.setChecked(bool(data.get("pdf_skip_if_missing", True)))
            self._append_log(f"Preset loaded: {src}")
            self._persist_settings()
        except Exception as exc:
            QMessageBox.critical(self, "Load preset failed", str(exc))

    def _persist_settings(self) -> None:
        config = self._build_config_from_ui()
        self.settings.setValue("cleaner_config", json.dumps(config.as_json_dict()))
        self.settings.setValue("pdf_enabled", self.pdf_enabled.isChecked())
        self.settings.setValue("pdf_output_dir", self.pdf_output_edit.text().strip())
        self.settings.setValue("lilypond_binary", self.lilypond_binary.text().strip())
        self.settings.setValue("pdf_skip_if_missing", self.pdf_skip_if_missing.isChecked())

    def _load_settings(self) -> None:
        raw_cfg = self.settings.value("cleaner_config", "")
        if raw_cfg:
            try:
                cfg = CleanerConfig.from_json_dict(json.loads(str(raw_cfg)))
                self._set_ui_from_config(cfg)
            except Exception:
                pass
        self.pdf_enabled.setChecked(self.settings.value("pdf_enabled", False, type=bool))
        self.pdf_output_edit.setText(str(self.settings.value("pdf_output_dir", self.pdf_output_edit.text())))
        self.lilypond_binary.setText(str(self.settings.value("lilypond_binary", self.lilypond_binary.text())))
        self.pdf_skip_if_missing.setChecked(self.settings.value("pdf_skip_if_missing", True, type=bool))

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

