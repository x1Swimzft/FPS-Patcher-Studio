"""Async queue thumbnails: ffmpeg/PIL work stays off the GUI thread.

Workers only produce PNG bytes and emit them through a queued signal; the
queue view turns those bytes into a ``QPixmap`` on the main thread.
"""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from ..ui.thumbnails import request_thumbnail

THUMBNAIL_SIZE = (56, 32)


class ThumbnailLoader(QObject):
    """One request per item id; emits ``b""`` when no frame is available."""

    ready = Signal(str, bytes)

    def __init__(
        self,
        ffmpeg_provider: Callable[[], Path | None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._ffmpeg_provider = ffmpeg_provider
        self._pending: set[str] = set()

    def request(self, item_id: str, path: Path) -> bool:
        if item_id in self._pending:
            return False
        ffmpeg = self._ffmpeg_provider()
        if ffmpeg is None:
            return False
        self._pending.add(item_id)
        request_thumbnail(
            path,
            ffmpeg,
            THUMBNAIL_SIZE,
            lambda image: self._finish(item_id, image),
        )
        return True

    def release(self, item_id: str) -> None:
        self._pending.discard(item_id)

    def _finish(self, item_id: str, image: Any) -> None:
        data = b""
        if image is not None:
            try:
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                data = buffer.getvalue()
            except Exception:
                data = b""
        self.ready.emit(item_id, data)
