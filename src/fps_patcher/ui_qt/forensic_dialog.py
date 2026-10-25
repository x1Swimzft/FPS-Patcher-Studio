"""Modal MP4 forensic analyzer dialog with a background comparison worker."""

from __future__ import annotations

import json
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
from ..core.bxd_patcher import repair_for_mobile
from ..core.diagnostic_logger import auto_save_diagnostic_log
from ..core.forensic_analyzer import (
    ForensicDiffResult,
    MP4ForensicAnalyzer,
    MP4ForensicReport,
    compare_mp4_files,
    export_diff_artifacts,
)
from ..ui.strings import t
from .bridge import ControllerBridge
from .theme import MONO_FONT_FAMILIES, Theme, ThemeManager

_VIDEO_FILTER = "Videos (*.mp4 *.mov *.m4v);;All files (*)"
_MAX_BYTE_SPANS = 40


class _AnalysisSignals(QObject):
    finished = Signal(object, str)
    failed = Signal(str)


class _TaskSignals(QObject):
    finished = Signal(str, object)
    failed = Signal(str)


class ForensicDialog(QDialog):
    def __init__(
        self,
        settings: Settings,
        theme_manager: ThemeManager,
        parent: QWidget | None = None,
        preselected_path: Path | None = None,
        bridge: ControllerBridge | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._theme_manager = theme_manager
        self._bridge = bridge if bridge is not None else getattr(parent, "bridge", None)

        self._report: MP4ForensicReport | None = None
        self._diff: ForensicDiffResult | None = None
        self._analysis_inputs: tuple[Path | None, Path | None] | None = None
        self._pending_inputs: tuple[Path | None, Path | None] = (None, None)
        self._console_lines: list[str] = []
        self._pending_action: str | None = None
        self._busy = False

        self._signals = _AnalysisSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._task_signals = _TaskSignals(self)
        self._task_signals.finished.connect(self._on_task_finished)
        self._task_signals.failed.connect(self._on_task_failed)
        if isinstance(self._bridge, ControllerBridge):
            self._bridge.forensic_status.connect(self._on_task_status)
            self._bridge.forensic_finished.connect(self._on_task_finished)
            self._bridge.forensic_failed.connect(self._on_task_failed)

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
        outer.addWidget(self._build_actions(theme))

        if preselected_path is not None:
            self.patched_edit.setText(str(preselected_path))
        self.original_edit.textChanged.connect(self._refresh_actions)
        self.patched_edit.textChanged.connect(self._refresh_actions)
        self._refresh_actions()

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
            layout, t("forensic_original", lang), theme, self._browse_original
        )
        self.patched_edit = self._add_path_row(
            layout, t("forensic_patched", lang), theme, self._browse_patched
        )

        self.analyze_button = QPushButton(t("forensic_analyze", lang))
        self.analyze_button.setProperty("variant", "primary")
        self.analyze_button.setMinimumHeight(theme.primary_height)
        self.analyze_button.clicked.connect(self._analyze)
        layout.addWidget(self.analyze_button)

        card.setAccessibleName(t("forensic_btn", lang))
        return card

    def _build_actions(self, theme: Theme) -> QWidget:
        lang = self.settings.language
        footer = QFrame()
        footer.setObjectName("ForensicActions")
        footer.setAccessibleName(t("forensic_actions", lang))

        layout = QVBoxLayout(footer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.spacing)

        self.status_label = QLabel("")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setAccessibleName(t("forensic_actions", lang))
        layout.addWidget(self.status_label)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(theme.spacing)

        self.repair_button = self._action_button(
            t("forensic_repair", lang), theme, self._repair
        )
        self.export_json_button = self._action_button(
            t("forensic_export_json", lang), theme, self._export_json
        )
        self.export_report_button = self._action_button(
            t("forensic_export_report", lang), theme, self._export_report
        )
        self.diagnostic_button = self._action_button(
            t("forensic_diagnostic_log", lang), theme, self._save_diagnostic_log
        )
        for button in (
            self.repair_button,
            self.export_json_button,
            self.export_report_button,
            self.diagnostic_button,
        ):
            row_layout.addWidget(button)
        row_layout.addStretch(1)
        layout.addWidget(row)
        return footer

    def _action_button(
        self, label: str, theme: Theme, slot: Callable[[], None]
    ) -> QPushButton:
        button = QPushButton(label)
        button.setProperty("variant", "secondary")
        button.setMinimumHeight(max(26, theme.secondary_height))
        button.setAccessibleName(label)
        button.setToolTip(label)
        button.clicked.connect(slot)
        return button

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
            self, t("forensic_original", self.settings.language), "", _VIDEO_FILTER
        )
        if path:
            self.original_edit.setText(path)

    def _browse_patched(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, t("forensic_patched", self.settings.language), "", _VIDEO_FILTER
        )
        if path:
            self.patched_edit.setText(path)

    @staticmethod
    def _path_from(edit: QLineEdit) -> Path | None:
        text = edit.text().strip()
        return Path(text) if text else None

    def _target(self) -> Path | None:
        target = self._path_from(self.patched_edit)
        return target if target is not None and target.is_file() else None

    def _source(self) -> Path | None:
        source = self._path_from(self.original_edit)
        return source if source is not None and source.is_file() else None

    def _analysis_ready(self) -> bool:
        current = (
            self._path_from(self.original_edit),
            self._path_from(self.patched_edit),
        )
        return (
            self._diff is not None or self._report is not None
        ) and self._analysis_inputs == current

    def _refresh_actions(self) -> None:
        ready = self._analysis_ready()
        target = self._target()
        enabled = not self._busy
        self.repair_button.setEnabled(ready and target is not None and enabled)
        self.diagnostic_button.setEnabled(ready and target is not None and enabled)
        self.export_json_button.setEnabled(ready and enabled)
        self.export_report_button.setEnabled(ready and enabled)

    def _show_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _analyze(self) -> None:
        lang = self.settings.language
        original = self._path_from(self.original_edit)
        patched = self._path_from(self.patched_edit)
        if original is None and patched is None:
            QMessageBox.warning(
                self,
                t("forensic_btn", lang),
                "Select at least one MP4 file to analyze.",
            )
            return
        for path in (original, patched):
            if path is not None and not path.is_file():
                QMessageBox.warning(
                    self,
                    t("forensic_btn", lang),
                    f"File not found: {path}",
                )
                return

        self._pending_inputs = (original, patched)
        self._analysis_inputs = None
        self.analyze_button.setEnabled(False)
        self.details.setPlainText(t("forensic_analyzing", lang))
        self._refresh_actions()

        def job() -> None:
            try:
                if original is not None and patched is not None:
                    diff = compare_mp4_files(original, patched)
                    payload: MP4ForensicReport | ForensicDiffResult = diff
                    text = _render_diff(diff)
                else:
                    target = original if original is not None else patched
                    assert target is not None
                    report = MP4ForensicAnalyzer(
                        target.read_bytes(), str(target)
                    ).parse()
                    payload = report
                    text = _render_report(report)
            except Exception as exc:
                self._signals.failed.emit(f"{type(exc).__name__}: {exc}")
            else:
                self._signals.finished.emit(payload, text)

        threading.Thread(
            target=job, daemon=True, name="fps-forensic-analysis"
        ).start()

    def _on_finished(self, payload: object, text: str) -> None:
        self._report = payload if isinstance(payload, MP4ForensicReport) else None
        self._diff = payload if isinstance(payload, ForensicDiffResult) else None
        self._analysis_inputs = self._pending_inputs
        self._console_lines = text.splitlines()
        self.details.setPlainText(text)
        self.analyze_button.setEnabled(True)
        self._show_status("")
        self._refresh_actions()

    def _on_failed(self, message: str) -> None:
        self._analysis_inputs = None
        self.analyze_button.setEnabled(True)
        self._refresh_actions()
        QMessageBox.critical(
            self,
            t("forensic_btn", self.settings.language),
            f"Analysis failed: {message}",
        )

    def _repair(self) -> None:
        lang = self.settings.language
        if not self._analysis_ready():
            self._show_status(t("forensic_need_analysis", lang))
            return
        target = self._target()
        if target is None:
            self._show_status(t("forensic_need_output", lang))
            return

        suggested = target.with_name(f"{target.stem}_mobile_repaired{target.suffix}")
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            t("forensic_repair", lang),
            str(suggested),
            _VIDEO_FILTER,
        )
        if not chosen:
            return
        output = Path(chosen)

        self._pending_action = "repair"
        self._busy = True
        self._show_status(t("forensic_repairing", lang))
        self._refresh_actions()
        if self._bridge is not None:
            self._bridge.forensic_repair(target, output)
        else:
            self._start_local_task(
                "repair",
                lambda: Path(repair_for_mobile(target, output)["output"]),
            )

    def _save_diagnostic_log(self) -> None:
        lang = self.settings.language
        if not self._analysis_ready():
            self._show_status(t("forensic_need_analysis", lang))
            return
        target = self._target()
        if target is None:
            self._show_status(t("forensic_need_output", lang))
            return
        lines = self._console_lines or self.details.toPlainText().splitlines()
        mask = bool(self.settings.mask_diagnostic_paths)

        self._pending_action = "diagnostic"
        self._busy = True
        self._show_status(t("forensic_exporting", lang))
        self._refresh_actions()
        if self._bridge is not None:
            self._bridge.forensic_diagnostic_log(
                target,
                source=self._source(),
                console_lines=lines,
                mask_paths=mask,
            )
        else:
            self._start_local_task(
                "diagnostic",
                lambda: auto_save_diagnostic_log(
                    target_file=target,
                    source_file=self._source(),
                    console_lines=lines,
                    mask_paths=mask,
                ),
            )

    def _export_json(self) -> None:
        lang = self.settings.language
        if not self._analysis_ready():
            self._show_status(t("forensic_need_analysis", lang))
            return
        chosen = QFileDialog.getExistingDirectory(
            self, t("forensic_export_json", lang)
        )
        if not chosen:
            return
        out_dir = Path(chosen)
        try:
            if self._diff is not None:
                export_diff_artifacts(self._diff, out_dir)
            else:
                assert self._report is not None
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "report.json").write_text(
                    json.dumps(self._report.to_dict(), indent=2), encoding="utf-8"
                )
        except Exception as exc:
            self._show_status(
                t("forensic_export_failed", lang).format(
                    error=f"{type(exc).__name__}: {exc}"
                )
            )
        else:
            self._show_status(t("forensic_export_done", lang).format(path=out_dir))

    def _export_report(self) -> None:
        lang = self.settings.language
        if not self._analysis_ready():
            self._show_status(t("forensic_need_analysis", lang))
            return
        target = self._target()
        suggested = (
            target.with_name(f"{target.stem}_forensic_report.md")
            if target is not None
            else "forensic_report.md"
        )
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            t("forensic_export_report", lang),
            str(suggested),
            "Markdown (*.md);;Text (*.txt)",
        )
        if not chosen:
            return
        path = Path(chosen)
        if self._diff is not None:
            text = _render_markdown(self._diff)
        else:
            assert self._report is not None
            text = _render_report(self._report)
        try:
            path.write_text(text, encoding="utf-8")
        except Exception as exc:
            self._show_status(
                t("forensic_export_failed", lang).format(
                    error=f"{type(exc).__name__}: {exc}"
                )
            )
        else:
            self._show_status(t("forensic_export_done", lang).format(path=path))

    def _start_local_task(self, kind: str, job: Callable[[], object]) -> None:
        """Fallback when no main-window bridge is available (still off the GUI thread)."""

        def worker() -> None:
            try:
                result = job()
            except Exception as exc:
                self._task_signals.failed.emit(f"{type(exc).__name__}: {exc}")
            else:
                if result is None:
                    self._task_signals.failed.emit(f"{kind} failed")
                else:
                    self._task_signals.finished.emit(kind, result)

        threading.Thread(
            target=worker, daemon=True, name=f"fps-forensic-{kind}"
        ).start()

    def _on_task_status(self, status: str) -> None:
        lang = self.settings.language
        key = f"forensic_{status}"
        if status in {"repairing", "exporting", "analyzing"}:
            self._show_status(t(key, lang))

    def _on_task_finished(self, kind: str, result: object) -> None:
        lang = self.settings.language
        self._busy = False
        self._pending_action = None
        if kind == "repair":
            path = Path(str(result))
            self.patched_edit.setText(str(path))
            self._show_status(t("forensic_repair_done", lang).format(path=path))
        else:
            self._show_status(t("forensic_export_done", lang).format(path=result))
        self._refresh_actions()

    def _on_task_failed(self, message: str) -> None:
        lang = self.settings.language
        action = self._pending_action
        self._busy = False
        self._pending_action = None
        key = "forensic_repair_failed" if action == "repair" else "forensic_export_failed"
        text = t(key, lang).format(error=message)
        self._show_status(text)
        self._refresh_actions()
        QMessageBox.critical(self, t("forensic_btn", lang), text)


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


def _render_markdown(result: ForensicDiffResult) -> str:
    lines = [
        f"# MP4 Forensic Report: {Path(result.original_path).name} vs "
        f"{Path(result.patched_path).name}",
        "",
        "## Verified Findings",
        f"- **Video Payload Integrity**: "
        f"{'PASS (Bit-exact)' if result.video_payload_match else 'FAIL (Modified)'}",
        f"- **Audio Samples**: {'MATCH' if result.audio_payload_match else 'CHANGED'}",
        f"- **Entire mdat Box**: {'MATCH' if result.mdat_match else 'CHANGED'}",
        f"- **Structure Match**: {'yes' if result.structure_match else 'no'}",
        f"- **moov Changed**: {'yes' if result.moov_changed else 'no'}",
        "",
        "## Observed Atom Differences",
        f"- **Changed Atoms**: `{', '.join(result.changed_atoms) or 'None'}`",
        "",
        "### Semantic Differences",
    ]
    for diff in result.semantic_diffs:
        lines.append(
            f"- **{diff.target}** `{diff.field}`: "
            f"`{diff.old_value}` -> `{diff.new_value}`"
        )
    lines.extend(
        [
            "",
            "### Binary Differences (First 100 Spans)",
            "| Offset | Length | Atom Path | Old Hex | New Hex |",
            "|---|---|---|---|---|",
        ]
    )
    for span in result.byte_diffs[:100]:
        lines.append(
            f"| `0x{span.offset:08x}` | {span.length} | `{span.atom_path}` | "
            f"`{span.old_bytes_hex}` | `{span.new_bytes_hex}` |"
        )
    lines.extend(
        [
            "",
            "### Hypothesis",
            *[f"- {line}" for line in result.hypothesis],
        ]
    )
    return "\n".join(lines)
