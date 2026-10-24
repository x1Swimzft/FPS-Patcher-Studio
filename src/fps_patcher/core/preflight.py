"""Smart pre-flight: normalise audio and cap bitrate before the X1T patch.

Pure planning helpers (``needs_*``, ``build_*``) have no side effects so they can be
unit-tested without ffmpeg. ``run_preflight`` performs the actual ffmpeg pass.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import PatchError
from .ffmpeg_locator import CREATE_NO_WINDOW, FFmpegPaths
from .ffmpeg_runner import run_streaming
from .models import LogEvent, VideoInfo

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


def preflight_output_path(src: Path) -> Path:
    return src.with_name(f"{src.stem}.preflight{src.suffix}")


def run_preflight(
    src: Path,
    plan: PreflightPlan,
    paths: FFmpegPaths,
    emit: Emit,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Run the pre-flight ffmpeg pass; return the temp file (caller deletes it)."""
    dst = preflight_output_path(src)
    dst.unlink(missing_ok=True)

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

        code = run_streaming(
            paths.ffmpeg,
            build_preflight_args(src, dst, plan, encoder),
            lambda _line: None,
            on_stderr,
            cancel_event,
        )
        if code == 0 and dst.is_file() and dst.stat().st_size > 0:
            return dst
        dst.unlink(missing_ok=True)
        last_tail = tail
        emit(LogEvent(f"[PREFLIGHT] {label} failed (exit {code}); trying next option", "WARN"))

    raise PatchError("Pre-flight conversion failed.", last_tail)
