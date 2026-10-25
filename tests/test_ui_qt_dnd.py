"""Qt drag/drop parity: URL filtering, recursion, dedupe and drag state."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import (  # noqa: E402
    QBuffer,
    QIODevice,
    QMimeData,
    QPoint,
    QRectF,
    QSize,
    Qt,
    QUrl,
)
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QImage  # noqa: E402

from fps_patcher.app.controller import AppController  # noqa: E402
from fps_patcher.app.queue_model import QueueItem  # noqa: E402
from fps_patcher.config import Settings  # noqa: E402
from fps_patcher.core.models import VideoInfo  # noqa: E402
from fps_patcher.ui.strings import t  # noqa: E402
from fps_patcher.ui_qt.queue_view import QueueView, _format_meta  # noqa: E402
from fps_patcher.ui_qt.theme import ThemeManager  # noqa: E402
from fps_patcher.ui_qt.thumbnails import THUMBNAIL_SIZE, ThumbnailLoader  # noqa: E402


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


def _png_bytes() -> bytes:
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    # Qt accepts the format as str; the stubs only declare bytes/None.
    assert image.save(buffer, "PNG")  # type: ignore[call-overload]
    data = buffer.data().data()
    assert isinstance(data, bytes)
    return data


def test_thumbnail_loader_skips_work_without_ffmpeg(
    qtbot: Any, tmp_path: Path
) -> None:
    def no_ffmpeg() -> Path | None:
        return None

    loader = ThumbnailLoader(no_ffmpeg)
    with qtbot.assertNotEmitted(loader.ready):
        assert loader.request("item", _touch(tmp_path / "clip.mp4")) is False
    assert THUMBNAIL_SIZE == (56, 32)


def test_thumbnail_cache_accepts_png_and_rejects_garbage(
    qtbot: Any, queue_view: QueueView, tmp_path: Path
) -> None:
    video = _touch(tmp_path / "thumb.mp4")
    queue_view.controller.items.add([video])
    queue_view.refresh()
    item = queue_view.controller.items.items[0]

    assert queue_view.thumbnail(item.item_id) is None
    queue_view._on_thumb_ready(item.item_id, b"not an image")
    assert queue_view.thumbnail(item.item_id) is None

    queue_view._on_thumb_ready(item.item_id, _png_bytes())
    pixmap = queue_view.thumbnail(item.item_id)
    assert pixmap is not None
    assert pixmap.size() == QSize(8, 8)


def test_row_pills_cover_resolution_fps_mode_and_size(
    queue_view: QueueView, tmp_path: Path
) -> None:
    item = QueueItem(path=tmp_path / "pills.mp4")
    item.info = VideoInfo(
        path=item.path,
        codec="h264",
        width=1920,
        height=1080,
        avg_fps=Fraction(30),
        r_fps=Fraction(30),
        duration_s=10,
        timescale=30000,
        nb_frames=300,
        has_audio=True,
        stream_count=2,
        file_size_bytes=12 * 1024 * 1024,
    )
    item.timescale = 90000
    pills = dict(queue_view.delegate.row_pills(item))

    assert pills["resolution"] == "1920×1080"
    assert pills["fps"] == "30 → 90 fps"
    assert pills["mode"] == "h264 · Mobile"
    assert pills["size"] == "12.0 MB"


def test_row_actions_are_large_and_emit_forensic(
    qtbot: Any, queue_view: QueueView, tmp_path: Path
) -> None:
    video = _touch(tmp_path / "forensic.mp4")
    queue_view.controller.items.add([video])
    queue_view.refresh()
    index = queue_view.model.index(0, 0)
    rect = QRectF(queue_view.list_view.visualRect(index))
    actions = queue_view.delegate.action_rects(rect)

    assert set(actions) == {"override", "forensic", "remove"}
    for area in actions.values():
        assert area.width() >= 26
        assert area.height() >= 26

    received: list[Path] = []
    queue_view.forensic_requested.connect(received.append)
    assert queue_view._handle_click(actions["forensic"].center().toPoint()) is True
    assert received == [video]


def test_profile_strip_follows_preset_strategy_and_output(
    queue_view: QueueView, tmp_path: Path
) -> None:
    queue_view.refresh_profile()
    summary = queue_view.drop_card.profile_summary.fullText()
    assert "60 FPS" in summary
    assert "X1T For Mobile" in summary
    assert t("drop_profile_output_same", "en") in summary

    queue_view.settings.last_preset = "120 FPS"
    queue_view.settings.strategy = "bxd-clean"
    queue_view.settings.output_dir = str(tmp_path)
    queue_view.refresh_profile()
    summary = queue_view.drop_card.profile_summary.fullText()
    assert "120 FPS" in summary
    assert "X1T Clean" in summary
    assert t("drop_profile_output_custom", "en") in summary
    assert queue_view.drop_card.profile_title.text() == t("active_patch_profile", "en")


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
