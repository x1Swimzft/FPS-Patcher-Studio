"""Main-thread seam between AppController's event queue and Qt widgets.

``AppController`` keeps its ``threading.Thread`` workers and only ever puts
events on ``controller.events``. This bridge drains that queue with a QTimer on
the Qt main thread, so widgets are never touched from a worker.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

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
