"""Locate working ffmpeg / ffprobe binaries.

Resolution order:
1. Explicit directory from settings.
2. ``bin/`` next to the frozen executable (PyInstaller) or project root.
3. Auto-download dir ``%LOCALAPPDATA%\\FPSPatcherStudio\\bin``.
4. System PATH.
Each candidate is validated by running ``-version``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import FFmpegNotFoundError

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass(frozen=True)
class FFmpegPaths:
    ffmpeg: Path
    ffprobe: Path
    version: str


def _exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def _bundled_bin_dirs() -> list[Path]:
    dirs: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass) / "bin")
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).parent / "bin")
    # project root: src/fps_patcher/core/ffmpeg_locator.py -> parents[3]
    dirs.append(Path(__file__).resolve().parents[3] / "bin")
    return dirs


def managed_bin_dir() -> Path:
    """Per-user install dir for auto-downloaded binaries (``%LOCALAPPDATA%``)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "FPSPatcherStudio" / "bin"


def get_version(binary: Path) -> str | None:
    """Return first line of ``-version`` output, or None if binary is unusable."""
    if not binary.is_file():
        return None
    try:
        proc = subprocess.run(
            [str(binary), "-hide_banner", "-version"],
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout.splitlines()[0].strip()


def _candidates(custom_dir: Path | None) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    dirs: list[Path] = []
    if custom_dir:
        dirs.append(custom_dir)
    dirs.extend(_bundled_bin_dirs())
    dirs.append(managed_bin_dir())
    for d in dirs:
        pairs.append((d / _exe("ffmpeg"), d / _exe("ffprobe")))
    # PATH: resolve ffprobe first, prefer ffmpeg from the same directory
    probe = shutil.which("ffprobe")
    if probe:
        d = Path(probe).parent
        pairs.append((d / _exe("ffmpeg"), Path(probe)))
    ff = shutil.which("ffmpeg")
    if ff and probe:
        pairs.append((Path(ff), Path(probe)))
    return pairs


def locate(custom_dir: Path | None = None) -> FFmpegPaths:
    """Find a validated ffmpeg + ffprobe pair or raise FFmpegNotFoundError."""
    seen: set[tuple[Path, Path]] = set()
    for ffmpeg, ffprobe in _candidates(custom_dir):
        key = (ffmpeg, ffprobe)
        if key in seen or not ffmpeg.is_file() or not ffprobe.is_file():
            continue
        seen.add(key)
        version = get_version(ffmpeg)
        if version and get_version(ffprobe):
            return FFmpegPaths(ffmpeg=ffmpeg, ffprobe=ffprobe, version=version)

    details: list[str] = []
    if custom_dir:
        details.append(f"custom directory '{custom_dir}'")
    details.append("bundled 'bin/' directory")
    details.append(f"auto-download directory '{managed_bin_dir()}'")
    details.append("system PATH")
    locations_checked = "; ".join(details)

    raise FFmpegNotFoundError(
        f"FFmpeg not found (checked: {locations_checked}). "
        "Please install FFmpeg (both ffmpeg and ffprobe), add it to PATH, "
        "place the executables in 'bin/', or select the folder in Settings."
    )
