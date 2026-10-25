"""Queue thumbnails: PIL/ffmpeg work stays off the GUI thread.

Workers produce an image, encode it as PNG bytes and emit them through a queued
signal; the queue view turns those bytes into a ``QPixmap`` on the main thread.
"""

from __future__ import annotations

import atexit
import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image
from PySide6.QtCore import QObject, Signal

THUMBNAIL_SIZE = (56, 32)

_CACHE_DIR = Path(tempfile.mkdtemp(prefix="fps_patcher_thumbs_"))


def _cleanup() -> None:
    shutil.rmtree(_CACHE_DIR, ignore_errors=True)


atexit.register(_cleanup)

_MEM_CACHE: dict[str, Any] = {}
_MAX_MEM_CACHE = 128  # ~7 MB of 160x90 thumbs; older entries are evicted oldest-first
_LOCK = threading.Lock()


def _remember(key: str, img: Any) -> None:
    with _LOCK:
        _MEM_CACHE[key] = img
        while len(_MEM_CACHE) > _MAX_MEM_CACHE:
            _MEM_CACHE.pop(next(iter(_MEM_CACHE)))


def get_cache_key(path: Path) -> str:
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = 0
    raw = f"{path.resolve()}_{mtime}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def request_thumbnail(
    path: Path,
    ffmpeg_exe: Path | None,
    size: tuple[int, int],
    callback: Callable[[Any | None], None],
) -> None:
    """Request thumbnail asynchronously. Invokes callback on main or worker thread."""
    key = get_cache_key(path)
    with _LOCK:
        if key in _MEM_CACHE:
            callback(_MEM_CACHE[key])
            return

    def worker() -> None:
        img = None
        target_png = _CACHE_DIR / f"{key}.png"
        if target_png.exists():
            try:
                img = Image.open(target_png)
                img.load()
            except Exception:
                img = None

        if img is None and ffmpeg_exe is not None and ffmpeg_exe.is_file():
            try:
                cmd = [
                    str(ffmpeg_exe),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    "0.5",
                    "-i",
                    str(path),
                    "-vframes",
                    "1",
                    "-vf",
                    f"scale={size[0]}:{size[1]}:force_original_aspect_ratio=decrease",
                    str(target_png),
                ]
                subprocess.run(
                    cmd,
                    check=True,
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if target_png.exists():
                    img = Image.open(target_png)
                    img.load()
            except Exception:
                img = None

        _remember(key, img)

        callback(img)

    threading.Thread(target=worker, daemon=True).start()


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
            lambda image: self.finish(item_id, image),
        )
        return True

    def release(self, item_id: str) -> None:
        self._pending.discard(item_id)

    def finish(self, item_id: str, image: Any) -> None:
        data = b""
        if image is not None:
            try:
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                data = buffer.getvalue()
            except Exception:
                data = b""
        self.ready.emit(item_id, data)
