"""Pure seam test: no widgets, only a QCoreApplication/QApplication event loop."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, QThread, Slot  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from fps_patcher.core.models import LogEvent  # noqa: E402
from fps_patcher.ui_qt.bridge import ControllerBridge  # noqa: E402


class _FakeController:
    busy = False

    def __init__(self) -> None:
        self.sent = False

    def drain(self, handler: Any, limit: int = 500) -> None:
        if not self.sent:
            self.sent = True
            handler(LogEvent("hello from worker"))


class _RepairController(_FakeController):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[Path, Path | None, threading.Thread]] = []

    def repair_file_for_mobile(self, src: Path, out: Path | None = None) -> Path | None:
        self.calls.append((src, out, threading.current_thread()))
        return out


class _ForensicProbe(QObject):
    def __init__(self, label: QLabel) -> None:
        super().__init__()
        self.label = label
        self.finished: list[tuple[str, object, QThread, str]] = []
        self.failed: list[tuple[str, QThread]] = []

    @Slot(str, object)
    def on_finished(self, kind: str, result: object) -> None:
        self.finished.append(
            (kind, result, QThread.currentThread(), self.label.text())
        )

    @Slot(str)
    def on_failed(self, message: str) -> None:
        self.failed.append((message, QThread.currentThread()))


def test_bridge_emits_log(qtbot: Any) -> None:
    controller = _FakeController()
    bridge = ControllerBridge(controller)  # type: ignore[arg-type]
    bridge.stop()
    try:
        with qtbot.waitSignal(bridge.log, timeout=1000) as blocker:
            bridge.start()
        assert blocker.args
        event = blocker.args[0]
        assert isinstance(event, LogEvent)
        assert event.message == "hello from worker"
    finally:
        bridge.stop()


def test_forensic_repair_worker_and_slot_stay_on_their_threads(qtbot: Any) -> None:
    app = QApplication.instance()
    assert app is not None
    main_thread = app.thread()

    controller = _RepairController()
    bridge = ControllerBridge(controller)  # type: ignore[arg-type]
    bridge.stop()

    label = QLabel("untouched")
    qtbot.addWidget(label)
    probe = _ForensicProbe(label)
    statuses: list[str] = []
    bridge.forensic_status.connect(statuses.append)
    bridge.forensic_finished.connect(probe.on_finished)

    source, output = Path("source.mp4"), Path("output.mp4")
    try:
        with qtbot.waitSignal(bridge.forensic_finished, timeout=2000) as blocker:
            bridge.forensic_repair(source, output)
    finally:
        bridge.stop()

    assert statuses == ["repairing"]
    assert blocker.args == ["repair", output]
    assert len(controller.calls) == 1
    called_source, called_output, worker_thread = controller.calls[0]
    assert (called_source, called_output) == (source, output)
    assert worker_thread is not threading.main_thread()

    assert probe.finished
    kind, result, slot_thread, widget_text = probe.finished[0]
    assert (kind, result) == ("repair", output)
    assert slot_thread is main_thread
    assert widget_text == "untouched"


def test_forensic_task_failure_is_reported_from_a_worker(qtbot: Any) -> None:
    controller = _FakeController()
    bridge = ControllerBridge(controller)  # type: ignore[arg-type]
    bridge.stop()
    probe = _ForensicProbe(QLabel())
    bridge.forensic_failed.connect(probe.on_failed)

    def boom() -> None:
        assert threading.current_thread() is not threading.main_thread()
        raise RuntimeError("nope")

    try:
        with qtbot.waitSignal(bridge.forensic_failed, timeout=2000) as blocker:
            bridge.start_forensic_task("repair", boom)
    finally:
        bridge.stop()

    assert blocker.args == ["RuntimeError: nope"]
    assert probe.failed
    message, slot_thread = probe.failed[0]
    assert message == "RuntimeError: nope"
    assert slot_thread is QApplication.instance().thread()  # type: ignore[union-attr]

