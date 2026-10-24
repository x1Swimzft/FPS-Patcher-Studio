"""Immutable data models shared across layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .ffmpeg_locator import FFmpegPaths

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".mov", ".m4v"})

FPS_PRESETS: dict[str, int] = {
    "60 FPS": 60000,
    "120 FPS": 120000,
}


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    codec: str
    width: int
    height: int
    avg_fps: Fraction
    r_fps: Fraction
    duration_s: float
    timescale: int
    nb_frames: int | None
    has_audio: bool
    stream_count: int
    audio_codec: str | None = None
    bit_rate: int | None = None

    @property
    def fps(self) -> float:
        """Best-effort display FPS (avg_frame_rate, falls back to r_frame_rate)."""
        value = self.avg_fps if self.avg_fps > 0 else self.r_fps
        return float(value)

    @property
    def is_vfr(self) -> bool:
        if self.avg_fps <= 0 or self.r_fps <= 0:
            return False
        return abs(float(self.avg_fps) - float(self.r_fps)) > 0.5


@dataclass(frozen=True)
class PatchRequest:
    src: Path
    out_dir: Path
    timescale: int
    strategy: str = "timescale"
    overwrite: bool = False
    auto_rename: bool = True
    v4_strict_lossless: bool = True
    v4_preserve_video: bool = True
    v4_preserve_audio: bool = True
    v4_sync_mvhd: bool = False
    v4_export_report: bool = False
    v4_dry_run: bool = False
    bxd_padding_bytes: int = 0
    bxd_max_tail_ms: int = 50


@dataclass(frozen=True)
class PatchResult:
    src: Path
    output: Path
    before: VideoInfo
    after: VideoInfo
    elapsed_s: float
    # True when output is non-standard (e.g. X1T ghost samples / trailing bytes).
    experimental: bool = False


LogLevel = Literal["INFO", "OK", "WARN", "ERROR", "DEBUG"]


@dataclass(frozen=True)
class LogEvent:
    message: str
    level: LogLevel = "INFO"


@dataclass(frozen=True)
class ProgressEvent:
    fraction: float  # 0.0 - 1.0 overall progress
    file_fraction: float = 0.0  # 0.0 - 1.0 progress of active file
    current_file: Path | None = None
    file_index: int = 1
    total_files: int = 1


@dataclass(frozen=True)
class ProbeDoneEvent:
    info: VideoInfo | None
    error: str | None = None
    queue_count: int = 1
    queue_paths: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class PatchDoneEvent:
    result: PatchResult | None
    error: str | None = None
    stderr_tail: list[str] = field(default_factory=list)
    batch_results: list[PatchResult] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    total_files: int = 1
    cancelled: bool = False


@dataclass(frozen=True)
class QueueChangedEvent:
    """Queue content/state changed; UI should re-render rows from controller.items."""

    reason: str = ""


@dataclass(frozen=True)
class FFmpegDownloadEvent:
    """Auto-download progress; ``stage`` is downloading/extracting/verifying/done/error."""

    stage: str
    downloaded: int = 0
    total: int = 0
    error: str | None = None
    paths: FFmpegPaths | None = None

    @property
    def percent(self) -> int:
        if self.total <= 0:
            return 0
        return max(0, min(100, int(self.downloaded * 100 / self.total)))


Event = (
    LogEvent
    | ProgressEvent
    | ProbeDoneEvent
    | PatchDoneEvent
    | QueueChangedEvent
    | FFmpegDownloadEvent
)
