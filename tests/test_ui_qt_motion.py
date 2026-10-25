"""Qt motion parity: reduce-motion snapping, real animation and shutdown."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QAbstractAnimation, QPropertyAnimation  # noqa: E402
from PySide6.QtWidgets import QPushButton  # noqa: E402

from fps_patcher.config import Settings  # noqa: E402
from fps_patcher.ui_qt.console import ConsolePanel  # noqa: E402
from fps_patcher.ui_qt.inspector import Inspector  # noqa: E402
from fps_patcher.ui_qt.motion import MotionController  # noqa: E402
from fps_patcher.ui_qt.theme import ThemeManager, make_theme  # noqa: E402
from fps_patcher.ui_qt.widgets import SegmentedControl  # noqa: E402


def _running(widget: Any) -> list[QAbstractAnimation]:
    return [
        animation
        for animation in widget.findChildren(QAbstractAnimation)
        if animation.state() == QAbstractAnimation.State.Running
    ]


def test_reduce_motion_segment_snaps_to_end(qtbot: Any) -> None:
    settings = Settings(reduce_motion=True)
    segment = SegmentedControl(["A", "B", "C"], make_theme(settings))
    qtbot.addWidget(segment)
    segment.set_reduce_motion(True)

    segment.set_value("C")

    assert segment.thumbPosition == 2.0
    assert segment._thumb_anim is None
    assert _running(segment) == []


def test_reduce_motion_console_reaches_full_height_without_animation(qtbot: Any) -> None:
    settings = Settings(reduce_motion=True)
    console = ConsolePanel(settings, ThemeManager(settings))
    qtbot.addWidget(console)
    console.set_animated(True)

    console.set_expanded(True)

    assert console.is_expanded is True
    assert console.height() == 180
    assert console.minimumHeight() == console.maximumHeight() == 180
    assert console._height_anim is None
    assert _running(console) == []

    console.set_expanded(False)
    assert console.height() == 36


def test_reduce_motion_start_glow_does_not_run(qtbot: Any) -> None:
    settings = Settings(reduce_motion=True)
    inspector = Inspector(settings, ThemeManager(settings))
    qtbot.addWidget(inspector)

    inspector.set_can_patch(True)

    assert inspector._glow_anim is None
    assert inspector._glow is None
    assert _running(inspector) == []


def test_segment_value_animates_and_finishes(qtbot: Any) -> None:
    settings = Settings(reduce_motion=False)
    segment = SegmentedControl(["A", "B", "C"], make_theme(settings))
    qtbot.addWidget(segment)
    segment.resize(300, 30)
    segment.show()

    segment.set_value("B")

    animation = segment._thumb_anim
    assert animation is not None
    assert animation.state() == QAbstractAnimation.State.Running

    qtbot.waitUntil(lambda: segment.thumbPosition == pytest.approx(1.0), timeout=1000)
    assert animation.state() == QAbstractAnimation.State.Stopped
    assert segment.thumbPosition == pytest.approx(1.0)


def test_console_height_animates_to_expanded(qtbot: Any) -> None:
    settings = Settings(reduce_motion=False)
    console = ConsolePanel(settings, ThemeManager(settings))
    qtbot.addWidget(console)
    console.resize(800, 36)
    console.show()
    qtbot.wait(20)
    console.set_animated(True)

    console.set_expanded(True)

    assert console._height_anim is not None
    qtbot.waitUntil(
        lambda: (
            console.minimumHeight() == 180
            and console.maximumHeight() == 180
            and console._height_anim is None
        ),
        timeout=2000,
    )
    assert console.minimumHeight() == console.maximumHeight() == 180
    assert console._height_anim is None
    assert _running(console) == []


def test_motion_controller_stop_all_stops_owned_animations(qtbot: Any) -> None:
    theme = make_theme(Settings())
    controller = MotionController(False, theme)
    button = QPushButton("x")
    qtbot.addWidget(button)
    animation = QPropertyAnimation(button, b"minimumHeight", controller)
    animation.setDuration(1000)
    animation.setStartValue(0)
    animation.setEndValue(100)
    animation.start()
    assert animation.state() == QAbstractAnimation.State.Running

    controller.stop_all()

    assert animation.state() == QAbstractAnimation.State.Stopped
    assert _running(controller) == []


def test_main_window_close_stops_bridge_watch_and_animations(
    qtbot: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from qt_support import make_main_window

    window = make_main_window(qtbot, monkeypatch, tmp_path)
    animation = QPropertyAnimation(window.console, b"minimumHeight", window.motion)
    animation.setDuration(1000)
    animation.setStartValue(36)
    animation.setEndValue(100)
    animation.start()
    assert animation.state() == QAbstractAnimation.State.Running

    window.close()

    assert window.bridge._running is False
    assert window.bridge._timer.isActive() is False
    assert window._watch_timer.isActive() is False
    assert animation.state() == QAbstractAnimation.State.Stopped
    assert _running(window) == []
