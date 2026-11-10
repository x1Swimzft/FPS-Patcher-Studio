"""Pluggable patch strategies. Each builds an ffmpeg argument list or flags direct atom patch.

Most strategies use stream copy (``-c copy``) or direct binary atom patching:
no re-encode, header/container rewrite only. The two ``tiktok-ts`` presets are
a deliberate exception and lossily re-encode video and audio into MPEG-TS.
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


class TikTokTSStrategy:
    """TikTok TS: re-encode via Media Foundation H.264 into MPEG-TS saved as .mp4.

    Mirrors the reference upload fingerprint (Main/CAVLC, 1 s GOP, u_vbr 20.48 Mbps).
    """

    direct = False

    def __init__(self, name: str, label: str, force_1080: bool = False) -> None:
        self.name = name
        self.label = label
        self.force_1080 = force_1080

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        vf = "fps=60"
        if self.force_1080:
            vf = (
                "scale=1920:1080:force_original_aspect_ratio=decrease"
                ":force_divisible_by=2,"
                "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1," + vf
            )
        # h264_mf in the bundled ffmpeg has no named profile table; 77 is H.264 Main.
        return [
            "-hide_banner",
            "-nostats",
            "-y",
            "-i",
            str(req.src),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-map_metadata",
            "-1",
            "-vf",
            vf,
            "-pix_fmt",
            "nv12",
            "-c:v",
            "h264_mf",
            "-profile:v",
            "77",
            "-rate_control",
            "u_vbr",
            "-b:v",
            "20480k",
            "-g",
            "60",
            "-bf",
            "2",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-progress",
            "pipe:1",
            "-f",
            "mpegts",
            str(out),
        ]


class TikTokTSRemuxStrategy:
    """TikTok TS remux: copy an H.264 video bitstream and re-encode audio only.

    The reference upload was a remux of an already-H.264 1080p60 source: its
    video SEI and bitrate survive unchanged. Re-encoding cannot reproduce that,
    so this preset copies the video and normalises only the audio and container.
    """

    name = "tiktok-ts-remux"
    label = "X1T Remux"
    direct = False

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        return [
            "-hide_banner",
            "-nostats",
            "-y",
            "-i",
            str(req.src),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-map_metadata",
            "-1",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-progress",
            "pipe:1",
            "-f",
            "mpegts",
            str(out),
        ]


class ZilemStrategy:
    """X1T Zilem: container-only MP4 rewrite with no re-encode.

    Keeps the original H.264 samples and AAC-LC 48 kHz stereo audio, extends the
    audio with silent frames, duplicates the audio track and writes a strict
    ISO-BMFF ``moov`` at the end of the file. The FFmpeg argument builder is
    never used: :func:`fps_patcher.core.zilem_patcher.build_zilem` does the work.
    """

    name = "zilem"
    label = "X1T Zilem"
    direct = True

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        raise RuntimeError("X1T Zilem does not use FFmpeg arguments.")


class ZilemV3Strategy:
    """X1T Zilem V3: the reference-exact Zilem container.

    Same byte-preserving transform as :class:`ZilemStrategy`, plus the original
    reference tag and the ``ZETA_OPTIMIZED/3`` free-box trailer. It exists for
    users who need to reproduce the reference fingerprint exactly; the default
    ``X1T Zilem`` preset stays neutral.
    """

    name = "zilem-v3"
    label = "X1T Zilem V3"
    direct = True

    def build_args(self, req: PatchRequest, info: VideoInfo, out: Path) -> list[str]:
        raise RuntimeError("X1T Zilem V3 does not use FFmpeg arguments.")


class _PresetDict(dict[str, PatchStrategy]):
    """Preset mapping dictionary with transparent x1t-* alias support."""

    _ALIASES = {
        "x1t-pc": "bxd-pc",
        "x1t-mobile": "bxd-mobile",
        "x1t-hybrid": "bxd-hybrid",
        "x1t-clean": "bxd-clean",
        "x1t-zilem": "zilem",
        "x1t-zilem-v3": "zilem-v3",
    }

    def __getitem__(self, key: str) -> PatchStrategy:
        return super().__getitem__(self._ALIASES.get(key, key))

    def get(self, key: str, default: Any = None) -> Any:
        return super().get(self._ALIASES.get(key, key), default)

    def __contains__(self, key: object) -> bool:
        return super().__contains__(key) or (isinstance(key, str) and key in self._ALIASES)


UI_PRESETS: dict[str, PatchStrategy] = _PresetDict({
    "zilem": ZilemStrategy(),
    "zilem-v3": ZilemV3Strategy(),
    "bxd-pc": BXDPCtrategy(),
    "bxd-mobile": BXDMobileStrategy(),
    "bxd-hybrid": BXDHybridStrategy(),
    "bxd-clean": BXDCleanStrategy(),
    "tiktok-ts": TikTokTSStrategy("tiktok-ts", "X1T 60fps"),
    "tiktok-ts-1080": TikTokTSStrategy(
        "tiktok-ts-1080", "X1T 1080p", force_1080=True
    ),
    "tiktok-ts-remux": TikTokTSRemuxStrategy(),
})

# The X1T/BXD family stays registered for saved settings, queue overrides and
# CLI compatibility, but it is no longer offered for new selections.
HIDDEN_PRESET_KEYS: frozenset[str] = frozenset(
    {"bxd-pc", "bxd-mobile", "bxd-hybrid", "bxd-clean"}
)
VISIBLE_PRESET_KEYS: tuple[str, ...] = tuple(
    key for key in UI_PRESETS if key not in HIDDEN_PRESET_KEYS
)


def visible_presets() -> list[PatchStrategy]:
    """Presets offered for new selections in the Inspector, Settings and queue."""
    return [UI_PRESETS[key] for key in VISIBLE_PRESET_KEYS]

STRATEGIES: dict[str, PatchStrategy] = {
    "zilem": UI_PRESETS["zilem"],
    "zilem-v3": UI_PRESETS["zilem-v3"],
    "bxd-pc": UI_PRESETS["bxd-pc"],
    "bxd-mobile": UI_PRESETS["bxd-mobile"],
    "bxd-hybrid": UI_PRESETS["bxd-hybrid"],
    "bxd-clean": UI_PRESETS["bxd-clean"],
    "tiktok-ts": UI_PRESETS["tiktok-ts"],
    "tiktok-ts-1080": UI_PRESETS["tiktok-ts-1080"],
    "tiktok-ts-remux": UI_PRESETS["tiktok-ts-remux"],
    "x1t-zilem": UI_PRESETS["zilem"],
    "x1t-zilem-v3": UI_PRESETS["zilem-v3"],
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
    "x1t-zilem": "zilem",
    "x1t-zilem-v3": "zilem-v3",
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
    if name in (
        "zilem",
        "zilem-v3",
        "bxd-pc",
        "bxd-mobile",
        "bxd-hybrid",
        "bxd-clean",
        "tiktok-ts",
        "tiktok-ts-1080",
        "tiktok-ts-remux",
    ):
        return name, None
    if name in ("x1t-zilem", "x1t-zilem-v3"):
        return name.removeprefix("x1t-"), None
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

