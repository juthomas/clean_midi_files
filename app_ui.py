#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
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
    QPlainTextEdit,
    QProgressBar,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from midi_cleaner.config import CleanerConfig
from midi_cleaner.core import FileProcessResult, format_stats, process_batch
from midi_cleaner.score_export import export_midi_to_pdf


@dataclass
class PdfOptions:
    enabled: bool
    output_dir: Path
    lilypond_binary: str


class CleanerWorker(QObject):
    progress = Signal(int, int)
    log = Signal(str)
    row = Signal(str, str, str, str)
    done = Signal(int, int, int, int, int)

    def __init__(self, config: CleanerConfig, pdf_options: PdfOptions) -> None:
        super().__init__()
        self.config = config
        self.pdf_options = pdf_options

    def run(self) -> None:
        pdf_ok = 0
        pdf_failed = 0

        def on_file_complete(result: FileProcessResult, index: int, total: int) -> None:
            nonlocal pdf_ok, pdf_failed
            self.progress.emit(index, total)
            if result.success and result.stats:
                midi_status = "OK"
                detail = format_stats(result.relative_path, result.stats)
                pdf_status = "-"
                if self.pdf_options.enabled:
                    pdf_path = (self.pdf_options.output_dir / result.relative_path).with_suffix(".pdf")
                    pdf_result = export_midi_to_pdf(
                        midi_path=result.output_path,
                        pdf_path=pdf_path,
                        lilypond_binary=self.pdf_options.lilypond_binary,
                    )
                    if pdf_result.success:
                        pdf_status = "OK"
                        pdf_ok += 1
                    else:
                        pdf_status = "FAILED"
                        pdf_failed += 1
                        detail = f"{detail} | pdf_error={pdf_result.error}"
                self.row.emit(str(result.relative_path), midi_status, pdf_status, detail)
                self.log.emit(detail)
            else:
                midi_status = "FAILED"
                pdf_status = "-"
                detail = result.error
                self.row.emit(str(result.relative_path), midi_status, pdf_status, detail)
                self.log.emit(f"[WARN] {result.relative_path}: {result.error}")

        batch = process_batch(self.config, on_file_complete=on_file_complete)
        self.done.emit(
            batch.total_files,
            batch.processed_count,
            batch.failed_count,
            pdf_ok,
            pdf_failed,
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MIDI Cleaner UI")
        self.resize(1200, 820)
        self._thread: Optional[QThread] = None
        self._worker: Optional[CleanerWorker] = None
        self._build_ui()
        self._load_defaults()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)

        path_group = QGroupBox("Folders")
        path_layout = QGridLayout(path_group)
        self.input_edit = QLineEdit()
        self.output_edit = QLineEdit()
        self.pdf_output_edit = QLineEdit()
        input_btn = QPushButton("Browse...")
        output_btn = QPushButton("Browse...")
        pdf_output_btn = QPushButton("Browse...")
        input_btn.clicked.connect(lambda: self._pick_directory(self.input_edit))
        output_btn.clicked.connect(lambda: self._pick_directory(self.output_edit))
        pdf_output_btn.clicked.connect(lambda: self._pick_directory(self.pdf_output_edit))
        path_layout.addWidget(QLabel("Input directory"), 0, 0)
        path_layout.addWidget(self.input_edit, 0, 1)
        path_layout.addWidget(input_btn, 0, 2)
        path_layout.addWidget(QLabel("Output directory"), 1, 0)
        path_layout.addWidget(self.output_edit, 1, 1)
        path_layout.addWidget(output_btn, 1, 2)
        path_layout.addWidget(QLabel("PDF output directory"), 2, 0)
        path_layout.addWidget(self.pdf_output_edit, 2, 1)
        path_layout.addWidget(pdf_output_btn, 2, 2)
        root_layout.addWidget(path_group)

        options_layout = QHBoxLayout()
        options_layout.addWidget(self._build_general_group())
        options_layout.addWidget(self._build_playability_group())
        options_layout.addWidget(self._build_sustain_group())
        root_layout.addLayout(options_layout)

        buttons_layout = QHBoxLayout()
        self.run_btn = QPushButton("Run batch")
        self.run_btn.clicked.connect(self._run_batch)
        self.save_preset_btn = QPushButton("Save preset")
        self.load_preset_btn = QPushButton("Load preset")
        self.save_preset_btn.clicked.connect(self._save_preset)
        self.load_preset_btn.clicked.connect(self._load_preset)
        buttons_layout.addWidget(self.run_btn)
        buttons_layout.addWidget(self.save_preset_btn)
        buttons_layout.addWidget(self.load_preset_btn)
        buttons_layout.addStretch(1)
        root_layout.addLayout(buttons_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        root_layout.addWidget(self.progress_bar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["File", "MIDI", "PDF", "Details"])
        self.table.horizontalHeader().setStretchLastSection(True)
        root_layout.addWidget(self.table, stretch=2)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        root_layout.addWidget(self.log_output, stretch=1)
        self.setCentralWidget(root)

    def _build_general_group(self) -> QGroupBox:
        group = QGroupBox("General")
        form = QFormLayout(group)
        self.recursive_check = QCheckBox("Recursive")
        self.recursive_check.setChecked(True)
        self.time_unit_combo = QComboBox()
        self.time_unit_combo.addItems(["mixed", "seconds", "beats"])
        self.split_pitch = QSpinBox()
        self.split_pitch.setRange(0, 127)
        self.min_pitch = QSpinBox()
        self.min_pitch.setRange(0, 127)
        self.max_pitch = QSpinBox()
        self.max_pitch.setRange(0, 127)
        self.max_duration = QDoubleSpinBox()
        self.max_duration.setDecimals(3)
        self.max_duration.setRange(0.001, 9999.0)
        self.max_duration.setSingleStep(0.05)
        form.addRow(self.recursive_check)
        form.addRow("Time unit", self.time_unit_combo)
        form.addRow("Split pitch", self.split_pitch)
        form.addRow("Min pitch", self.min_pitch)
        form.addRow("Max pitch", self.max_pitch)
        form.addRow("Max duration", self.max_duration)
        return group

    def _build_playability_group(self) -> QGroupBox:
        group = QGroupBox("Playability")
        form = QFormLayout(group)
        self.max_simultaneous = QSpinBox()
        self.max_simultaneous.setRange(1, 10)
        self.max_hand_span = QSpinBox()
        self.max_hand_span.setRange(1, 48)
        self.min_move_delay = QDoubleSpinBox()
        self.min_move_delay.setDecimals(3)
        self.min_move_delay.setRange(0.0, 60.0)
        self.min_move_delay.setSingleStep(0.01)
        self.merge_gap = QDoubleSpinBox()
        self.merge_gap.setDecimals(3)
        self.merge_gap.setRange(0.0, 60.0)
        self.merge_gap.setSingleStep(0.01)
        self.merge_min_duration = QDoubleSpinBox()
        self.merge_min_duration.setDecimals(3)
        self.merge_min_duration.setRange(0.0, 60.0)
        self.merge_min_duration.setSingleStep(0.01)
        form.addRow("Max simultaneous / hand", self.max_simultaneous)
        form.addRow("Max hand span (semitones)", self.max_hand_span)
        form.addRow("Min hand move delay", self.min_move_delay)
        form.addRow("Merge gap", self.merge_gap)
        form.addRow("Merge min duration", self.merge_min_duration)
        return group

    def _build_sustain_group(self) -> QGroupBox:
        group = QGroupBox("Sustain + PDF")
        form = QFormLayout(group)
        self.sustain_mode = QComboBox()
        self.sustain_mode.addItems(["adaptive", "periodic"])
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
        self.pdf_enabled = QCheckBox("Export PDF")
        self.pdf_enabled.setChecked(False)
        self.lilypond_binary = QLineEdit()
        form.addRow("Sustain mode", self.sustain_mode)
        form.addRow("Sustain every beats", self.sustain_every_beats)
        form.addRow("Sustain gap multiplier", self.sustain_gap_multiplier)
        form.addRow("Sustain min hold", self.sustain_min_hold)
        form.addRow("Sustain max hold", self.sustain_max_hold)
        form.addRow("Sustain release", self.sustain_release)
        form.addRow(self.pdf_enabled)
        form.addRow("LilyPond binary", self.lilypond_binary)
        return group

    def _load_defaults(self) -> None:
        config = CleanerConfig(input_dir=Path("input_midi"), output_dir=Path("output_midi"))
        self._set_ui_from_config(config)
        self.pdf_output_edit.setText(str(Path("output_pdf")))
        self.lilypond_binary.setText("lilypond")

    def _build_config_from_ui(self) -> CleanerConfig:
        return CleanerConfig(
            input_dir=Path(self.input_edit.text().strip()),
            output_dir=Path(self.output_edit.text().strip()),
            recursive=self.recursive_check.isChecked(),
            time_unit=self.time_unit_combo.currentText(),
            split_pitch=self.split_pitch.value(),
            min_pitch=self.min_pitch.value(),
            max_pitch=self.max_pitch.value(),
            max_simultaneous_per_hand=self.max_simultaneous.value(),
            max_hand_span_semitones=self.max_hand_span.value(),
            min_hand_move_delay_seconds=self.min_move_delay.value(),
            max_duration_seconds=self.max_duration.value(),
            merge_gap_seconds=self.merge_gap.value(),
            merge_min_duration_seconds=self.merge_min_duration.value(),
            sustain_mode=self.sustain_mode.currentText(),
            sustain_every_beats=self.sustain_every_beats.value(),
            sustain_gap_multiplier=self.sustain_gap_multiplier.value(),
            sustain_min_hold_seconds=self.sustain_min_hold.value(),
            sustain_max_hold_seconds=self.sustain_max_hold.value(),
            sustain_release_before_next_seconds=self.sustain_release.value(),
        )

    def _set_ui_from_config(self, config: CleanerConfig) -> None:
        self.input_edit.setText(str(config.input_dir))
        self.output_edit.setText(str(config.output_dir))
        self.recursive_check.setChecked(config.recursive)
        self.time_unit_combo.setCurrentText(config.time_unit)
        self.split_pitch.setValue(config.split_pitch)
        self.min_pitch.setValue(config.min_pitch)
        self.max_pitch.setValue(config.max_pitch)
        self.max_simultaneous.setValue(config.max_simultaneous_per_hand)
        self.max_hand_span.setValue(config.max_hand_span_semitones)
        self.min_move_delay.setValue(config.min_hand_move_delay_seconds)
        self.max_duration.setValue(config.max_duration_seconds)
        self.merge_gap.setValue(config.merge_gap_seconds)
        self.merge_min_duration.setValue(config.merge_min_duration_seconds)
        self.sustain_mode.setCurrentText(config.sustain_mode)
        self.sustain_every_beats.setValue(config.sustain_every_beats)
        self.sustain_gap_multiplier.setValue(config.sustain_gap_multiplier)
        self.sustain_min_hold.setValue(config.sustain_min_hold_seconds)
        self.sustain_max_hold.setValue(config.sustain_max_hold_seconds)
        self.sustain_release.setValue(config.sustain_release_before_next_seconds)

    def _pick_directory(self, target: QLineEdit) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose directory", target.text() or str(Path.cwd()))
        if chosen:
            target.setText(chosen)

    def _append_log(self, line: str) -> None:
        self.log_output.appendPlainText(line)

    def _add_result_row(self, file_path: str, midi_status: str, pdf_status: str, details: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(file_path))
        self.table.setItem(row, 1, QTableWidgetItem(midi_status))
        self.table.setItem(row, 2, QTableWidgetItem(pdf_status))
        self.table.setItem(row, 3, QTableWidgetItem(details))

    def _set_running(self, running: bool) -> None:
        self.run_btn.setEnabled(not running)
        self.save_preset_btn.setEnabled(not running)
        self.load_preset_btn.setEnabled(not running)

    def _run_batch(self) -> None:
        config = self._build_config_from_ui()
        if not config.input_dir.exists() or not config.input_dir.is_dir():
            QMessageBox.critical(self, "Invalid input", f"Input directory not found:\n{config.input_dir}")
            return
        pdf_options = PdfOptions(
            enabled=self.pdf_enabled.isChecked(),
            output_dir=Path(self.pdf_output_edit.text().strip() or "output_pdf"),
            lilypond_binary=self.lilypond_binary.text().strip() or "lilypond",
        )
        self.table.setRowCount(0)
        self.log_output.clear()
        self.progress_bar.setValue(0)
        self._set_running(True)

        self._thread = QThread(self)
        self._worker = CleanerWorker(config=config, pdf_options=pdf_options)
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
            return
        self.progress_bar.setValue(int((current / total) * 100))

    def _on_done(self, total: int, processed: int, failed: int, pdf_ok: int, pdf_failed: int) -> None:
        self._set_running(False)
        self._append_log(
            f"Done. total={total}, processed={processed}, failed={failed}, pdf_ok={pdf_ok}, pdf_failed={pdf_failed}"
        )
        QMessageBox.information(
            self,
            "Batch finished",
            (
                f"Files: {total}\n"
                f"Processed: {processed}\n"
                f"Failed: {failed}\n"
                f"PDF ok: {pdf_ok}\n"
                f"PDF failed: {pdf_failed}"
            ),
        )
        self._thread = None
        self._worker = None

    def _save_preset(self) -> None:
        config = self._build_config_from_ui()
        preset = {
            "cleaner_config": config.as_json_dict(),
            "pdf_enabled": self.pdf_enabled.isChecked(),
            "pdf_output_dir": self.pdf_output_edit.text().strip(),
            "lilypond_binary": self.lilypond_binary.text().strip(),
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
            self._append_log(f"Preset loaded: {src}")
        except Exception as exc:
            QMessageBox.critical(self, "Load preset failed", str(exc))


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()

