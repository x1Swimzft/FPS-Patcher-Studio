"""Modal MP4 forensic analyzer dialog with a background comparison worker."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings
from ..core.forensic_analyzer import (
    ForensicDiffResult,
    MP4ForensicAnalyzer,
    MP4ForensicReport,
    compare_mp4_files,
)
from ..ui.strings import t
from .theme import MONO_FONT_FAMILIES, Theme, ThemeManager

_VIDEO_FILTER = "Videos (*.mp4 *.mov *.m4v);;All files (*)"
_MAX_BYTE_SPANS = 40


class _AnalysisSignals(QObject):
    finished = Signal(str)
    failed = Signal(str)


class ForensicDialog(QDialog):
    def __init__(
        self,
        settings: Settings,
        theme_manager: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._theme_manager = theme_manager
        self._signals = _AnalysisSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)

        self.setModal(True)
        self.setWindowTitle(t("forensic_btn", settings.language))
        self.resize(900, 640)
        self.setMinimumSize(760, 520)

        theme = theme_manager.theme
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.outer, theme.outer, theme.outer, theme.outer)
        outer.setSpacing(theme.spacing)

        outer.addWidget(self._build_picker(theme))
        self.details = QPlainTextEdit()
        self.details.setObjectName("ConsoleLog")
        self.details.setReadOnly(True)
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        mono = QFont()
        mono.setFamilies(list(MONO_FONT_FAMILIES))
        mono.setPixelSize(theme.fonts.mono)
        self.details.setFont(mono)
        outer.addWidget(self.details, 1)

    def _build_picker(self, theme: Theme) -> QWidget:
        lang = self.settings.language
        card = QFrame()
        card.setObjectName("Card")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(
            theme.inner, theme.inner, theme.inner, theme.inner
        )
        layout.setSpacing(theme.outer)

        self.original_edit = self._add_path_row(
            layout, "Original file", theme, self._browse_original
        )
        self.patched_edit = self._add_path_row(
            layout, "Patched / target file", theme, self._browse_patched
        )

        self.analyze_button = QPushButton("Analyze")
        self.analyze_button.setProperty("variant", "primary")
        self.analyze_button.setMinimumHeight(theme.primary_height)
        self.analyze_button.clicked.connect(self._analyze)
        layout.addWidget(self.analyze_button)

        card.setAccessibleName(t("forensic_btn", lang))
        return card

    def _add_path_row(
        self,
        layout: QVBoxLayout,
        label: str,
        theme: Theme,
        browse: Callable[[], None],
    ) -> QLineEdit:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(theme.spacing)

        title = QLabel(label)
        title.setMinimumWidth(120)
        row_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)

        edit = QLineEdit()
        edit.setClearButtonEnabled(True)
        row_layout.addWidget(edit, 1)

        button = QPushButton(t("browse_files", self.settings.language))
        button.setProperty("variant", "secondary")
        button.setFixedHeight(theme.secondary_height)
        button.clicked.connect(browse)
        row_layout.addWidget(button, 0)

        layout.addWidget(row)
        return edit

    def _browse_original(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select original MP4", "", _VIDEO_FILTER
        )
        if path:
            self.original_edit.setText(path)

    def _browse_patched(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select patched MP4", "", _VIDEO_FILTER
        )
        if path:
            self.patched_edit.setText(path)

    def _analyze(self) -> None:
        original = self._path_from(self.original_edit)
        patched = self._path_from(self.patched_edit)
        if original is None and patched is None:
            QMessageBox.warning(
                self,
                t("forensic_btn", self.settings.language),
                "Select at least one MP4 file to analyze.",
            )
            return
        for path in (original, patched):
            if path is not None and not path.is_file():
                QMessageBox.warning(
                    self,
                    t("forensic_btn", self.settings.language),
                    f"File not found: {path}",
                )
                return

        self.analyze_button.setEnabled(False)
        self.details.setPlainText("Analyzing...")

        def job() -> None:
            try:
                if original is not None and patched is not None:
                    text = _render_diff(compare_mp4_files(original, patched))
                else:
                    target = original if original is not None else patched
                    assert target is not None
                    report = MP4ForensicAnalyzer(
                        target.read_bytes(), str(target)
                    ).parse()
                    text = _render_report(report)
            except Exception as exc:
                self._signals.failed.emit(f"{type(exc).__name__}: {exc}")
            else:
                self._signals.finished.emit(text)

        threading.Thread(
            target=job, daemon=True, name="fps-forensic-analysis"
        ).start()

    @staticmethod
    def _path_from(edit: QLineEdit) -> Path | None:
        text = edit.text().strip()
        return Path(text) if text else None

    def _on_finished(self, text: str) -> None:
        self.details.setPlainText(text)
        self.analyze_button.setEnabled(True)

    def _on_failed(self, message: str) -> None:
        self.analyze_button.setEnabled(True)
        QMessageBox.critical(
            self,
            t("forensic_btn", self.settings.language),
            f"Analysis failed: {message}",
        )


def _format_size(size: int) -> str:
    return f"{size:,} bytes"


def _render_report(report: MP4ForensicReport) -> str:
    lines = [
        "MP4 FORENSIC REPORT",
        "",
        f"File: {report.file_path}",
        f"Size: {_format_size(report.file_size)}",
        f"SHA-256: {report.file_sha256}",
        f"mdat: {'present' if report.mdat_found else 'missing'}",
        f"mdat offset: {report.mdat_offset}",
        f"mdat size: {_format_size(report.mdat_size)}",
        f"mdat payload SHA-256: {report.mdat_payload_sha256}",
        f"moov SHA-256: {report.moov_sha256}",
        f"Trailing data: {_format_size(report.trailing_data_size)}",
    ]

    if report.summary_fields:
        lines.extend(["", "SUMMARY"])
        for key, value in report.summary_fields.items():
            lines.append(f"  {key}: {value}")

    lines.extend(["", "TRACKS"])
    if report.tracks:
        for track in report.tracks:
            lines.append(
                f"  track {track.track_id} ({track.handler_type}, {track.codec}): "
                f"timescale={track.timescale} duration={track.duration_track} "
                f"samples={track.sample_count}"
            )
    else:
        lines.append("  (none)")

    lines.extend(["", "ATOM TREE"])
    _append_atoms(lines, report.atom_tree, 1)
    return "\n".join(lines)


def _append_atoms(lines: list[str], atoms: list[Any], depth: int) -> None:
    indent = "  " * depth
    for atom in atoms:
        fields = ""
        if atom.fields:
            fields = "  " + ", ".join(
                f"{key}={value}" for key, value in atom.fields.items()
            )
        lines.append(
            f"{indent}{atom.type_str} @ {atom.start} size {atom.size}{fields}"
        )
        if atom.children:
            _append_atoms(lines, atom.children, depth + 1)


def _render_diff(result: ForensicDiffResult) -> str:
    lines = [
        "MP4 FORENSIC DIFF",
        "",
        f"Original: {result.original_path}",
        f"Patched: {result.patched_path}",
        f"Size changed: {'yes' if result.file_size_changed else 'no'} "
        f"({result.size_difference:+,} bytes)",
        f"Structure match: {'yes' if result.structure_match else 'no'}",
        f"moov changed: {'yes' if result.moov_changed else 'no'}",
        f"mdat payload: {'MATCH' if result.mdat_match else 'CHANGED'}",
        f"Video payload: {'MATCH' if result.video_payload_match else 'CHANGED'}",
        f"Audio payload: {'MATCH' if result.audio_payload_match else 'CHANGED'}",
    ]
    if result.audio_ghost_samples:
        lines.append(f"Audio ghost samples: {result.audio_ghost_samples}")

    lines.extend(["", "CHANGED ATOMS"])
    if result.changed_atoms:
        lines.extend(f"  {atom}" for atom in result.changed_atoms)
    else:
        lines.append("  (none)")

    lines.extend(["", "SEMANTIC DIFFERENCES"])
    if result.semantic_diffs:
        for diff in result.semantic_diffs:
            lines.append(
                f"  {diff.target} {diff.field}: {diff.old_value} -> "
                f"{diff.new_value} ({diff.interpretation})"
            )
    else:
        lines.append("  (none)")

    lines.extend(["", "BYTE DIFFERENCES"])
    if result.byte_diffs:
        for span in result.byte_diffs[:_MAX_BYTE_SPANS]:
            lines.append(
                f"  @{span.offset} len {span.length} {span.atom_path} "
                f"old={span.old_bytes_hex} new={span.new_bytes_hex}"
            )
        remaining = len(result.byte_diffs) - _MAX_BYTE_SPANS
        if remaining > 0:
            lines.append(f"  ... {remaining} more byte span(s)")
    else:
        lines.append("  (none)")

    lines.extend(["", "CLASSIFICATION"])
    for status, atoms in result.bxd_classification.items():
        if atoms:
            lines.append(f"  {status}: {', '.join(atoms)}")

    lines.extend(["", "HYPOTHESIS"])
    if result.hypothesis:
        lines.extend(f"  {line}" for line in result.hypothesis)
    else:
        lines.append("  (none)")
    return "\n".join(lines)
