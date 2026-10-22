"""Shared test fixtures: synthetic clips generated with ffmpeg lavfi."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    with contextlib.suppress(Exception):
        import ctypes

        ctypes.cdll.ucrtbase._setmaxstdio(2048)

import pytest

from fps_patcher.core.ffmpeg_locator import FFmpegPaths, locate

# uv-managed CPython may not locate its bundled Tcl/Tk scripts (init.tcl); point at them.
_TCL_VARS = (("TCL_LIBRARY", "tcl8.6", "init.tcl"), ("TK_LIBRARY", "tk8.6", "tk.tcl"))
for _var, _name, _probe in _TCL_VARS:
    _dir = Path(sys.base_prefix) / "tcl" / _name
    if _var not in os.environ and (_dir / _probe).is_file():
        os.environ[_var] = str(_dir)


@pytest.fixture(scope="session")
def ff() -> FFmpegPaths:
    try:
        return locate()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"ffmpeg unavailable: {exc}")


def _ensure_encoders(ff: FFmpegPaths) -> None:
    try:
        proc = subprocess.run(
            [str(ff.ffmpeg), "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except Exception as exc:
        pytest.skip(f"Could not query ffmpeg encoders: {exc}")
    if "libx264" not in proc.stdout or "aac" not in proc.stdout:
        pytest.skip("Required encoder libx264 or aac missing from ffmpeg -encoders")


def _make_clip(ff: FFmpegPaths, out: Path, fps: str, audio: bool = True) -> Path:
    _ensure_encoders(ff)
    cmd = [
        str(ff.ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=320x240:rate={fps}:duration=2",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=2"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd.append(str(out))
    subprocess.run(cmd, check=True)
    return out


@pytest.fixture(scope="session")
def clip_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("clips")


@pytest.fixture(scope="session")
def clip30(ff: FFmpegPaths, clip_dir: Path) -> Path:
    return _make_clip(ff, clip_dir / "clip 30fps ไทย.mp4", "30")


@pytest.fixture(scope="session")
def clip5994(ff: FFmpegPaths, clip_dir: Path) -> Path:
    return _make_clip(ff, clip_dir / "clip5994.mov", "60000/1001")


@pytest.fixture(scope="session")
def clip_noaudio(ff: FFmpegPaths, clip_dir: Path) -> Path:
    return _make_clip(ff, clip_dir / "noaudio.mp4", "24", audio=False)
