"""Qt main window shell: toolbar, queue/inspector split and controller bridge."""

from __future__ import annotations

import contextlib
import inspect
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
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..app import shell_integration
from ..app.controller import AppController
from ..app.queue_model import InputQueue, QueueItem
from ..app.startup import set_startup_enabled
from ..app.watcher import FolderWatcher
from ..config import Settings, app_data_dir, platform_export_template
from ..core.models import (
    SUPPORTED_EXTENSIONS,
    FFmpegDownloadEvent,
    LogEvent,
    PatchDoneEvent,
    PatchRequest,
    ProbeDoneEvent,
    ProgressEvent,
    QueueChangedEvent,
    UpdateAvailableEvent,
    UpdateDownloadEvent,
)
from ..core.notify import notify
from ..core.patcher import output_base_for
from ..core.platform_profiles import get_profile
from ..core.strategies import strategy_requires_ffmpeg
from ..ui.strings import readiness_check_label, t
from .bridge import ControllerBridge
from .console import ConsolePanel
from .forensic_dialog import ForensicDialog
from .history_dialog import HistoryDialog
from .icons import get_icon
from .inspector import Inspector
from .motion import MotionController
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
from .update_dialog import UpdateDialog
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
        self.motion = MotionController(settings.reduce_motion, self.theme, self)

        self._last_output: Path | None = None
        self._watcher: FolderWatcher | None = None
        self._watch_inbox: queue.Queue[Path] = queue.Queue()
        self._watch_batch_active = False
        self._ff_init_thread: threading.Thread | None = None
        self._ff_state = "checking"
        self._ff_detail = ""
        self._update_info: Any = None
        self._update_prompted = False
        self._update_dialog: UpdateDialog | None = None
        self._pending_update_path: Path | None = None
        self._probe_running = False
        self._pending_logs: list[tuple[str, str]] = []
        self._latest_progress: ProgressEvent | None = None
        self._queue_dirty = False
        self._last_busy: bool | None = None
        self._last_can_patch: bool | None = None
        self._console_expanded = False
        self._tray: QSystemTrayIcon | None = None
        self._force_quit = False
        self._tray_notice_shown = False

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
        self._build_tray_menu()
        self._sync_tray()

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
        self._sync_startup()
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
        self.console.set_animated(True)
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

        self.brand_bar = QFrame(toolbar)
        self.brand_bar.setObjectName("BrandBar")
        self.brand_bar.setFixedSize(3, 18)
        self.brand_bar.setStyleSheet(
            f"background: {theme.color('accent')}; border-radius: 1px;"
        )
        layout.addWidget(self.brand_bar, 0, Qt.AlignmentFlag.AlignVCenter)

        self.title_label = QLabel(t("app_title", lang))
        self.title_label.setProperty("role", "title")
        layout.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.version_badge = QLabel(f"v{__version__}")
        self.version_badge.setProperty("role", "badge")
        layout.addWidget(self.version_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)

        self.ffmpeg_button = QPushButton()
        self.ffmpeg_button.setProperty("variant", "secondary")
        self.ffmpeg_button.setProperty("motionSkip", True)
        self.ffmpeg_button.setFixedHeight(theme.button_height)
        self.ffmpeg_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ffmpeg_button.clicked.connect(self._show_ffmpeg_menu)
        layout.addWidget(self.ffmpeg_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.forensic_button = text_button(
            t("forensic_btn", lang),
            theme,
            self._open_forensic,
            variant="ghost",
            height=theme.button_height,
        )
        layout.addWidget(self.forensic_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.history_button = text_button(
            t("history_btn", lang),
            theme,
            self._open_history,
            variant="ghost",
            height=theme.button_height,
        )
        layout.addWidget(self.history_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.output_button = text_button(
            t("open_output_btn", lang),
            theme,
            self._open_output,
            variant="ghost",
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
        self.history_button.setAccessibleName(t("history_btn", lang))
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
        self.queue_view.forensic_requested.connect(self._open_forensic_for)
        self.queue_view.readiness_clicked.connect(self._log_readiness)

        self.inspector.patch_requested.connect(
            lambda timescale, strategy: self._start_patch(
                timescale, strategy, only_selected=True
            )
        )
        self.inspector.cancel_requested.connect(self._handle_cancel)
        self.inspector.profile_changed.connect(self._on_profile_changed)
        self.inspector.strategy_changed.connect(self._refresh_readiness)
        self.inspector.strategy_changed.connect(self.queue_view.refresh_profile)
        self.inspector.target_changed.connect(self.queue_view.refresh_profile)
        self.inspector.override_changed.connect(self._on_override_changed)

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
        self.motion.set_theme(theme)
        self.motion.set_reduce_motion(bool(self.settings.reduce_motion))
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, theme)

        self.theme_button.setIcon(
            get_icon("sun" if theme.is_dark else "moon", theme.is_dark)
        )
        self.settings_button.setIcon(get_icon("settings", theme.is_dark))
        self.brand_bar.setStyleSheet(
            f"background: {theme.color('accent')}; border-radius: 1px;"
        )
        self._set_ffmpeg_state(self._ff_state, self._ff_detail)
        self._update_title_bar()
        self._apply_window_opacity()
        self.queue_view.refresh_profile()
        if self.isVisible():
            apply_backdrop(self, self.settings, theme)

    def _update_title_bar(self) -> None:
        update_title_bar_theme(
            self, self.theme.is_dark, self.theme.color("toolbar_bg")
        )

    def _apply_window_opacity(self) -> None:
        with contextlib.suppress(Exception):
            self.setWindowOpacity(max(0.85, min(1.0, float(self.settings.window_alpha))))

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
        self._apply_window_opacity()
        apply_backdrop(self, self.settings, self.theme_manager.theme)

    # --------------------------------------------------------------- ffmpeg UI
    def _set_ffmpeg_state(self, state: str, detail: str = "") -> None:
        self._ff_state = state
        self._ff_detail = detail
        theme = self.theme_manager.theme
        lang = self.settings.language

        if state == "ready":
            text = t("ffmpeg_ok", lang)
            color = theme.color("text")
            background = theme.color("accent_dim")
            border = theme.color("success")
        elif state == "missing":
            text = t("ffmpeg_not_found", lang)
            color = theme.color("text")
            background = theme.color("surface_raised")
            border = theme.color("danger")
        elif state == "downloading":
            text = detail or t("ffmpeg_downloading", lang, percent=0)
            color = theme.color("text2")
            background = theme.color("surface_raised")
            border = theme.color("border")
        else:
            text = t("checking_ffmpeg", lang)
            color = theme.color("text2")
            background = theme.color("surface_raised")
            border = theme.color("border")

        self.ffmpeg_button.setText(text)
        self.ffmpeg_button.setToolTip(text)
        self.ffmpeg_button.setAccessibleName(text)
        self.ffmpeg_button.setStyleSheet(
            "QPushButton {"
            f"background: {background};"
            f"color: {color};"
            f"border: 1px solid {border};"
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
        if not self.settings.check_ffmpeg_on_start and not self.settings.ffmpeg_dir:
            self._set_ffmpeg_state("missing")
            self._refresh_readiness()
            return
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
            self.queue_view.refresh()
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
        folder = Path(self.settings.watch_folder) if self.settings.watch_folder else None
        if not self.settings.watch_folder_enabled:
            if self._watcher is not None:
                self._watcher.stop(wait=False)
                self._watcher = None
            return
        if folder is None or not folder.is_dir():
            if self._watcher is not None:
                self._watcher.stop(wait=False)
                self._watcher = None
            self.console.append("Watch folder is not configured or missing.", "WARN")
            return
        # Keep a running watcher: restarting re-primes and would drop exports that
        # finished while the settings dialog was open.
        if self._watcher is not None and self._watcher.folder == folder:
            return
        if self._watcher is not None:
            self._watcher.stop(wait=False)
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
            self.settings.target_timescale(),
            self.settings.strategy,
            only_selected=False,
            only_paths=paths,
        )
        if not self.controller.busy:
            self._watch_batch_active = False

    def _notify_watch_done(self, message: str) -> None:
        self._notify_done(message)

    def _notify_done(self, message: str) -> None:
        mode = self.settings.notify_done
        if mode == "none":
            return
        threading.Thread(target=notify, args=(mode, message), daemon=True).start()

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
        was_watch = self._watch_batch_active

        if self._watcher is not None:
            watched = event.batch_results or (
                [event.result] if event.result is not None else []
            )
            for result in watched:
                self._watcher.record_own_output(result.output)

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
        if not was_watch and not event.cancelled:
            total = event.total_files or len(event.batch_results) + len(event.failed)
            self._notify_done(
                t(
                    "batch_summary_msg",
                    lang,
                    ok=max(total - len(event.failed), 0),
                    failed=len(event.failed),
                    total=total,
                )
            )

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
        self.inspector.set_focused_item(item)

    def _on_override_changed(
        self,
        path: object,
        timescale: int | None,
        strategy: str | None,
        profile: str | None,
    ) -> None:
        if path is None:
            return
        self.controller.items.set_override(
            Path(str(path)),
            timescale=timescale,
            strategy=strategy,
            platform_profile=profile,
        )
        self.queue_view.refresh()
        self.queue_view.refresh_profile()
        self.inspector.refresh_readiness()
        self.inspector.refresh_override()

    def _on_queue_focus_changed(self, item: object) -> None:
        if item is not None and not hasattr(item, "path"):
            item = self.controller.items.get(Path(str(item)))
        self.inspector.set_focused_item(item)  # type: ignore[arg-type]

    def _on_profile_changed(self) -> None:
        self.queue_view.refresh()
        self._sync_focused_item()
        self._refresh_readiness()

    def _log_readiness(self, item: QueueItem) -> None:
        report = self.queue_view.readiness(item)
        if report is None:
            return
        lang = self.settings.language
        profile = get_profile(self.settings.platform_profile)
        self.console.append(
            t(
                "readiness_log_title",
                lang,
                profile=t(profile.label_key, lang),
                score=report.score,
                status=t(f"readiness_{report.status}", lang),
            ),
            "INFO",
        )
        for check in report.checks:
            level = {"warning": "WARN", "error": "ERROR"}.get(check.status, "INFO")
            self.console.append(
                t(
                    "readiness_log_check",
                    lang,
                    check=readiness_check_label(check.check_id, check.label, lang),
                    status=t(f"check_status_{check.status}", lang),
                    detail=check.detail,
                ),
                level,
            )
            if check.recommendation:
                self.console.append(
                    t(
                        "readiness_log_recommend",
                        lang,
                        recommendation=check.recommendation,
                    ),
                    "INFO",
                )

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
        if self.settings.overwrite and self.settings.confirm_overwrite:
            filename_template = (
                self.settings.filename_template
                if self.settings.use_filename_template
                else ""
            )
            existing = 0
            for item in self.controller.items.snapshot_for_run(only_selected):
                out_dir = (
                    Path(self.settings.output_dir)
                    if self.settings.output_dir
                    else item.path.parent
                )
                item_profile = item.platform_profile
                if item_profile:
                    targets = [item_profile]
                elif len(self.settings.export_platforms) > 1:
                    targets = list(self.settings.export_platforms)
                else:
                    targets = [self.settings.platform_profile]
                template = (
                    platform_export_template(filename_template)
                    if len(targets) > 1
                    else filename_template
                )
                for target in targets:
                    base = output_base_for(
                        PatchRequest(
                            src=item.path,
                            out_dir=out_dir,
                            timescale=item.timescale or effective_timescale,
                            strategy=item.strategy or effective_strategy,
                            filename_template=template,
                            platform_profile=target,
                        )
                    )
                    if base.exists():
                        existing += 1
            if existing:
                answer = QMessageBox.question(
                    self,
                    t("app_title", self.settings.language),
                    t(
                        "confirm_overwrite_run",
                        self.settings.language,
                        count=existing,
                    ),
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
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
        dialog.deleteLater()

    def _on_settings_applied(self, applied: object) -> None:
        if isinstance(applied, Settings) and applied is not self.settings:
            for item in fields(Settings):
                if item.init:
                    setattr(self.settings, item.name, getattr(applied, item.name))

        self.theme_manager.apply(self.settings)
        self._apply_always_on_top()
        self._retranslate()
        self._sync_tray()
        self._sync_startup(notify=True)
        self._sync_watcher()
        self._sync_explorer_menu()
        self._init_ffmpeg()
        self.queue_view.refresh()
        self.queue_view.refresh_profile()
        self._sync_focused_item()
        self.inspector.refresh_settings()
        self.inspector.refresh_readiness()
        self._refresh_readiness()
        if self.isVisible():
            apply_backdrop(self, self.settings, self.theme_manager.theme)

    def _open_forensic(self) -> None:
        ForensicDialog(self.settings, self.theme_manager, self).exec()

    def _open_history(self) -> None:
        HistoryDialog(self.settings, self.theme_manager, self.controller, self).exec()

    def _open_forensic_for(self, path: object) -> None:
        target = Path(str(path))
        params = inspect.signature(ForensicDialog.__init__).parameters
        if "preselected_path" in params:
            dialog = ForensicDialog(
                self.settings, self.theme_manager, self, preselected_path=target
            )
        else:
            dialog = ForensicDialog(self.settings, self.theme_manager, self)
            original_edit = getattr(dialog, "original_edit", None)
            if original_edit is not None:
                original_edit.setText(str(target))
        dialog.exec()

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
        self.history_button.setText(t("history_btn", lang))
        self.history_button.setAccessibleName(t("history_btn", lang))
        self.output_button.setText(t("open_output_btn", lang))
        self.output_button.setAccessibleName(t("open_output_btn", lang))
        self.theme_button.setToolTip(t("toggle_theme_tip", lang))
        self.theme_button.setAccessibleName(t("toggle_theme_tip", lang))
        self.settings_button.setToolTip(t("settings_btn", lang))
        self.settings_button.setAccessibleName(t("settings_btn", lang))
        if hasattr(self, "_tray_show_action"):
            self._tray_show_action.setText(t("tray_show", lang))
            self._tray_quit_action.setText(t("tray_quit", lang))
        if self._tray is not None:
            self._tray.setToolTip(t("app_title", lang))
        self._set_ffmpeg_state(self._ff_state, self._ff_detail)
        if self._update_info is not None:
            self._show_update_button()

    # ------------------------------------------------------------------ update
    def _on_update_available(self, event: UpdateAvailableEvent) -> None:
        self._update_info = event.info
        self._show_update_button()
        QTimer.singleShot(0, self._prompt_update_on_startup)

    def _prompt_update_on_startup(self) -> None:
        info = self._update_info
        if info is None or self._update_prompted:
            return
        self._update_prompted = True
        if self.settings.skipped_update_version == getattr(info, "version", ""):
            return
        self._open_update_dialog(info)

    def _open_update_dialog(self, info: Any) -> None:
        dialog = self._update_dialog
        if dialog is None:
            dialog = UpdateDialog(info, self.settings, self)
            dialog.update_requested.connect(
                lambda: self.controller.start_update_download(info)
            )
            dialog.skip_requested.connect(lambda: self._on_update_skip(info))
            dialog.cancel_requested.connect(self.controller.cancel_update_download)
            self._update_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_update_skip(self, info: Any) -> None:
        self.settings.skipped_update_version = getattr(info, "version", "")
        self.settings.save_async()
        if self._update_dialog is not None:
            self._update_dialog.close()

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
        if self._pending_update_path is not None:
            self._apply_downloaded_update(self._pending_update_path)
            return
        info = self._update_info
        if info is None:
            return
        self._open_update_dialog(info)

    def _apply_downloaded_update(self, path: Path) -> None:
        lang = self.settings.language
        if self.controller.busy:
            self.console.append(t("update_busy_deferred", lang), "INFO")
            return
        self._pending_update_path = None
        try:
            if path.suffix.lower() == ".zip":
                from ..core.updater import apply_portable_update

                apply_portable_update(path)
            else:
                from ..core.updater import launch_installer

                launch_installer(path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                t("app_title", lang),
                t("update_failed", lang, error=str(exc)),
            )
            self._show_update_button()
            return
        self.close()

    def _on_update_download(self, event: UpdateDownloadEvent) -> None:
        lang = self.settings.language
        dialog = self._update_dialog
        if event.stage == "downloading":
            self.update_button.setText(
                t("update_downloading", lang, percent=event.percent)
            )
            self.update_button.setEnabled(False)
            if dialog is not None:
                dialog.set_progress(event.percent)
        elif event.stage == "done":
            if dialog is not None:
                dialog.download_finished()
            if event.path is None:
                self._show_update_button()
                return
            if self.controller.busy:
                self._pending_update_path = event.path
                text = t("update_ready_install", lang)
                self.update_button.setText(text)
                self.update_button.setToolTip(text)
                self.update_button.setAccessibleName(text)
                self.update_button.setEnabled(True)
                self.console.append(t("update_busy_deferred", lang), "INFO")
                return
            self._apply_downloaded_update(event.path)
        elif event.stage == "cancelled":
            if dialog is not None:
                dialog.download_cancelled()
            self._show_update_button()
        elif event.stage == "error":
            message = event.error or "Unknown error"
            if "SHA-256" in message:
                display = t("update_sha256_failed", lang)
            else:
                display = t("update_failed", lang, error=message)
            if dialog is not None and dialog.isVisible():
                dialog.download_failed(display)
            else:
                QMessageBox.critical(self, t("app_title", lang), display)
            self._show_update_button()

    # -------------------------------------------------------------------- tray
    def _sync_startup(self, notify: bool = False) -> None:
        if set_startup_enabled(self.settings.start_with_windows):
            return
        lang = self.settings.language
        self.console.append(t("startup_failed", lang), "WARN")
        if notify:
            QMessageBox.warning(self, t("app_title", lang), t("startup_failed", lang))

    @property
    def tray_available(self) -> bool:
        """True when the tray icon is live, so the window may start hidden."""
        return self._tray is not None

    def _build_tray_menu(self) -> None:
        lang = self.settings.language
        self._tray_menu = QMenu(self)
        self._tray_show_action = self._tray_menu.addAction(
            t("tray_show", lang), self._show_from_tray
        )
        self._tray_quit_action = self._tray_menu.addAction(
            t("tray_quit", lang), self._quit_from_tray
        )

    def _sync_tray(self) -> None:
        app = QApplication.instance()
        wanted = bool(self.settings.tray_enabled) and QSystemTrayIcon.isSystemTrayAvailable()
        if wanted and self._tray is None:
            icon = self.windowIcon()
            if icon.isNull() and isinstance(app, QApplication):
                icon = app.windowIcon()
            if icon.isNull():
                icon = get_icon("settings", self.theme.is_dark)
            self._tray = QSystemTrayIcon(icon, self)
            self._tray.setToolTip(t("app_title", self.settings.language))
            self._tray.setContextMenu(self._tray_menu)
            self._tray.activated.connect(self._on_tray_activated)
            self._tray.show()
        elif not wanted and self._tray is not None:
            self._tray.hide()
            self._tray.deleteLater()
            self._tray = None
        if isinstance(app, QApplication):
            app.setQuitOnLastWindowClosed(not wanted)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        self._force_quit = True
        if self._tray is not None:
            self._tray.hide()
        self.close()
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.quit()

    # -------------------------------------------------------------------- close
    def closeEvent(self, event: QCloseEvent) -> None:
        if (
            self._tray is not None
            and self.settings.tray_enabled
            and not self._force_quit
        ):
            self.hide()
            with contextlib.suppress(OSError):
                self._save_geometry()
                self.settings.save()
                self.controller.items.save(app_data_dir() / "queue.json")
            if not self._tray_notice_shown:
                self._tray_notice_shown = True
                lang = self.settings.language
                message = t(
                    "tray_patching" if self._last_busy else "tray_background", lang
                )
                with contextlib.suppress(Exception):
                    self._tray.showMessage(
                        t("app_title", lang),
                        message,
                        QSystemTrayIcon.MessageIcon.Information,
                        2500,
                    )
            event.ignore()
            return
        self.motion.stop_all()
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
            if self._tray is not None:
                self._tray.hide()
            app = QApplication.instance()
            if isinstance(app, QApplication):
                app.setQuitOnLastWindowClosed(True)
            event.accept()
