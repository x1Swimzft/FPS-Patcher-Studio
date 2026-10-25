"""Smart pre-flight: normalise audio and cap bitrate before the X1T patch.

Pure planning helpers (``needs_*``, ``build_*``) have no side effects so they can be
unit-tested without ffmpeg. ``run_preflight`` performs the actual ffmpeg pass.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import PatchError
from .ffmpeg_locator import CREATE_NO_WINDOW, FFmpegPaths
from .ffmpeg_runner import run_streaming
from .models import LogEvent, VideoInfo

_OWNER_TOOL = "fps-patcher-studio"
_OWNER_SUFFIX = ".preflight-owner.json"
_STALE_AGE_S = 24 * 3600.0
_OWNER_HOST = socket.gethostname()

TARGET_AUDIO_CODEC = "aac"
TARGET_SAMPLE_RATE = 48000
TARGET_CHANNELS = 2
TARGET_AUDIO_BITRATE = "192k"

BITRATE_TRIGGER_BPS = 25_000_000  # re-encode only above this
BITRATE_TARGET = "16M"
BITRATE_MAXRATE = "18M"
BITRATE_BUFSIZE = "36M"

# Preference order; every candidate is tried and failures fall through to libx264.
HW_ENCODERS: tuple[str, ...] = ("h264_nvenc", "h264_amf", "h264_qsv")
SOFTWARE_ENCODER = "libx264"

Emit = Callable[[LogEvent], None]


@dataclass(frozen=True)
class PreflightPlan:
    normalize_audio: bool
    cap_bitrate: bool

    @property
    def needed(self) -> bool:
        return self.normalize_audio or self.cap_bitrate


def needs_audio_normalize(info: VideoInfo) -> bool:
    """True when the audio track is not AAC-LC 48 kHz stereo.

    Unknown sample rate / channels (None) are not treated as a mismatch, so a
    direct-probe result with only a codec name never triggers a needless re-encode.
    """
    if not info.has_audio:
        return False
    codec = (info.audio_codec or "").lower()
    if codec not in ("aac", "mp4a"):
        return True
    if info.audio_sample_rate is not None and info.audio_sample_rate != TARGET_SAMPLE_RATE:
        return True
    return info.audio_channels is not None and info.audio_channels != TARGET_CHANNELS


def needs_bitrate_cap(info: VideoInfo) -> bool:
    return info.bit_rate is not None and info.bit_rate > BITRATE_TRIGGER_BPS


def make_plan(info: VideoInfo, *, normalize_audio: bool, cap_bitrate: bool) -> PreflightPlan:
    return PreflightPlan(
        normalize_audio=normalize_audio and needs_audio_normalize(info),
        cap_bitrate=cap_bitrate and needs_bitrate_cap(info),
    )


def _audio_args(normalize: bool) -> list[str]:
    if normalize:
        return [
            "-c:a", TARGET_AUDIO_CODEC,
            "-ar", str(TARGET_SAMPLE_RATE),
            "-ac", str(TARGET_CHANNELS),
            "-b:a", TARGET_AUDIO_BITRATE,
        ]  # fmt: skip
    return ["-c:a", "copy"]


def _video_args(encoder: str | None) -> list[str]:
    if encoder is None:
        return ["-c:v", "copy"]
    args = ["-c:v", encoder, "-pix_fmt", "yuv420p"]
    if encoder == SOFTWARE_ENCODER:
        args += ["-preset", "veryfast"]
    args += ["-b:v", BITRATE_TARGET, "-maxrate", BITRATE_MAXRATE, "-bufsize", BITRATE_BUFSIZE]
    return args


def build_preflight_args(
    src: Path, dst: Path, plan: PreflightPlan, encoder: str | None = None
) -> list[str]:
    """ffmpeg arguments for one pre-flight pass (audio-only or audio+video)."""
    video_encoder = (encoder or SOFTWARE_ENCODER) if plan.cap_bitrate else None
    return [
        "-hide_banner", "-nostdin", "-y",
        "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-map_metadata", "0",
        *_video_args(video_encoder),
        *_audio_args(plan.normalize_audio),
        "-progress", "pipe:1",
        str(dst),
    ]  # fmt: skip


def encoder_candidates(available: Sequence[str]) -> list[str]:
    """Hardware encoders found in ``available`` (preferred order) + software fallback."""
    found = [e for e in HW_ENCODERS if e in available]
    return [*found, SOFTWARE_ENCODER]


def list_h264_encoders(ffmpeg: Path) -> list[str]:
    """Names of H.264 encoders compiled into this ffmpeg build (empty on failure)."""
    try:
        proc = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-encoders"],
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    names: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] in (*HW_ENCODERS, SOFTWARE_ENCODER):
            names.append(parts[1])
    return names


def _owner_marker_path(dst: Path) -> Path:
    return dst.with_name(f".{dst.name}{_OWNER_SUFFIX}")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.GetExitCodeProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_owner_marker(marker: Path) -> dict[str, object] | None:
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("tool") != _OWNER_TOOL:
        return None
    if data.get("host") != _OWNER_HOST:
        return None  # a PID from another machine cannot be checked safely
    if not isinstance(data.get("pid"), int):
        return None
    temp = data.get("temp")
    if not isinstance(temp, str) or Path(temp).name != temp or ".preflight" not in temp.lower():
        return None
    return data


def _owner_is_stale(
    marker: Path, temp: Path, info: dict[str, object], now: float, max_age_s: float
) -> bool:
    try:
        age = now - marker.stat().st_mtime
    except OSError:
        return False
    try:
        # An orphan ffmpeg may outlive the app and still be writing.
        if now - temp.stat().st_mtime < 60:
            return False
    except OSError:
        pass  # temp already gone: the marker can still be swept
    if age > max_age_s:
        return True
    pid = info["pid"]
    if not isinstance(pid, int):
        return True
    # A dead PID is only trusted after a short grace period; PID reuse must not
    # delete a temp that another live instance is still writing.
    return age > 60 and not _pid_alive(pid)


def cleanup_stale_preflight(
    folders: Iterable[Path], *, max_age_s: float = _STALE_AGE_S, now: float | None = None
) -> int:
    """Delete stale preflight temps that carry our explicit ownership marker.

    Files without a valid marker are never touched, even if they end in
    ``.preflight``. Active markers (live PID, or younger than 60 s) are kept.
    """
    moment = time.time() if now is None else now
    removed = 0
    for folder in {Path(f) for f in folders}:
        try:
            markers = list(folder.glob(f".*{_OWNER_SUFFIX}"))
        except OSError:
            continue
        for marker in markers:
            info = _read_owner_marker(marker)
            if info is None:
                continue
            temp = folder / str(info["temp"])
            if not _owner_is_stale(marker, temp, info, moment, max_age_s):
                continue
            if temp.exists():
                try:
                    fd = os.open(temp, os.O_RDWR)
                    os.close(fd)
                except OSError:
                    continue  # held exclusively or not writable: leave it alone
            try:
                temp.unlink(missing_ok=True)
                marker.unlink(missing_ok=True)
                removed += 1
            except OSError:
                continue
    return removed


def remove_preflight_temp(path: Path) -> None:
    """Delete a preflight temp and its ownership marker after the job finishes."""
    marker = _owner_marker_path(path)
    try:
        path.unlink(missing_ok=True)
        info = _read_owner_marker(marker)
        if info is not None and info.get("temp") == path.name:
            marker.unlink(missing_ok=True)
    except OSError:
        pass


def _claim_preflight_owner(src: Path, dst: Path, *, max_age_s: float = _STALE_AGE_S) -> Path:
    """Create an exclusive marker, or refuse if another live process owns this temp."""
    marker = _owner_marker_path(dst)
    payload = json.dumps(
        {
            "tool": _OWNER_TOOL,
            "host": _OWNER_HOST,
            "pid": os.getpid(),
            "created": time.time(),
            "source": str(src),
            "temp": dst.name,
        }
    ).encode("utf-8")
    for attempt in (1, 2):
        try:
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            info = _read_owner_marker(marker)
            if info is not None and not _owner_is_stale(
                marker, dst, info, time.time(), max_age_s
            ):
                raise PatchError(f"Pre-flight already running for {src.name}.") from None
            try:
                marker.unlink(missing_ok=True)
            except OSError as exc:
                raise PatchError(f"Cannot claim pre-flight temp for {src.name}: {exc}") from exc
            if attempt == 2:
                raise PatchError(f"Cannot claim pre-flight temp for {src.name}.") from None
            continue
        except OSError as exc:
            raise PatchError(f"Cannot claim pre-flight temp for {src.name}: {exc}") from exc
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
        except OSError as exc:
            marker.unlink(missing_ok=True)
            raise PatchError(f"Cannot write pre-flight marker for {src.name}: {exc}") from exc
        return marker
    raise PatchError(f"Cannot claim pre-flight temp for {src.name}.")


def run_preflight(
    src: Path,
    plan: PreflightPlan,
    paths: FFmpegPaths,
    emit: Emit,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Run the pre-flight ffmpeg pass; return the temp file (caller deletes it)."""
    # Unique per invocation so two jobs on the same source never share a temp.
    dst = src.with_name(
        f"{src.stem}.preflight-{os.getpid()}-{secrets.token_hex(6)}{src.suffix}"
    )
    cleanup_stale_preflight([src.parent])
    marker = _claim_preflight_owner(src, dst)
    released = False
    try:
        candidates: list[str | None]
        if plan.cap_bitrate:
            candidates = list(encoder_candidates(list_h264_encoders(paths.ffmpeg)))
        else:
            candidates = [None]

        last_tail: list[str] = []
        for encoder in candidates:
            label = encoder or "audio only"
            emit(LogEvent(f"[PREFLIGHT] ffmpeg pass ({label})"))
            tail: list[str] = []

            def on_stderr(line: str, _tail: list[str] = tail) -> None:
                _tail.append(line)
                del _tail[:-15]

            try:
                code = run_streaming(
                    paths.ffmpeg,
                    build_preflight_args(src, dst, plan, encoder),
                    lambda _line: None,
                    on_stderr,
                    cancel_event,
                )
            except Exception:
                dst.unlink(missing_ok=True)  # cancel/error: never leave a partial preflight copy
                raise
            if code == 0 and dst.is_file() and dst.stat().st_size > 0:
                # Keep the marker until the caller deletes the temp; a hard kill
                # between here and there is then recoverable at startup.
                released = True
                return dst
            dst.unlink(missing_ok=True)
            last_tail = tail
            emit(LogEvent(f"[PREFLIGHT] {label} failed (exit {code}); trying next option", "WARN"))

        raise PatchError("Pre-flight conversion failed.", last_tail)
    finally:
        if not released:
            dst.unlink(missing_ok=True)
            marker.unlink(missing_ok=True)
