"""Qt main window shell: toolbar, queue/inspector split and controller bridge."""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import threading
from dataclasses import fields
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QSettings, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..app import shell_integration
from ..app.controller import AppController
from ..app.queue_model import InputQueue
from ..app.quick_patch import QUICK_PATCH_TIMESCALE
from ..app.watcher import FolderWatcher
from ..config import Settings, app_data_dir
from ..core.models import (
    SUPPORTED_EXTENSIONS,
    FFmpegDownloadEvent,
    LogEvent,
    PatchDoneEvent,
    ProbeDoneEvent,
    ProgressEvent,
    QueueChangedEvent,
    UpdateAvailableEvent,
    UpdateDownloadEvent,
)
from ..core.notify import toast
from ..core.strategies import strategy_requires_ffmpeg
from ..ui.strings import t
from .bridge import ControllerBridge
from .console import ConsolePanel
from .forensic_dialog import ForensicDialog
from .icons import get_icon
from .inspector import Inspector
from .qss import apply_theme
from .queue_view import QueueView
from .settings_dialog import SettingsDialog
from .theme import (
    RADIUS_PILL,
    Theme,
    ThemeManager,
    apply_backdrop,
    update_title_bar_theme,
)
from .widgets import icon_button, text_button

log = logging.getLogger("fps_patcher.ui_qt.main_window")

__all__ = ["MainWindow"]

_DEFAULT_TIMESCALE = 60000
_WATCH_DRAIN_MS = 500


def _video_filter() -> str:
    patterns = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
    return f"Videos ({patterns});;All files (*)"


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.controller = AppController(settings)
        self.theme_manager = ThemeManager(settings, self)
        self.theme: Theme = self.theme_manager.theme

        self._last_output: Path | None = None
        self._watcher: FolderWatcher | None = None
        self._watch_inbox: queue.Queue[Path] = queue.Queue()
        self._watch_batch_active = False
        self._ff_init_thread: threading.Thread | None = None
        self._ff_state = "checking"
        self._ff_detail = ""
        self._update_info: Any = None
        self._probe_running = False
        self._pending_logs: list[tuple[str, str]] = []
        self._latest_progress: ProgressEvent | None = None
        self._queue_dirty = False
        self._last_busy: bool | None = None
        self._last_can_patch: bool | None = None
        self._console_expanded = False

        self._qt_settings = QSettings("FPSPatcherStudio", "QtUI")
        self._load_queue()

        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, self.theme)

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(self.theme.min_width, self.theme.min_height)
        self.resize(self.theme.window_width, self.theme.window_height)
        if settings.always_on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._restore_geometry()

        self._build_shell()
        self._build_shortcuts()
        self._connect_signals()

        self.bridge = ControllerBridge(self.controller, self)
        self._connect_bridge()
        self.theme_manager.changed.connect(self._on_theme_changed)

        for name, old, new in self.controller.items.migrated_overrides:
            self.console.append(
                f"[CONFIG] Queue item '{name}' preset migrated: '{old}' -> '{new}'",
                "INFO",
            )

        self._console_expanded = False
        self.console.set_expanded(False)
        self.queue_view.refresh()
        self._sync_focused_item()
        self._refresh_readiness()
        self._update_title_bar()

        self._cleanup_stale_preflight()
        self._init_ffmpeg()
        self._sync_watcher()
        self._sync_explorer_menu()
        self.controller.check_for_updates_background(__version__)

        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(_WATCH_DRAIN_MS)
        self._watch_timer.timeout.connect(self._drain_watch_inbox)
        self._watch_timer.start()

    # ------------------------------------------------------------------ shell
    def _build_shell(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_toolbar())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(
            self.theme.outer, self.theme.outer, self.theme.outer, self.theme.outer
        )
        body_layout.setSpacing(self.theme.spacing)

        self.queue_view = QueueView(
            self.controller, self.settings, self.theme_manager, body
        )
        self.inspector = Inspector(self.settings, self.theme_manager, body)
        self.inspector.setFixedWidth(self.theme.inspector_width)
        body_layout.addWidget(self.queue_view, 1)
        body_layout.addWidget(self.inspector, 0)
        outer.addWidget(body, 1)

        self.console = ConsolePanel(self.settings, self.theme_manager, root)
        outer.addWidget(self.console, 0)

    def _build_toolbar(self) -> QWidget:
        theme = self.theme
        lang = self.settings.language
        toolbar = QWidget()
        toolbar.setObjectName("Toolbar")
        toolbar.setFixedHeight(theme.toolbar_height)

        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(theme.inner, 0, theme.inner, 0)
        layout.setSpacing(theme.spacing)

        self.title_label = QLabel(t("app_title", lang))
        self.title_label.setProperty("role", "title")
        layout.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.version_badge = QLabel(f"v{__version__}")
        self.version_badge.setProperty("role", "badge")
        layout.addWidget(self.version_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)

        self.ffmpeg_button = QPushButton()
        self.ffmpeg_button.setProperty("variant", "secondary")
        self.ffmpeg_button.setFixedHeight(theme.button_height)
        self.ffmpeg_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ffmpeg_button.clicked.connect(self._show_ffmpeg_menu)
        layout.addWidget(self.ffmpeg_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.forensic_button = text_button(
            t("forensic_btn", lang),
            theme,
            self._open_forensic,
            height=theme.button_height,
        )
        layout.addWidget(self.forensic_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.output_button = text_button(
            t("open_output_btn", lang),
            theme,
            self._open_output,
            height=theme.button_height,
        )
        layout.addWidget(self.output_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.update_button = text_button(
            "",
            theme,
            self._on_update_clicked,
            variant="primary",
            height=theme.button_height,
        )
        self.update_button.setVisible(False)
        layout.addWidget(self.update_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.theme_button = icon_button(
            "sun" if theme.is_dark else "moon",
            t("toggle_theme_tip", lang),
            theme,
            self._toggle_appearance,
        )
        layout.addWidget(self.theme_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.settings_button = icon_button(
            "settings",
            t("settings_btn", lang),
            theme,
            self._open_settings,
        )
        layout.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.forensic_button.setAccessibleName(t("forensic_btn", lang))
        self.output_button.setAccessibleName(t("open_output_btn", lang))
        self._set_ffmpeg_state("checking")
        return toolbar

    def _build_shortcuts(self) -> None:
        bindings = (
            ("Ctrl+,", self._open_settings),
            ("Ctrl+A", self._select_all),
            ("Delete", self._delete_selected),
            ("Ctrl+O", self._browse_files),
            ("Return", lambda: self._start_patch(only_selected=True)),
        )
        self._shortcuts: list[QShortcut] = []
        for sequence, slot in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(slot)
            self._shortcuts.append(shortcut)

    def _connect_signals(self) -> None:
        self.queue_view.patch_requested.connect(self._start_patch)
        self.queue_view.focus_changed.connect(self._on_queue_focus_changed)
        self.queue_view.selection_changed.connect(self._refresh_readiness)

        self.inspector.patch_requested.connect(
            lambda timescale, strategy: self._start_patch(
                timescale, strategy, only_selected=True
            )
        )
        self.inspector.cancel_requested.connect(self._handle_cancel)
        self.inspector.profile_changed.connect(self._on_profile_changed)
        self.inspector.strategy_changed.connect(self._refresh_readiness)

        self.console.repair_requested.connect(self._repair_for_mobile_from_console)
        self.console.expanded_changed.connect(self._on_console_expanded)

    def _connect_bridge(self) -> None:
        self.bridge.log.connect(self._on_log)
        self.bridge.progress.connect(self._on_progress)
        self.bridge.probe_done.connect(self._on_probe_done)
        self.bridge.patch_done.connect(self._on_patch_done)
        self.bridge.queue_changed.connect(self._on_queue_changed)
        self.bridge.ffmpeg.connect(self._on_ffmpeg)
        self.bridge.update_available.connect(self._on_update_available)
        self.bridge.update_download.connect(self._on_update_download)
        self.bridge.drained.connect(self._flush_events)

    # --------------------------------------------------------------- geometry
    def _restore_geometry(self) -> None:
        if not self.settings.remember_geometry:
            return
        geometry = self._qt_settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = self._qt_settings.value("windowState")
        if state is not None:
            self.restoreState(state)

    def _save_geometry(self) -> None:
        if not self.settings.remember_geometry:
            return
        self._qt_settings.setValue("geometry", self.saveGeometry())
        self._qt_settings.setValue("windowState", self.saveState())
        self._qt_settings.sync()

    def _load_queue(self) -> None:
        queue_file = app_data_dir() / "queue.json"
        if not queue_file.exists():
            return
        restored = InputQueue.load(queue_file, migrate_legacy=True)
        if len(restored):
            self.controller.items = restored
            self.controller.queue = restored.paths()

    # ------------------------------------------------------------------ theme
    def _on_theme_changed(self, theme: Theme) -> None:
        self.theme = theme
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, theme)

        self.theme_button.setIcon(
            get_icon("sun" if theme.is_dark else "moon", theme.is_dark)
        )
        self.settings_button.setIcon(get_icon("settings", theme.is_dark))
        self._set_ffmpeg_state(self._ff_state, self._ff_detail)
        self._update_title_bar()
        if self.isVisible():
            apply_backdrop(self, self.settings, theme)

    def _update_title_bar(self) -> None:
        update_title_bar_theme(
            self, self.theme.is_dark, self.theme.color("toolbar_bg")
        )

    def _toggle_appearance(self) -> None:
        self.settings.appearance = (
            "light" if self.settings.appearance == "dark" else "dark"
        )
        self.settings.save_async()
        self.theme_manager.apply(self.settings)
        self._update_title_bar()
        if self.isVisible():
            apply_backdrop(self, self.settings, self.theme_manager.theme)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._update_title_bar()
        apply_backdrop(self, self.settings, self.theme_manager.theme)

    # --------------------------------------------------------------- ffmpeg UI
    def _set_ffmpeg_state(self, state: str, detail: str = "") -> None:
        self._ff_state = state
        self._ff_detail = detail
        theme = self.theme_manager.theme
        lang = self.settings.language

        if state == "ready":
            text = t("ffmpeg_ok", lang)
            color = theme.color("success")
            background = theme.color("accent_light")
        elif state == "missing":
            text = t("ffmpeg_not_found", lang)
            color = theme.color("danger")
            background = theme.color("surface_raised")
        elif state == "downloading":
            text = detail or t("ffmpeg_downloading", lang, percent=0)
            color = theme.color("text2")
            background = theme.color("surface_raised")
        else:
            text = t("checking_ffmpeg", lang)
            color = theme.color("text2")
            background = theme.color("surface_raised")

        self.ffmpeg_button.setText(text)
        self.ffmpeg_button.setToolTip(text)
        self.ffmpeg_button.setAccessibleName(text)
        self.ffmpeg_button.setStyleSheet(
            "QPushButton {"
            f"background: {background};"
            f"color: {color};"
            f"border: 1px solid {theme.color('border')};"
            f"border-radius: {RADIUS_PILL}px;"
            f"padding: 0 {theme.inner}px;"
            f"font-size: {theme.fonts.caption}px;"
            "}"
            "QPushButton:hover {"
            f"background: {theme.color('surface_hover')};"
            f"border-color: {theme.color('border_hover')};"
            "}"
        )

    def _show_ffmpeg_menu(self) -> None:
        lang = self.settings.language
        menu = QMenu(self)
        menu.addAction(t("test_ffmpeg", lang), self._init_ffmpeg)
        download = menu.addAction(
            t("ffmpeg_auto_download_btn", lang),
            self.controller.start_ffmpeg_download,
        )
        download.setEnabled(self._ff_state != "downloading")
        menu.addAction(t("ffmpeg_folder_btn", lang), self._pick_ffmpeg)
        anchor = self.ffmpeg_button.mapToGlobal(
            QPoint(0, self.ffmpeg_button.height())
        )
        menu.exec(anchor)

    def _init_ffmpeg(self) -> None:
        if self._ff_state == "downloading" or self.controller.ffmpeg_downloading:
            return
        if self._ff_init_thread is not None and self._ff_init_thread.is_alive():
            return
        self._set_ffmpeg_state("checking")
        self._ff_init_thread = threading.Thread(
            target=self._init_ffmpeg_worker, daemon=True, name="fps-ffmpeg-init"
        )
        self._ff_init_thread.start()

    def _init_ffmpeg_worker(self) -> None:
        paths = self.controller.init_ffmpeg()
        self.controller.emit(
            FFmpegDownloadEvent("ready" if paths else "missing", paths=paths)
        )

    def _pick_ffmpeg(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self,
            t("ffmpeg_dir", self.settings.language),
            self.settings.ffmpeg_dir or "",
        )
        if chosen:
            self.settings.ffmpeg_dir = chosen
            self.settings.save_async()
            self._init_ffmpeg()

    def _on_ffmpeg(self, event: FFmpegDownloadEvent) -> None:
        lang = self.settings.language
        if event.stage == "downloading":
            self._set_ffmpeg_state(
                "downloading", t("ffmpeg_downloading", lang, percent=event.percent)
            )
        elif event.stage in ("extracting", "verifying"):
            self._set_ffmpeg_state("downloading", t("ffmpeg_extracting", lang))
        elif event.stage in ("ready", "done"):
            self._set_ffmpeg_state("ready")
            self._refresh_readiness()
            self._probe_pending_queue_items()
            if event.stage == "done":
                self.console.append(t("ffmpeg_installed", lang), "OK")
        elif event.stage in ("missing", "error"):
            self._set_ffmpeg_state("missing")
            self._refresh_readiness()
            self._probe_pending_queue_items()

    def _probe_pending_queue_items(self) -> None:
        if self._probe_running:
            return
        pending = [
            item.path
            for item in self.controller.items.items
            if item.info is None and item.status == "pending"
        ]
        if not pending:
            return
        ffprobe_path = self.controller.ffmpeg.ffprobe if self.controller.ffmpeg else None
        self._probe_running = True

        def job() -> None:
            from ..core.errors import FPSPatcherError
            from ..core.prober import probe

            try:
                for path in pending:
                    if self.controller.items.get(path) is None:
                        continue
                    self.controller.items.set_status(path, "probing")
                    self.controller.emit(QueueChangedEvent("probing"))
                    try:
                        info = probe(path, ffprobe_path)
                        self.controller.items.set_info(path, info)
                    except FPSPatcherError as exc:
                        self.controller.items.set_info(path, None, str(exc))
                        self.controller.emit(
                            LogEvent(f"Probe failed {path.name}: {exc}", "ERROR")
                        )
                    self.controller.emit(QueueChangedEvent("probed"))
            finally:
                self._probe_running = False

        threading.Thread(
            target=job, daemon=True, name="fps-probe-restored"
        ).start()

    # ----------------------------------------------------------------- watcher
    def _sync_watcher(self) -> None:
        if self._watcher is not None:
            self._watcher.stop(wait=False)
            self._watcher = None
        if not self.settings.watch_folder_enabled:
            return
        folder = Path(self.settings.watch_folder) if self.settings.watch_folder else None
        if folder is None or not folder.is_dir():
            self.console.append("Watch folder is not configured or missing.", "WARN")
            return
        self._watcher = FolderWatcher(folder, self._watch_inbox.put)
        self._watcher.start()
        self.console.append(f"Watching folder: {folder}", "INFO")

    def _drain_watch_inbox(self) -> None:
        if self.controller.busy or self._watch_inbox.empty():
            return
        paths: list[Path] = []
        while True:
            try:
                paths.append(self._watch_inbox.get_nowait())
            except queue.Empty:
                break
        if not paths:
            return
        paths = list(dict.fromkeys(paths))
        self.controller.add_files(paths, select=False)
        self.queue_view.refresh()
        self.console.append(f"Watch folder: patching {len(paths)} file(s)", "INFO")
        self._watch_batch_active = True
        self.controller.start_patch(
            QUICK_PATCH_TIMESCALE,
            self.settings.strategy,
            only_selected=False,
            only_paths=paths,
        )
        if not self.controller.busy:
            self._watch_batch_active = False

    def _notify_watch_done(self, message: str) -> None:
        threading.Thread(target=toast, args=(message,), daemon=True).start()

    def _cleanup_stale_preflight(self) -> None:
        from ..core.preflight import cleanup_stale_preflight

        folders: set[Path] = {item.path.parent for item in self.controller.items.items}
        if self.settings.output_dir:
            folders.add(Path(self.settings.output_dir))
        if self.settings.watch_folder_enabled and self.settings.watch_folder:
            folders.add(Path(self.settings.watch_folder))
        if folders:
            threading.Thread(
                target=cleanup_stale_preflight,
                args=(folders,),
                daemon=True,
                name="fps-preflight-cleanup",
            ).start()

    def _sync_explorer_menu(self) -> None:
        try:
            if self.settings.explorer_menu:
                shell_integration.install()
            else:
                shell_integration.uninstall()
        except Exception as exc:
            self.console.append(f"Explorer context menu update failed: {exc}", "ERROR")

    # ------------------------------------------------------------------ events
    def _on_log(self, event: LogEvent) -> None:
        self._pending_logs.append((event.message, event.level))

    def _on_progress(self, event: ProgressEvent) -> None:
        self._latest_progress = event

    def _on_queue_changed(self, _event: QueueChangedEvent) -> None:
        self._queue_dirty = True

    def _on_probe_done(self, event: ProbeDoneEvent) -> None:
        self._queue_dirty = True
        if self.controller.queue:
            self.console.set_context_files(target=self.controller.queue[-1])
        if event.info is not None:
            if event.queue_count > 1:
                self.console.append(
                    f"Batch queued ({event.queue_count} files). "
                    f"1st clip: {event.info.fps:.3f} FPS",
                    "OK",
                )
            else:
                self.console.append(f"Detected {event.info.fps:.3f} FPS", "OK")
        elif event.error:
            self.console.append(f"Probe failed: {event.error}", "ERROR")

    def _on_patch_done(self, event: PatchDoneEvent) -> None:
        lang = self.settings.language
        self._queue_dirty = True
        self._latest_progress = None

        if self._watch_batch_active:
            self._watch_batch_active = False
            if event.cancelled:
                self._notify_watch_done("Watch folder: patch cancelled")
            elif event.failed:
                self._notify_watch_done(
                    f"Watch folder: {len(event.failed)} file(s) failed"
                )
            else:
                self._notify_watch_done(
                    f"Watch folder: {len(event.batch_results)} file(s) patched"
                )

        if event.cancelled:
            self.console.append(f"Operation cancelled: {event.error}", "WARN")
            self.inspector.set_idle()
        elif event.batch_results:
            self._last_output = event.batch_results[-1].output
            source = self.controller.queue[-1] if self.controller.queue else None
            self.console.set_context_files(
                target=self._last_output, source=source
            )
            done_count = len(event.batch_results)
            experimental = sum(1 for result in event.batch_results if result.experimental)
            suffix = f" ({experimental} experimental)" if experimental else ""
            self.console.append(
                f"Batch finished: {done_count}/{event.total_files} files patched{suffix}.",
                "WARN" if experimental else "OK",
            )
            if event.total_files > 1 or event.failed or experimental:
                message = t(
                    "batch_summary_msg",
                    lang,
                    ok=done_count - experimental,
                    failed=len(event.failed),
                    total=event.total_files,
                )
                if experimental:
                    message += "\n" + t(
                        "batch_summary_experimental",
                        lang,
                        experimental=experimental,
                    )
                QTimer.singleShot(
                    0,
                    lambda msg=message: QMessageBox.information(
                        self, t("batch_summary_title", lang), msg
                    ),
                )
            if self.settings.open_when_done and self._last_output:
                QTimer.singleShot(0, self._open_output)
        elif event.result is not None:
            self._last_output = event.result.output
            source = self.controller.queue[-1] if self.controller.queue else None
            self.console.set_context_files(
                target=self._last_output, source=source
            )
            if self.settings.open_when_done:
                QTimer.singleShot(0, self._open_output)
        else:
            self.console.append(f"Patch failed: {event.error}", "ERROR")
            for line in event.stderr_tail:
                self.console.append(line, "WARN")
            self.inspector.set_idle()

        self._refresh_readiness()

    def _flush_events(self) -> None:
        if self._pending_logs:
            batch, self._pending_logs = self._pending_logs, []
            self.console.append_batch(batch)
        if self._latest_progress is not None:
            progress, self._latest_progress = self._latest_progress, None
            self._refresh_readiness()
            self.inspector.set_progress(progress)
        if self._queue_dirty:
            self._queue_dirty = False
            self.queue_view.refresh()
            self._sync_focused_item()
        self._refresh_readiness()

    def _sync_focused_item(self) -> None:
        path = self.queue_view.focused_path()
        item = self.controller.items.get(path) if path is not None else None
        if item is None:
            items = self.controller.items.items
            if items:
                item = next(
                    (i for i in reversed(items) if i.info is not None), items[-1]
                )
        self.inspector.set_focused_item(item)

    def _on_queue_focus_changed(self, item: object) -> None:
        if item is not None and not hasattr(item, "path"):
            item = self.controller.items.get(Path(str(item)))
        self.inspector.set_focused_item(item)  # type: ignore[arg-type]

    def _on_profile_changed(self) -> None:
        self.queue_view.refresh()
        self._sync_focused_item()
        self._refresh_readiness()

    def _refresh_readiness(self) -> None:
        strategy = self.inspector.strategy() or self.settings.strategy
        needs_ffmpeg = strategy_requires_ffmpeg(strategy)
        can_patch = bool(self.controller.queue or self.controller.current) and (
            not needs_ffmpeg or self.controller.ffmpeg is not None
        )
        busy = self.controller.busy

        if busy != self._last_busy:
            self._last_busy = busy
            self.queue_view.set_busy(busy)
            self.inspector.set_busy(busy)
        if can_patch != self._last_can_patch:
            self._last_can_patch = can_patch
            self.inspector.set_can_patch(can_patch)

    # ----------------------------------------------------------------- actions
    def _start_patch(
        self,
        timescale: int | None = None,
        strategy: str | None = None,
        only_selected: bool = True,
    ) -> None:
        effective_timescale = (
            timescale
            if timescale is not None
            else self.inspector.timescale() or _DEFAULT_TIMESCALE
        )
        effective_strategy = (
            strategy
            if strategy is not None
            else self.inspector.strategy() or self.settings.strategy
        )
        self.controller.start_patch(
            effective_timescale, effective_strategy, only_selected=only_selected
        )
        self._refresh_readiness()

    def _handle_cancel(self) -> None:
        if self.settings.confirm_cancel:
            answer = QMessageBox.question(
                self,
                t("app_title", self.settings.language),
                t("confirm_cancel_run", self.settings.language),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.controller.cancel()

    def _select_all(self) -> None:
        self.controller.items.select_all(True)
        self.queue_view.refresh()

    def _delete_selected(self) -> None:
        self.controller.remove_selected()

    def _browse_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            t("browse_files", self.settings.language),
            "",
            _video_filter(),
        )
        if paths:
            self.controller.add_files([Path(path) for path in paths])
            self.queue_view.refresh()

    def _open_output(self) -> None:
        target: Path | None = None
        if self._last_output is not None and self._last_output.exists():
            target = self._last_output
        if target is None and self.settings.output_dir:
            candidate = Path(self.settings.output_dir)
            if candidate.exists():
                target = candidate
        if target is None and self.controller.queue:
            target = self.controller.queue[-1].parent
        if target is None:
            return
        if os.name == "nt":
            if target.is_file():
                subprocess.Popen(["explorer", "/select,", str(target)])
            else:
                os.startfile(str(target))
        elif hasattr(os, "startfile"):
            os.startfile(str(target))
        else:
            subprocess.Popen(["xdg-open", str(target.parent if target.is_file() else target)])

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.theme_manager, self)
        dialog.applied.connect(self._on_settings_applied)
        dialog.download_requested.connect(self.controller.start_ffmpeg_download)
        dialog.exec()

    def _on_settings_applied(self, applied: object) -> None:
        if isinstance(applied, Settings) and applied is not self.settings:
            for item in fields(Settings):
                if item.init:
                    setattr(self.settings, item.name, getattr(applied, item.name))

        self.theme_manager.apply(self.settings)
        self._apply_always_on_top()
        self._retranslate()
        self._sync_watcher()
        self._sync_explorer_menu()
        self._init_ffmpeg()
        self.queue_view.refresh()
        self._sync_focused_item()
        self.inspector.refresh_readiness()
        self._refresh_readiness()
        if self.isVisible():
            apply_backdrop(self, self.settings, self.theme_manager.theme)

    def _open_forensic(self) -> None:
        ForensicDialog(self.settings, self.theme_manager, self).exec()

    def _apply_always_on_top(self) -> None:
        wanted = bool(self.settings.always_on_top)
        current = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        if wanted == current:
            return
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, wanted)
        if visible:
            self.show()

    def _on_console_expanded(self, expanded: bool) -> None:
        self._console_expanded = bool(expanded)

    def _repair_for_mobile_from_console(self, candidate: object | None = None) -> None:
        raw = getattr(candidate, "path", candidate)
        target = Path(str(raw)) if raw else None
        if target is None or not target.is_file():
            focused = self.queue_view.focused_path()
            selected = self.queue_view.selected_paths()
            if focused is not None and focused.is_file():
                target = focused
            elif selected:
                target = Path(selected[0])
            elif self.controller.queue:
                target = self.controller.queue[-1]
        if target is None or not target.is_file():
            chosen, _ = QFileDialog.getOpenFileName(
                self,
                t("repair_for_mobile", self.settings.language),
                "",
                _video_filter(),
            )
            if not chosen:
                return
            target = Path(chosen)

        def job(path: Path) -> None:
            output = self.controller.repair_file_for_mobile(path)
            if output is not None:
                self.controller.emit(
                    LogEvent(f"Mobile repair complete: {output}", "OK")
                )

        threading.Thread(
            target=job, args=(target,), daemon=True, name="fps-mobile-repair"
        ).start()

    def _retranslate(self) -> None:
        lang = self.settings.language
        self.title_label.setText(t("app_title", lang))
        self.forensic_button.setText(t("forensic_btn", lang))
        self.forensic_button.setAccessibleName(t("forensic_btn", lang))
        self.output_button.setText(t("open_output_btn", lang))
        self.output_button.setAccessibleName(t("open_output_btn", lang))
        self.theme_button.setToolTip(t("toggle_theme_tip", lang))
        self.theme_button.setAccessibleName(t("toggle_theme_tip", lang))
        self.settings_button.setToolTip(t("settings_btn", lang))
        self.settings_button.setAccessibleName(t("settings_btn", lang))
        self._set_ffmpeg_state(self._ff_state, self._ff_detail)
        if self._update_info is not None:
            self._show_update_button()

    # ------------------------------------------------------------------ update
    def _on_update_available(self, event: UpdateAvailableEvent) -> None:
        self._update_info = event.info
        self._show_update_button()

    def _show_update_button(self) -> None:
        info = self._update_info
        if info is None:
            return
        text = t(
            "update_available_btn",
            self.settings.language,
            version=getattr(info, "version", ""),
        )
        self.update_button.setText(text)
        self.update_button.setToolTip(text)
        self.update_button.setAccessibleName(text)
        self.update_button.setEnabled(True)
        self.update_button.setVisible(True)

    def _on_update_clicked(self) -> None:
        info = self._update_info
        if info is None:
            return
        lang = self.settings.language
        notes = getattr(info, "notes", "").strip()
        if len(notes) > 400:
            notes = notes[:400] + "..."
        prompt = t(
            "update_dialog_prompt",
            lang,
            version=getattr(info, "version", ""),
            notes=notes or "-",
        )
        answer = QMessageBox.question(
            self, t("update_dialog_title", lang), prompt
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.update_button.setText(t("update_downloading", lang, percent=0))
        self.update_button.setEnabled(False)
        self.controller.start_update_download(info)

    def _on_update_download(self, event: UpdateDownloadEvent) -> None:
        lang = self.settings.language
        if event.stage == "downloading":
            self.update_button.setText(
                t("update_downloading", lang, percent=event.percent)
            )
            self.update_button.setEnabled(False)
        elif event.stage == "done":
            self.update_button.setText(t("update_ready_launch", lang))
            self.update_button.setEnabled(False)
            if event.path is None:
                self._show_update_button()
                return
            try:
                from ..core.updater import launch_installer

                launch_installer(event.path)
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    t("app_title", lang),
                    t("update_failed", lang, error=str(exc)),
                )
                self._show_update_button()
                return
            self.close()
        elif event.stage == "error":
            message = event.error or "Unknown error"
            if "SHA-256" in message:
                display = t("update_sha256_failed", lang)
            else:
                display = t("update_failed", lang, error=message)
            QMessageBox.critical(self, t("app_title", lang), display)
            self._show_update_button()

    # -------------------------------------------------------------------- close
    def closeEvent(self, event: QCloseEvent) -> None:
        self.bridge.stop()
        self._watch_timer.stop()
        if self._watcher is not None:
            self._watcher.stop(wait=False)
            self._watcher = None
        self.controller.shutdown()
        try:
            self._save_geometry()
            self.settings.save()
            self.controller.items.save(app_data_dir() / "queue.json")
        except OSError:
            log.exception("Could not persist Qt UI state")
        finally:
            event.accept()
