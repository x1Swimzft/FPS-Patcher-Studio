"""Pluggable patch strategies. Each builds an ffmpeg argument list or flags direct atom patch.

All strategies use stream copy (``-c copy``) or direct binary atom patching:
no re-encode, header/container rewrite only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

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
    """Experimental X1T container method (audio inflation & indeterminate mvhd duration)."""

    name = "bxd-experimental"
    label = "Experimental X1T Container Method"
    direct = True

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        raise RuntimeError("X1T Experimental strategy does not use FFmpeg arguments.")


class BXDPCtrategy:
    """X1T For PC: Original non-standard X1T container inflation (PC-oriented)."""

    name = "bxd-pc"
    label = "X1T For PC"
    direct = True

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        raise RuntimeError("X1T For PC preset does not use FFmpeg arguments.")


class BXDMobileStrategy:
    """X1T For Mobile: ISO-BMFF compliant faststart + free-box padding + valid timing."""

    name = "bxd-mobile"
    label = "X1T For Mobile"
    direct = True

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        raise RuntimeError("X1T For Mobile preset does not use FFmpeg arguments.")


class BXDHybridStrategy:
    """X1T Hybrid: ISO-BMFF free-box padding + bounded last-sample duration shaping."""

    name = "bxd-hybrid"
    label = "X1T Hybrid"
    direct = True

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        raise RuntimeError("X1T Hybrid preset does not use FFmpeg arguments.")


class BXDCleanStrategy:
    """X1T Clean: Pure ISO-BMFF faststart & atom timescale retiming without padding."""

    name = "bxd-clean"
    label = "X1T Clean"
    direct = True

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        raise RuntimeError("X1T Clean preset does not use FFmpeg arguments.")


# X1T Class Aliases
X1TStrategy = BXDStrategy
X1TPCStrategy = BXDPCtrategy
X1TMobileStrategy = BXDMobileStrategy
X1THybridStrategy = BXDHybridStrategy
X1TCleanStrategy = BXDCleanStrategy


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


class _PresetDict(dict[str, PatchStrategy]):
    """Preset mapping dictionary with transparent x1t-* alias support."""

    _ALIASES = {
        "x1t-pc": "bxd-pc",
        "x1t-mobile": "bxd-mobile",
        "x1t-hybrid": "bxd-hybrid",
        "x1t-clean": "bxd-clean",
    }

    def __getitem__(self, key: str) -> PatchStrategy:
        return super().__getitem__(self._ALIASES.get(key, key))

    def get(self, key: str, default: Any = None) -> Any:
        return super().get(self._ALIASES.get(key, key), default)

    def __contains__(self, key: object) -> bool:
        return super().__contains__(key) or (isinstance(key, str) and key in self._ALIASES)


UI_PRESETS: dict[str, PatchStrategy] = _PresetDict({
    "bxd-pc": BXDPCtrategy(),
    "bxd-mobile": BXDMobileStrategy(),
    "bxd-hybrid": BXDHybridStrategy(),
    "bxd-clean": BXDCleanStrategy(),
})

STRATEGIES: dict[str, PatchStrategy] = {
    "bxd-pc": UI_PRESETS["bxd-pc"],
    "bxd-mobile": UI_PRESETS["bxd-mobile"],
    "bxd-hybrid": UI_PRESETS["bxd-hybrid"],
    "bxd-clean": UI_PRESETS["bxd-clean"],
    "x1t-pc": UI_PRESETS["bxd-pc"],
    "x1t-mobile": UI_PRESETS["bxd-mobile"],
    "x1t-hybrid": UI_PRESETS["bxd-hybrid"],
    "x1t-clean": UI_PRESETS["bxd-clean"],
    "direct-atom": DirectAtomStrategy(),
    "v4-forensic": MethodV4Strategy(),
    "bxd-experimental": BXDStrategy(),
    "x1t-experimental": BXDStrategy(),
    "ffmpeg-copy": FFmpegStrategy(),
}

# Compatibility aliases for legacy or shorthand keys
_STRATEGY_ALIASES: dict[str, str] = {
    "timescale": "ffmpeg-copy",
    "timescale+movie": "ffmpeg-copy",
    "bxd-bypass": "bxd-experimental",
    "x1t-bypass": "bxd-experimental",
    "x1t-pc": "bxd-pc",
    "x1t-mobile": "bxd-mobile",
    "x1t-hybrid": "bxd-hybrid",
    "x1t-clean": "bxd-clean",
    "x1t-experimental": "bxd-experimental",
}

_UI_MIGRATION_MAP: dict[str, str] = {
    "bxd-bypass": "bxd-pc",
    "bxd-experimental": "bxd-pc",
    "x1t-bypass": "bxd-pc",
    "x1t-experimental": "bxd-pc",
    "x1t-pc": "bxd-pc",
    "x1t-mobile": "bxd-mobile",
    "x1t-hybrid": "bxd-hybrid",
    "x1t-clean": "bxd-clean",
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
    if name in ("bxd-pc", "bxd-mobile", "bxd-hybrid", "bxd-clean"):
        return name, None
    if name in ("x1t-pc", "x1t-mobile", "x1t-hybrid", "x1t-clean"):
        return name.replace("x1t-", "bxd-"), None
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

