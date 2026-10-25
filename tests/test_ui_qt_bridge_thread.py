"""ControllerBridge thread-hand-off and toolkit-isolation checks."""

from __future__ import annotations

import ast
import threading
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from fps_patcher.app.controller import AppController  # noqa: E402
from fps_patcher.config import Settings  # noqa: E402
from fps_patcher.core.models import LogEvent  # noqa: E402
from fps_patcher.ui_qt.bridge import ControllerBridge  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "src" / "fps_patcher"
TOOLKITS = frozenset({"PySide6", "customtkinter", "tkinter", "tkinterdnd2"})


def test_worker_log_reaches_main_thread_without_touching_widgets(qtbot: Any) -> None:
    app = QApplication.instance()
    assert app is not None
    main_thread = app.thread()
    controller = AppController(Settings())
    bridge = ControllerBridge(controller)
    bridge.stop()

    label = QLabel("untouched")
    qtbot.addWidget(label)
    slot_threads: list[QThread] = []
    values_seen: list[str] = []

    def on_log(event: LogEvent) -> None:
        slot_threads.append(QThread.currentThread())
        values_seen.append(label.text())

    bridge.log.connect(on_log)
    worker_finished = threading.Event()

    def worker() -> None:
        assert threading.current_thread() is not threading.main_thread()
        controller.events.put(LogEvent("from worker thread", "INFO"))
        worker_finished.set()

    thread = threading.Thread(target=worker, name="bridge-test-worker")
    try:
        with qtbot.waitSignal(bridge.log, timeout=2000) as blocker:
            bridge.start()
            thread.start()
        thread.join(timeout=2)

        assert not thread.is_alive()
        assert worker_finished.is_set()
        assert blocker.args
        assert blocker.args[0].message == "from worker thread"
        # The slot, not the worker, is the only place a widget is read.
        assert slot_threads == [main_thread]
        assert values_seen == ["untouched"]
        assert label.thread() is main_thread
    finally:
        bridge.stop()


def test_core_and_app_never_import_a_ui_toolkit() -> None:
    offenders: list[str] = []
    for folder in ("core", "app"):
        for source in (SRC / folder).rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for node in ast.walk(tree):
                roots: set[str] = set()
                if isinstance(node, ast.Import):
                    roots = {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    roots = {node.module.split(".")[0]}
                bad = roots & TOOLKITS
                if bad:
                    offenders.append(f"{source.relative_to(SRC)}:{node.lineno} {sorted(bad)}")
    assert offenders == []
