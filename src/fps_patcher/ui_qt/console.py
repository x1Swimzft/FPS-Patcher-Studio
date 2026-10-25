"""Collapsible Qt activity console drawer."""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPalette, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings, app_data_dir
from ..ui.strings import t
from .icons import get_icon
from .motion import animate_height
from .theme import MONO_FONT_FAMILIES, RADIUS_PILL, UI_FONT_FAMILIES, Theme, ThemeManager
from .widgets import ElidedLabel, icon_button

_CMD_PREFIXES = ("$ ", "> ", "Command:", "command:", "ffmpeg ", "ffprobe ", "[CMD]")
_DIM_PREFIXES = (
    "[DIM]",
    "[DEBUG]",
    "frame=",
    "size=",
    "Stream #",
    "Metadata:",
    "Duration:",
    "  configuration:",
    "  lib",
)

# Console surfaces stay dark in every preset, so use the dark half of each token.
_LEVEL_TOKENS = {
    "INFO": "text",
    "OK": "success",
    "WARN": "warn",
    "ERROR": "danger",
    "CMD": "accent",
    "DIM": "muted",
    "DEBUG": "muted",
}


def classify_log_level(text: str, level: str = "INFO") -> str:
    """Map a level or a known command/diagnostic prefix to a console tag."""
    norm = (level or "INFO").strip().upper()
    if norm == "COMMAND":
        return "CMD"
    if norm in ("OK", "WARN", "ERROR", "CMD", "DIM", "DEBUG"):
        return norm
    stripped = text.lstrip()
    if stripped.startswith(_CMD_PREFIXES):
        return "CMD"
    if stripped.startswith(_DIM_PREFIXES):
        return "DIM"
    return "INFO"


class ConsolePanel(QWidget):
    """Activity console: a 36 px summary row that expands into a 180 px log."""

    save_log_requested = Signal()
    repair_requested = Signal(object)
    expanded_changed = Signal(bool)

    def __init__(
        self,
        settings: Settings,
        theme_manager: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._theme = theme_manager.theme
        self._expanded = False
        self._animated = False
        self._height_anim: QVariantAnimation | None = None
        self._show_ffmpeg = bool(settings.show_ffmpeg_output)
        self._entries: list[tuple[str, str, str]] = []  # (timestamp, text, tag)
        self._lines: list[str] = []
        self.last_target_file: Path | None = None
        self.last_source_file: Path | None = None
        self._formats: dict[str, QTextCharFormat] = {}
        self._time_format = QTextCharFormat()

        self.setObjectName("Console")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build()
        self.set_theme(self._theme)
        theme_manager.subscribe(self.set_theme)

    # ---------- construction ----------
    def _build(self) -> None:
        theme = self._theme
        lang = self._lang()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = QWidget(self)
        self._header.setObjectName("ConsoleHeader")
        self._header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._header.setFixedHeight(max(1, theme.console_collapsed_height - 1))
        self._header_layout = QHBoxLayout(self._header)
        self._header_layout.setContentsMargins(theme.inner, 0, theme.outer, 0)
        self._header_layout.setSpacing(theme.outer)
        root.addWidget(self._header)

        title = t("activity_console", lang)
        self._chevron = icon_button(
            "chevron_right",
            title,
            theme,
            self.toggle,
            accessible_name=title,
            parent=self._header,
        )
        self._chevron.setIcon(get_icon("chevron_right", True))
        self._header_layout.addWidget(self._chevron, 0, Qt.AlignmentFlag.AlignVCenter)

        self._title = QLabel(title, self._header)
        self._title.setProperty("role", "title")
        self._header_layout.addWidget(self._title, 0, Qt.AlignmentFlag.AlignVCenter)

        self._count = QLabel(self._format_line_count(0), self._header)
        self._count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._header_layout.addWidget(self._count, 0, Qt.AlignmentFlag.AlignVCenter)

        self._latest = ElidedLabel("", self._header)
        self._latest.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._header_layout.addWidget(self._latest, 1, Qt.AlignmentFlag.AlignVCenter)

        self._more = icon_button(
            "more",
            t("more_actions", lang),
            theme,
            self._show_menu,
            accessible_name=t("more_actions", lang),
            parent=self._header,
        )
        self._more.setIcon(get_icon("more", True))
        self._header_layout.addWidget(self._more, 0, Qt.AlignmentFlag.AlignVCenter)

        self.detail = QWidget(self)
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(
            theme.inner, theme.outer, theme.inner, theme.outer
        )
        detail_layout.setSpacing(0)

        self.editor = QPlainTextEdit(self.detail)
        self.editor.setObjectName("ConsoleLog")
        self.editor.setReadOnly(True)
        self.editor.setUndoRedoEnabled(False)
        self.editor.setFrameShape(QFrame.Shape.NoFrame)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setMaximumBlockCount(self._max_lines())
        self.editor.setAccessibleName(title)
        detail_layout.addWidget(self.editor)
        root.addWidget(self.detail, 1)

        self._apply_expanded(False)

    # ---------- settings helpers ----------
    def _lang(self) -> str:
        return str(getattr(self._settings, "language", "en") or "en")

    def _max_lines(self) -> int:
        try:
            return max(100, min(20000, int(self._settings.max_log_lines)))
        except (AttributeError, TypeError, ValueError):
            return 2000

    def _format_line_count(self, count: int) -> str:
        return t(
            "console_line_one" if count == 1 else "console_lines",
            self._lang(),
            count=count,
        )

    def _console_color(self, token: str) -> str:
        pair: tuple[str, str] = getattr(self._theme.tokens, token)
        return pair[1]

    def _mono_font(self, pixel_size: int) -> QFont:
        font = QFont()
        font.setFamilies(list(MONO_FONT_FAMILIES))
        font.setPixelSize(pixel_size)
        return font

    # ---------- theme ----------
    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._show_ffmpeg = bool(
            getattr(self._settings, "show_ffmpeg_output", self._show_ffmpeg)
        )
        lang = self._lang()
        mono_families = ", ".join(f'"{name}"' for name in MONO_FONT_FAMILIES)

        try:
            editor_size = int(self._settings.console_font_size)
        except (AttributeError, TypeError, ValueError):
            editor_size = theme.fonts.mono
        editor_size = max(11, min(24, editor_size))

        self.setStyleSheet(
            "QWidget#Console {"
            f"background: {self._console_color('console_bg')};"
            f"border-top: 1px solid {self._console_color('console_border')};"
            "}"
            "QWidget#ConsoleHeader {"
            f"background: {self._console_color('console_bg')};"
            "}"
            "QPlainTextEdit#ConsoleLog {"
            f"background: {self._console_color('console_bg')};"
            f"border: 1px solid {self._console_color('console_border')};"
            f"border-radius: {theme.radii.control}px;"
            f"color: {self._console_color('text')};"
            f"font-family: {mono_families};"
            f"font-size: {editor_size}px;"
            f"padding: {theme.outer}px {theme.inner}px;"
            f"selection-background-color: {self._console_color('accent')};"
            f"selection-color: {self._console_color('on_accent')};"
            "}"
        )

        self._header.setFixedHeight(max(1, theme.console_collapsed_height - 1))
        self._header_layout.setContentsMargins(theme.inner, 0, theme.outer, 0)
        self._header_layout.setSpacing(theme.outer)

        title_font = QFont()
        title_font.setFamilies(list(UI_FONT_FAMILIES))
        title_font.setPixelSize(theme.fonts.body + 2)
        title_font.setWeight(QFont.Weight.DemiBold)
        self._title.setFont(title_font)
        self._title.setStyleSheet(f"color: {self._console_color('text')};")
        title_palette = self._title.palette()
        title_palette.setColor(
            QPalette.ColorRole.WindowText, QColor(self._console_color("text"))
        )
        self._title.setPalette(title_palette)

        self._count.setFixedHeight(max(18, theme.fonts.caption + 8))
        self._count.setStyleSheet(
            f"background: {self._console_color('console_border')};"
            f"color: {self._console_color('text2')};"
            f"border-radius: {RADIUS_PILL}px;"
            f"padding: 0 {theme.outer + 2}px;"
            f"font-size: {theme.fonts.caption}px;"
        )

        latest_font = self._mono_font(max(11, min(12, theme.fonts.mono)))
        self._latest.setFont(latest_font)
        palette = self._latest.palette()
        palette.setColor(
            QPalette.ColorRole.WindowText, QColor(self._console_color("text2"))
        )
        self._latest.setPalette(palette)
        self._latest.setStyleSheet(
            f"color: {self._console_color('text2')}; background: transparent;"
        )

        for button in (self._chevron, self._more):
            button.setFixedSize(theme.icon_button_size, theme.icon_button_size)

        editor_font = self._mono_font(editor_size)
        self.editor.setFont(editor_font)
        self.editor.document().setDefaultFont(editor_font)
        self.editor.setMaximumBlockCount(self._max_lines())
        self.editor.setStyleSheet(
            f"font-family: {mono_families}; font-size: {editor_size}px;"
        )

        self._build_formats()
        self._render_all()

        chevron = "chevron_down" if self._expanded else "chevron_right"
        self._chevron.setIcon(get_icon(chevron, True))
        title = t("activity_console", lang)
        self._title.setText(title)
        self._chevron.setToolTip(title)
        self._chevron.setAccessibleName(title)
        self._more.setToolTip(t("more_actions", lang))
        self._more.setAccessibleName(t("more_actions", lang))
        self._update_status()
        self._apply_expanded(self._expanded)

    def _build_formats(self) -> None:
        self._formats = {}
        for tag, token in _LEVEL_TOKENS.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(self._console_color(token)))
            self._formats[tag] = fmt
        self._time_format = QTextCharFormat()
        self._time_format.setForeground(QColor(self._console_color("muted")))

    # ---------- drawing ----------
    def _format_entry(self, entry: tuple[str, str, str]) -> str:
        timestamp, text, _tag = entry
        return f"[{timestamp}] {text}" if timestamp else text

    def _insert_entries(self, entries: list[tuple[str, str, str]]) -> None:
        cursor = QTextCursor(self.editor.document())
        cursor.beginEditBlock()
        for timestamp, text, tag in entries:
            if timestamp:
                cursor.insertText(f"[{timestamp}] ", self._time_format)
            cursor.insertText(text, self._formats.get(tag, self._formats["INFO"]))
            cursor.insertText("\n", self._formats["INFO"])
        cursor.endEditBlock()

    def _render_all(self) -> None:
        cap = self._max_lines()
        if len(self._entries) > cap:
            self._entries = self._entries[-cap:]
        self._lines = [self._format_entry(entry) for entry in self._entries]

        was_at_bottom = self._at_bottom()
        self.editor.setUpdatesEnabled(False)
        self.editor.clear()
        self._insert_entries(self._entries)
        self.editor.setUpdatesEnabled(True)
        if was_at_bottom and bool(self._settings.log_autoscroll):
            self._scroll_to_end()
        self._update_status()

    def _at_bottom(self) -> bool:
        bar = self.editor.verticalScrollBar()
        return bar.value() >= bar.maximum()

    def _scroll_to_end(self) -> None:
        bar = self.editor.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _update_status(self) -> None:
        count_text = self._format_line_count(len(self._entries))
        self._count.setText(count_text)
        self._count.setAccessibleName(count_text)
        self._latest.setText(self._lines[-1] if self._lines else "")

    # ---------- logging ----------
    def append(self, text: str, level: str = "INFO") -> None:
        self.append_batch([(text, level)])

    def append_batch(self, entries: list[tuple[str, str]]) -> None:
        if not entries:
            return
        timestamp = (
            time.strftime("%H:%M:%S") if bool(self._settings.log_timestamps) else ""
        )
        prepared: list[tuple[str, str, str]] = []
        for raw_text, level in entries:
            norm = (level or "INFO").strip().upper()
            if norm == "DEBUG" and not self._show_ffmpeg:
                continue
            for line in str(raw_text).splitlines() or [""]:
                prepared.append((timestamp, line, classify_log_level(line, norm)))
        if not prepared:
            return

        cap = self._max_lines()
        if len(prepared) > cap:
            prepared = prepared[-cap:]

        was_at_bottom = self._at_bottom()
        self._insert_entries(prepared)
        self._entries.extend(prepared)
        if len(self._entries) > cap:
            del self._entries[:-cap]
        self._lines.extend(self._format_entry(entry) for entry in prepared)
        if len(self._lines) > cap:
            del self._lines[:-cap]

        if was_at_bottom and bool(self._settings.log_autoscroll):
            self._scroll_to_end()
        self._update_status()

    def clear_logs(self) -> None:
        self._entries.clear()
        self._lines.clear()
        self.editor.clear()
        self._update_status()

    def get_lines(self) -> list[str]:
        return list(self._lines)

    def set_context_files(
        self, target: Path | None = None, source: Path | None = None
    ) -> None:
        if target is not None:
            self.last_target_file = target
        if source is not None:
            self.last_source_file = source

    # ---------- expansion ----------
    @property
    def is_expanded(self) -> bool:
        return self._expanded

    @property
    def reduce_motion(self) -> bool:
        return bool(getattr(self._settings, "reduce_motion", False))

    def set_animated(self, animated: bool) -> None:
        """Hook for the shell's height animation (package 7)."""
        self._animated = bool(animated)

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._chevron.setIcon(
            get_icon("chevron_down" if expanded else "chevron_right", True)
        )
        if expanded:
            self.detail.setVisible(True)
        self.expanded_changed.emit(expanded)
        target = self._drawer_height(expanded)
        if self._animated and not self.reduce_motion:
            self._stop_height()
            self._height_anim = animate_height(
                self,
                self.height(),
                target,
                220,
                False,
                on_finished=lambda: self._finish_drawer(expanded),
            )
        else:
            self._apply_expanded(expanded)

    def _drawer_height(self, expanded: bool) -> int:
        return int(
            self._theme.console_expanded_height
            if expanded
            else self._theme.console_collapsed_height
        )

    def _finish_drawer(self, expanded: bool) -> None:
        # The animation group deletes itself on finished; drop our reference
        # before applying the final state so it is not stopped/deleted twice.
        self._height_anim = None
        if expanded == self._expanded:
            self._apply_expanded(expanded)

    def _stop_height(self) -> None:
        if self._height_anim is not None:
            self._height_anim.stop()
            self._height_anim.deleteLater()
            self._height_anim = None

    def _apply_expanded(self, expanded: bool) -> None:
        """Commit the final drawer state; animation always lands here."""
        expanded = bool(expanded)
        self._stop_height()
        self._expanded = expanded
        self.detail.setVisible(expanded)
        self._chevron.setIcon(
            get_icon("chevron_down" if expanded else "chevron_right", True)
        )
        self.setFixedHeight(self._drawer_height(expanded))

    def hideEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._stop_height()
        self._apply_expanded(self._expanded)
        super().hideEvent(event)

    # ---------- menu and actions ----------
    def _menu_position(self, menu: QMenu) -> QPoint:
        anchor = self._more.mapToGlobal(QPoint(0, 0))
        hint = menu.sizeHint()
        return QPoint(
            anchor.x() + self._more.width() - hint.width(),
            anchor.y() - hint.height() - 4,
        )

    def _show_menu(self) -> None:
        lang = self._lang()
        menu = QMenu(self)

        ffmpeg = menu.addAction(t("ffmpeg_logs", lang))
        ffmpeg.setCheckable(True)
        ffmpeg.setChecked(self._show_ffmpeg)
        ffmpeg.toggled.connect(self._on_ffmpeg_toggled)

        menu.addSeparator()
        menu.addAction(t("copy_logs", lang), self._copy_all)
        menu.addAction(t("clear_logs", lang), self.clear_logs)
        menu.addAction(t("save_log", lang), self._save_log)
        menu.addAction(t("open_logs_folder", lang), self._open_logs_folder)
        menu.addAction(t("repair_for_mobile", lang), self._request_repair)
        menu.exec(self._menu_position(menu))

    def _on_ffmpeg_toggled(self, checked: bool) -> None:
        self._show_ffmpeg = bool(checked)
        self._settings.show_ffmpeg_output = self._show_ffmpeg
        with contextlib.suppress(Exception):
            self._settings.save_async()

    def _copy_all(self) -> None:
        QApplication.clipboard().setText("\n".join(self.get_lines()))

    def _save_log(self) -> None:
        self.save_log_requested.emit()
        stamp = time.strftime("%Y%m%d_%H%M%S")
        context = self.last_target_file or self.last_source_file
        folder = context.parent if context is not None else app_data_dir()
        stem = context.stem if context is not None else "console"
        suggested = folder / f"{stem}_console_{stamp}.txt"
        dest, _selected = QFileDialog.getSaveFileName(
            self,
            t("save_log", self._lang()),
            str(suggested),
            "Text files (*.txt)",
        )
        if not dest:
            return
        path = Path(dest)
        if path.suffix.lower() != ".txt":
            path = path.with_suffix(".txt")
        text = "\n".join(self.get_lines())
        try:
            path.write_text(text + ("\n" if text else ""), encoding="utf-8")
        except OSError as exc:
            self.append(f"Could not save log: {exc}", "ERROR")
            return
        self.append(f"Log saved to: {path.name}", "OK")

    def _open_logs_folder(self) -> None:
        folder = app_data_dir()
        starter = getattr(os, "startfile", None)
        if callable(starter):
            with contextlib.suppress(OSError):
                starter(str(folder))

    def _request_repair(self) -> None:
        self.repair_requested.emit(self.last_target_file or self.last_source_file)
