"""Pluggable patch strategies. Each builds an ffmpeg argument list or flags direct atom patch.

All strategies use stream copy (``-c copy``) or direct binary atom patching:
no re-encode, header/container rewrite only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import PatchRequest, VideoInfo


def muxer_for(path: Path) -> str:
    return "mov" if path.suffix.lower() == ".mov" else "mp4"


def _base_args(req: PatchRequest) -> list[str]:
    return [
        "-hide_banner",
        "-nostats",
        "-y",
        "-i",
        str(req.src),
        "-map",
        "0",
        "-c",
        "copy",
        "-map_metadata",
        "0",
    ]


def _tail_args(req: PatchRequest, out: Path) -> list[str]:
    return [
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-f",
        muxer_for(req.src),
        str(out),
    ]


@runtime_checkable
class PatchStrategy(Protocol):
    name: str
    label: str
    direct: bool

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]: ...


class DirectAtomStrategy:
    """Method V3: Direct MP4 atom timing patch (lossless in-place header edit)."""

    name = "direct-atom"
    label = "Method V3: Direct MP4 Atom Patch"
    direct = True

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        raise RuntimeError("Direct Atom strategy does not use FFmpeg arguments.")


class MethodV4Strategy:
    """Method V4: Forensic atom patch with timing sync & forensic validation."""

    name = "v4-forensic"
    label = "Method V4: Forensic Lossless Patch"
    direct = True

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        raise RuntimeError("Method V4 Forensic strategy does not use FFmpeg arguments.")


class BXDStrategy:
    """Experimental BXD container method (audio inflation & indeterminate mvhd duration)."""

    name = "bxd-experimental"
    label = "Experimental BXD Container Method"
    direct = True

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        raise RuntimeError("BXD Experimental strategy does not use FFmpeg arguments.")


class BXDPCtrategy:
    """Bxd For PC: Original non-standard BXD container inflation (PC-oriented)."""

    name = "bxd-pc"
    label = "Bxd For PC"
    direct = True

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        raise RuntimeError("Bxd For PC preset does not use FFmpeg arguments.")


class BXDMobileStrategy:
    """Bxd For Mobile: ISO-BMFF compliant faststart + free-box padding + valid timing."""

    name = "bxd-mobile"
    label = "Bxd For Mobile"
    direct = True

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        raise RuntimeError("Bxd For Mobile preset does not use FFmpeg arguments.")


class BXDHybridStrategy:
    """Bxd Hybrid: ISO-BMFF free-box padding + bounded last-sample duration shaping."""

    name = "bxd-hybrid"
    label = "Bxd Hybrid"
    direct = True

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        raise RuntimeError("Bxd Hybrid preset does not use FFmpeg arguments.")


class BXDCleanStrategy:
    """Bxd Clean: Pure ISO-BMFF faststart & atom timescale retiming without padding."""

    name = "bxd-clean"
    label = "Bxd Clean"
    direct = True

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        raise RuntimeError("Bxd Clean preset does not use FFmpeg arguments.")


class FFmpegStrategy:
    """FFmpeg stream copy remuxing (-c copy -video_track_timescale)."""

    name = "ffmpeg-copy"
    label = "FFmpeg Stream Copy (Remux)"
    direct = False

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        return [
            *_base_args(req),
            "-video_track_timescale",
            str(req.timescale),
            *_tail_args(req, out),
        ]


UI_PRESETS: dict[str, PatchStrategy] = {
    "bxd-pc": BXDPCtrategy(),
    "bxd-mobile": BXDMobileStrategy(),
    "bxd-hybrid": BXDHybridStrategy(),
    "bxd-clean": BXDCleanStrategy(),
}

STRATEGIES: dict[str, PatchStrategy] = {
    "bxd-pc": UI_PRESETS["bxd-pc"],
    "bxd-mobile": UI_PRESETS["bxd-mobile"],
    "bxd-hybrid": UI_PRESETS["bxd-hybrid"],
    "bxd-clean": UI_PRESETS["bxd-clean"],
    "direct-atom": DirectAtomStrategy(),
    "v4-forensic": MethodV4Strategy(),
    "bxd-experimental": BXDStrategy(),
    "ffmpeg-copy": FFmpegStrategy(),
}

# Compatibility aliases for legacy or shorthand keys
_STRATEGY_ALIASES: dict[str, str] = {
    "timescale": "ffmpeg-copy",
    "timescale+movie": "ffmpeg-copy",
    "bxd-bypass": "bxd-experimental",
}

_UI_MIGRATION_MAP: dict[str, str] = {
    "bxd-bypass": "bxd-pc",
    "bxd-experimental": "bxd-pc",
    "direct-atom": "bxd-clean",
    "v4-forensic": "bxd-clean",
    "ffmpeg-copy": "bxd-clean",
    "timescale": "bxd-clean",
    "timescale+movie": "bxd-clean",
}


def migrate_strategy_name(name: str) -> tuple[str, str | None]:
    """Migrate legacy strategy key to a valid UI_PRESETS key.

    Returns (resolved_preset_key, original_legacy_key_if_migrated).
    """
    if name in UI_PRESETS:
        return name, None
    if name in _UI_MIGRATION_MAP:
        return _UI_MIGRATION_MAP[name], name
    return "bxd-mobile", name


def strategy_requires_ffmpeg(strategy: PatchStrategy | str) -> bool:
    """Check if strategy requires ffmpeg.exe for remuxing (direct strategies do not)."""
    strat = get_strategy(strategy) if isinstance(strategy, str) else strategy
    return not strat.direct


def get_strategy(name: str) -> PatchStrategy:
    resolved_name = _STRATEGY_ALIASES.get(name, name)
    try:
        return STRATEGIES[resolved_name]
    except KeyError as exc:
        raise ValueError(f"Unknown strategy: {name}") from exc

