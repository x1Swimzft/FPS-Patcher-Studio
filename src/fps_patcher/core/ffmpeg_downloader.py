"""Download and install official FFmpeg Windows x64 static binaries.

Fetches the BtbN GPL build zip over HTTPS (verified TLS), streams it to a temp
file with progress/cancel support, extracts only ``*/bin/ffmpeg.exe`` and
``*/bin/ffprobe.exe`` to fixed names (archive paths are never used as output
paths, so Zip Slip is impossible), verifies them, then atomically moves them
into :func:`managed_bin_dir`.
"""

from __future__ import annotations

import os
import shutil
import ssl
import threading
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from .errors import FFmpegDownloadError
from .ffmpeg_locator import FFmpegPaths, get_version, managed_bin_dir

DOWNLOAD_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)
CHUNK_SIZE = 64 * 1024
TIMEOUT_S = 30
MAX_MEMBER_BYTES = 512 * 1024 * 1024  # zip-bomb guard per extracted binary
BINARIES = ("ffmpeg.exe", "ffprobe.exe")

ProgressCallback = Callable[[int, int, str], None]


def _noop(_done: int, _total: int, _stage: str) -> None:
    pass


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise FFmpegDownloadError("FFmpeg download cancelled.")


def _download(
    url: str,
    dest: Path,
    progress: ProgressCallback,
    cancel: threading.Event | None,
) -> None:
    if not url.lower().startswith("https://"):
        raise FFmpegDownloadError(f"Refusing non-HTTPS download URL: {url}")
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "FPSPatcherStudio"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=ctx) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            progress(0, total, "downloading")
            with dest.open("wb") as fh:
                while True:
                    _check_cancel(cancel)
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    progress(done, total, "downloading")
    except OSError as exc:  # URLError, HTTPError, timeouts, disk errors
        raise FFmpegDownloadError(f"Download failed: {exc}") from exc
    if total and done != total:
        raise FFmpegDownloadError(f"Download incomplete ({done}/{total} bytes).")


def extract_binaries(
    zip_path: Path,
    out_dir: Path,
    cancel: threading.Event | None = None,
) -> dict[str, Path]:
    """Extract ``*/bin/ffmpeg.exe`` + ``*/bin/ffprobe.exe`` into ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    found: dict[str, Path] = {}
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                parts = PurePosixPath(info.filename.replace("\\", "/")).parts
                if len(parts) < 2 or parts[-2].lower() != "bin" or info.is_dir():
                    continue
                name = parts[-1].lower()
                if name not in BINARIES or name in found:
                    continue
                if info.file_size > MAX_MEMBER_BYTES:
                    raise FFmpegDownloadError(f"{name} in archive is implausibly large.")
                target = out_dir / name
                with zf.open(info) as src, target.open("wb") as dst:
                    written = 0
                    while chunk := src.read(CHUNK_SIZE):
                        _check_cancel(cancel)
                        written += len(chunk)
                        if written > MAX_MEMBER_BYTES:
                            raise FFmpegDownloadError(f"{name} exceeds size limit.")
                        dst.write(chunk)
                found[name] = target
    except (zipfile.BadZipFile, OSError) as exc:
        raise FFmpegDownloadError(f"Invalid FFmpeg archive: {exc}") from exc
    missing = [b for b in BINARIES if b not in found]
    if missing:
        raise FFmpegDownloadError(f"Archive missing: {', '.join(missing)}")
    return found


def download_ffmpeg(
    dest_dir: Path | None = None,
    progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
    url: str = DOWNLOAD_URL,
) -> FFmpegPaths:
    """Download, extract, verify and install ffmpeg + ffprobe. Blocking."""
    dest_dir = dest_dir or managed_bin_dir()
    report = progress or _noop
    staging = dest_dir / ".staging"
    zip_path = dest_dir / ".ffmpeg-download.zip"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
        _download(url, zip_path, report, cancel)

        report(0, 0, "extracting")
        staged = extract_binaries(zip_path, staging, cancel)

        report(0, 0, "verifying")
        version = get_version(staged["ffmpeg.exe"])
        if not version or not get_version(staged["ffprobe.exe"]):
            raise FFmpegDownloadError("Downloaded FFmpeg binaries failed to run.")
        _check_cancel(cancel)

        final: dict[str, Path] = {}
        for name, src in staged.items():
            final[name] = dest_dir / name
            try:
                os.replace(src, final[name])
            except OSError as exc:
                raise FFmpegDownloadError(f"Cannot install {name}: {exc}") from exc
        return FFmpegPaths(
            ffmpeg=final["ffmpeg.exe"], ffprobe=final["ffprobe.exe"], version=version
        )
    finally:
        zip_path.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
