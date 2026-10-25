"""Pure seam test: no widgets, only a QCoreApplication/QApplication event loop."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("PySide6")

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
