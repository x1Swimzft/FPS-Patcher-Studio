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

from .errors import PatchCancelledError, PatchError
from .ffmpeg_locator import CREATE_NO_WINDOW, FFmpegPaths
from .ffmpeg_runner import run_streaming
from .models import LogEvent, VideoInfo
from .platform_profiles import PlatformProfile

# FFmpeg preflight encodes compete for the same GPU; keep one pass at a time
# across all controller workers.
_PREFLIGHT_GPU_SEM = threading.Semaphore(1)

_OWNER_TOOL = "fps-patcher-studio"
_OWNER_SUFFIX = ".preflight-owner.json"
_STALE_AGE_S = 24 * 3600.0
_OWNER_HOST = socket.gethostname()

TARGET_AUDIO_CODEC = "aac"
TARGET_SAMPLE_RATE = 48000
TARGET_CHANNELS = 2
TARGET_AUDIO_BITRATE = "192k"

BITRATE_TRIGGER_BPS = 25_000_000  # advisory warning only
BITRATE_TARGET_MBPS = 16
BITRATE_TARGET_MBPS_MIN = 1
BITRATE_TARGET_MBPS_MAX = 24

# Preference order; every candidate is tried and failures fall through to libx264.
HW_ENCODERS: tuple[str, ...] = ("h264_nvenc", "h264_amf", "h264_qsv")
SOFTWARE_ENCODER = "libx264"
# Generic Windows GPU decode. Software decode of high-bitrate AV1 is slower than
# realtime, so the cap pass tries this first and retries without it on failure.
HW_DECODER = "d3d11va"

Emit = Callable[[LogEvent], None]


@dataclass(frozen=True)
class PreflightPlan:
    normalize_audio: bool
    cap_bitrate: bool
    fix_vfr: bool = False
    transcode_codec: bool = False
    scale_width: int | None = None
    scale_height: int | None = None

    @property
    def needs_video_encode(self) -> bool:
        return (
            self.cap_bitrate
            or self.fix_vfr
            or self.transcode_codec
            or self.scale_width is not None
            or self.scale_height is not None
        )

    @property
    def needed(self) -> bool:
        return self.normalize_audio or self.needs_video_encode


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


def target_bitrate_bps(target_mbps: int = BITRATE_TARGET_MBPS) -> int:
    """Clamped target bitrate in bits/s (1-24 Mbps)."""
    clamped = max(BITRATE_TARGET_MBPS_MIN, min(BITRATE_TARGET_MBPS_MAX, int(target_mbps)))
    return clamped * 1_000_000


def needs_bitrate_cap(
    info: VideoInfo, target_bps: int = BITRATE_TARGET_MBPS * 1_000_000
) -> bool:
    return info.bit_rate is not None and info.bit_rate > target_bps


def planned_output_bitrate(
    info: VideoInfo,
    *,
    cap_bitrate: bool,
    target_mbps: int = BITRATE_TARGET_MBPS,
) -> int | None:
    """Estimated output bitrate: the cap target when it applies, else the source."""
    if info.bit_rate is None:
        return None
    target = target_bitrate_bps(target_mbps)
    if cap_bitrate and needs_bitrate_cap(info, target):
        return target
    return info.bit_rate


def _resolution_target(
    info: VideoInfo, profile: PlatformProfile | None
) -> tuple[int | None, int | None]:
    """Target fit box that only shrinks a source exceeding the profile caps."""
    if profile is None or info.width <= 0 or info.height <= 0:
        return None, None
    width, height = info.width, info.height
    target_w, target_h = width, height
    capped = False
    if profile.max_dimension is not None and max(width, height) > profile.max_dimension:
        target_w = min(target_w, profile.max_dimension)
        target_h = min(target_h, profile.max_dimension)
        capped = True
    if profile.max_short_side is not None and min(width, height) > profile.max_short_side:
        if width >= height:
            target_h = min(target_h, profile.max_short_side)
        else:
            target_w = min(target_w, profile.max_short_side)
        capped = True
    return (target_w, target_h) if capped else (None, None)


def make_plan(
    info: VideoInfo,
    *,
    normalize_audio: bool,
    cap_bitrate: bool,
    target_mbps: int = BITRATE_TARGET_MBPS,
    fix_vfr: bool = False,
    fix_codec: bool = False,
    cap_resolution: bool = False,
    profile: PlatformProfile | None = None,
) -> PreflightPlan:
    scale_width, scale_height = (
        _resolution_target(info, profile) if cap_resolution else (None, None)
    )
    return PreflightPlan(
        normalize_audio=normalize_audio and needs_audio_normalize(info),
        cap_bitrate=cap_bitrate
        and needs_bitrate_cap(info, target_bitrate_bps(target_mbps)),
        fix_vfr=fix_vfr and info.is_vfr,
        transcode_codec=(
            fix_codec
            and profile is not None
            and (info.codec or "").lower() not in profile.video_codecs
        ),
        scale_width=scale_width,
        scale_height=scale_height,
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


def _video_args(encoder: str | None, target_mbps: int) -> list[str]:
    if encoder is None:
        return ["-c:v", "copy"]
    target = target_bitrate_bps(target_mbps) // 1_000_000
    args = ["-c:v", encoder, "-pix_fmt", "yuv420p"]
    if encoder == SOFTWARE_ENCODER:
        args += ["-preset", "veryfast"]
    args += [
        "-b:v", f"{target}M",
        "-maxrate", f"{target + 2}M",
        "-bufsize", f"{target * 2}M",
    ]  # fmt: skip
    return args


def _scale_filter(plan: PreflightPlan) -> str | None:
    """Fit inside the plan box without upscaling; aspect ratio is preserved."""
    if plan.scale_width is None and plan.scale_height is None:
        return None
    width = plan.scale_width if plan.scale_width is not None else "iw"
    height = plan.scale_height if plan.scale_height is not None else "ih"
    return (
        f"scale=w='min(iw,{width})':h='min(ih,{height})':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2"
    )


def build_preflight_args(
    src: Path,
    dst: Path,
    plan: PreflightPlan,
    encoder: str | None = None,
    extra_args: Sequence[str] = (),
    hwaccel: str | None = None,
    bitrate_target_mbps: int = BITRATE_TARGET_MBPS,
) -> list[str]:
    """ffmpeg arguments for one pre-flight pass (audio-only or audio+video)."""
    # Every video re-encode (bitrate cap, VFR, codec or resolution fix) targets
    # the configured bitrate: one pass is cheaper than a second quality pass.
    video_encoder = (encoder or SOFTWARE_ENCODER) if plan.needs_video_encode else None
    input_args = ["-hwaccel", hwaccel] if hwaccel and plan.needs_video_encode else []
    video_filter: list[str] = []
    if plan.fix_vfr:
        video_filter += ["-fps_mode", "cfr"]
    scale = _scale_filter(plan)
    if scale is not None:
        video_filter += ["-vf", scale]
    return [
        "-hide_banner", "-nostdin", "-y",
        *input_args,
        "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-map_metadata", "0",
        *_video_args(video_encoder, bitrate_target_mbps),
        *video_filter,
        *_audio_args(plan.normalize_audio),
        *extra_args,
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
    *,
    extra_args: Sequence[str] = (),
    force_event: threading.Event | None = None,
    on_stdout_line: Callable[[str], None] | None = None,
    bitrate_target_mbps: int = BITRATE_TARGET_MBPS,
) -> Path:
    """Run the pre-flight ffmpeg pass; return the temp file (caller deletes it)."""
    # Unique per invocation so two jobs on the same source never share a temp.
    dst = src.with_name(
        f"{src.stem}.preflight-{os.getpid()}-{secrets.token_hex(6)}{src.suffix}"
    )
    cleanup_stale_preflight([src.parent])
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise PatchCancelledError("Pre-flight cancelled.")
        if _PREFLIGHT_GPU_SEM.acquire(timeout=0.1):
            break
    marker: Path | None = None
    released = False
    try:
        marker = _claim_preflight_owner(src, dst)
        attempts: list[tuple[str | None, str | None]]
        if plan.needs_video_encode:
            encoders = list(encoder_candidates(list_h264_encoders(paths.ffmpeg)))
            attempts = [(HW_DECODER, e) for e in encoders] + [(None, e) for e in encoders]
        else:
            attempts = [(None, None)]

        last_tail: list[str] = []
        read_stdout = on_stdout_line or (lambda _line: None)
        for hwaccel, encoder in attempts:
            label = encoder or "audio only"
            if hwaccel:
                label += f" ({hwaccel} decode)"
            emit(LogEvent(f"[PREFLIGHT] ffmpeg pass ({label})"))
            tail: list[str] = []

            def on_stderr(line: str, _tail: list[str] = tail) -> None:
                _tail.append(line)
                del _tail[:-15]

            try:
                code = run_streaming(
                    paths.ffmpeg,
                    build_preflight_args(
                        src,
                        dst,
                        plan,
                        encoder,
                        extra_args,
                        hwaccel,
                        bitrate_target_mbps,
                    ),
                    read_stdout,
                    on_stderr,
                    cancel_event,
                    force_event,
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
        # Release before returning the temp so waiting workers can start their
        # own pass while the caller patches the previous result.
        _PREFLIGHT_GPU_SEM.release()
        if not released:
            dst.unlink(missing_ok=True)
            if marker is not None:
                marker.unlink(missing_ok=True)
