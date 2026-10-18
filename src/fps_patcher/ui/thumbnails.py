"""Background thumbnail generator and disk/memory cache for MP4/MOV files."""

from __future__ import annotations

import atexit
import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

_CACHE_DIR = Path(tempfile.mkdtemp(prefix="fps_patcher_thumbs_"))


def _cleanup() -> None:
    shutil.rmtree(_CACHE_DIR, ignore_errors=True)


atexit.register(_cleanup)

_MEM_CACHE: dict[str, Any] = {}
_LOCK = threading.Lock()


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

        with _LOCK:
            _MEM_CACHE[key] = img

        callback(img)

    threading.Thread(target=worker, daemon=True).start()
