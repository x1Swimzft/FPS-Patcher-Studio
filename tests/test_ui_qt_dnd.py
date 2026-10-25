"""Qt drag/drop parity: URL filtering, recursion, dedupe and drag state."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent  # noqa: E402

from fps_patcher.app.controller import AppController  # noqa: E402
from fps_patcher.app.queue_model import QueueItem  # noqa: E402
from fps_patcher.config import Settings  # noqa: E402
from fps_patcher.core.models import VideoInfo  # noqa: E402
from fps_patcher.ui_qt.queue_view import QueueView, _format_meta  # noqa: E402
from fps_patcher.ui_qt.theme import ThemeManager  # noqa: E402


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a real video")
    return path


def test_queue_meta_uses_single_encoded_separators(tmp_path: Path) -> None:
    item = QueueItem(path=tmp_path / "clip.mp4")
    item.info = VideoInfo(
        path=item.path,
        codec="h264",
        width=1920,
        height=1080,
        avg_fps=Fraction(60),
        r_fps=Fraction(60),
        duration_s=42,
        timescale=60000,
        nb_frames=2520,
        has_audio=True,
        stream_count=2,
    )
    meta = _format_meta(item)
    assert "1920×1080" in meta
    assert " · " in meta
    assert "Ã" not in meta and "Â" not in meta and "â" not in meta


def test_collect_urls_filters_recurses_and_dedupes(tmp_path: Path) -> None:
    mp4 = _touch(tmp_path / "a.mp4")
    mov = _touch(tmp_path / "b.MOV")
    m4v = _touch(tmp_path / "c.m4v")
    _touch(tmp_path / "skip.txt")
    _touch(tmp_path / "skip.avi")
    nested = _touch(tmp_path / "nested" / "deeper" / "d.mp4")

    urls = [
        QUrl.fromLocalFile(str(mp4)),
        QUrl.fromLocalFile(str(tmp_path)),
        QUrl.fromLocalFile(str(mp4)),
        QUrl.fromLocalFile(str(tmp_path / "skip.txt")),
    ]

    collected = QueueView.collect_urls(urls)

    assert collected == [mp4, mov, m4v, nested]
    assert collected.count(mp4) == 1
    assert all(path.suffix.lower() in {".mp4", ".mov", ".m4v"} for path in collected)


def test_collect_urls_ignores_non_local_and_missing_urls(tmp_path: Path) -> None:
    assert QueueView.collect_urls([QUrl("https://example.invalid/a.mp4")]) == []
    assert QueueView.collect_urls([QUrl.fromLocalFile(str(tmp_path / "missing.mp4"))]) == []


@pytest.fixture
def queue_view(qtbot: Any) -> QueueView:
    settings = Settings(reduce_motion=True)
    view = QueueView(AppController(settings), settings, ThemeManager(settings))
    qtbot.addWidget(view)
    view.resize(640, 420)
    view.show()
    qtbot.waitExposed(view)
    return view


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_drag_enter_and_leave_toggle_state_without_queueing(
    qtbot: Any, queue_view: QueueView, tmp_path: Path
) -> None:
    video = _touch(tmp_path / "drop.mp4")
    assert queue_view.drop_card.isVisible()
    assert queue_view.controller.items.items == []

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(video))])
    enter = QDragEnterEvent(
        QPoint(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    queue_view.dragEnterEvent(enter)

    assert enter.isAccepted()
    assert queue_view.drop_card.dragActive is True
    assert queue_view.controller.items.items == []

    queue_view.dragLeaveEvent(QDragLeaveEvent())

    assert queue_view.drop_card.dragActive is False
    assert queue_view.controller.items.items == []


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_drag_enter_rejects_unsupported_extensions(
    qtbot: Any, queue_view: QueueView, tmp_path: Path
) -> None:
    text = _touch(tmp_path / "notes.txt")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(text))])
    enter = QDragEnterEvent(
        QPoint(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    queue_view.dragEnterEvent(enter)

    assert not enter.isAccepted()
    assert queue_view.drop_card.dragActive is False
    assert queue_view.controller.items.items == []
