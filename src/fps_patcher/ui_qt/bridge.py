"""Main-thread seam between AppController's event queue and Qt widgets.

``AppController`` keeps its ``threading.Thread`` workers and only ever puts
events on ``controller.events``. This bridge drains that queue with a QTimer on
the Qt main thread, so widgets are never touched from a worker.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.diagnostic_logger import auto_save_diagnostic_log
from ..core.models import (
    Event,
    FFmpegDownloadEvent,
    LogEvent,
    PatchDoneEvent,
    ProbeDoneEvent,
    ProgressEvent,
    QueueChangedEvent,
    UpdateAvailableEvent,
    UpdateDownloadEvent,
)

if TYPE_CHECKING:
    from ..app.controller import AppController

POLL_MS_BUSY = 50
POLL_MS_IDLE = 200
DRAIN_LIMIT = 500


class ControllerBridge(QObject):
    """Drain controller events on the main thread and re-emit them as Qt signals."""

    log = Signal(object)
    progress = Signal(object)
    probe_done = Signal(object)
    patch_done = Signal(object)
    queue_changed = Signal(object)
    ffmpeg = Signal(object)
    update_available = Signal(object)
    update_download = Signal(object)
    drained = Signal()

    # Forensic task seam: workers emit, the dialog's slots run on the main thread.
    forensic_status = Signal(str)
    forensic_finished = Signal(str, object)
    forensic_failed = Signal(str)

    def __init__(self, controller: AppController, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._running = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._drain)
        self.start()

    def start(self) -> None:
        """Start polling. A no-op when the timer is already active."""
        self._running = True
        if not self._timer.isActive():
            self._timer.start(0)

    def stop(self) -> None:
        self._running = False
        self._timer.stop()

    def _drain(self) -> None:
        seen = False

        def handler(event: Event) -> None:
            nonlocal seen
            seen = True
            self._emit(event)

        try:
            self._controller.drain(handler, limit=DRAIN_LIMIT)
        finally:
            if seen:
                self.drained.emit()
            if self._running:
                self._timer.start(POLL_MS_BUSY if self._controller.busy else POLL_MS_IDLE)

    def _emit(self, event: Event) -> None:
        if isinstance(event, LogEvent):
            self.log.emit(event)
        elif isinstance(event, ProgressEvent):
            self.progress.emit(event)
        elif isinstance(event, ProbeDoneEvent):
            self.probe_done.emit(event)
        elif isinstance(event, PatchDoneEvent):
            self.patch_done.emit(event)
        elif isinstance(event, QueueChangedEvent):
            self.queue_changed.emit(event)
        elif isinstance(event, FFmpegDownloadEvent):
            self.ffmpeg.emit(event)
        elif isinstance(event, UpdateAvailableEvent):
            self.update_available.emit(event)
        elif isinstance(event, UpdateDownloadEvent):
            self.update_download.emit(event)

    def start_forensic_task(self, kind: str, job: Callable[[], object]) -> None:
        """Run ``job`` off the GUI thread; emit only signals from the worker."""

        def worker() -> None:
            try:
                result = job()
            except Exception as exc:
                self.forensic_failed.emit(f"{type(exc).__name__}: {exc}")
            else:
                if result is None:
                    self.forensic_failed.emit(f"{kind} failed")
                else:
                    self.forensic_finished.emit(kind, result)

        threading.Thread(
            target=worker, daemon=True, name=f"fps-forensic-{kind}"
        ).start()

    def forensic_repair(self, source: Path, output: Path | None = None) -> None:
        """Repair ``source`` for mobile in a worker thread."""
        self.forensic_status.emit("repairing")
        self.start_forensic_task(
            "repair", lambda: self._controller.repair_file_for_mobile(source, output)
        )

    def forensic_diagnostic_log(
        self,
        target: Path,
        *,
        source: Path | None = None,
        console_lines: list[str] | None = None,
        mask_paths: bool = True,
    ) -> None:
        """Write an auto-rotated diagnostic log in a worker thread."""
        self.forensic_status.emit("exporting")
        self.start_forensic_task(
            "diagnostic",
            lambda: auto_save_diagnostic_log(
                target_file=target,
                source_file=source,
                console_lines=console_lines,
                mask_paths=mask_paths,
            ),
        )
