"""Platform presets and deterministic pre-flight readiness scoring.

This module is deliberately pure: no Tk, no FFmpeg, no network. The profile data
is deterministic offline information; the cited sources are documentation URLs,
not runtime dependencies. All checks are read-only and never mutate media.

Evidence labels
---------------
``documented``   The platform explicitly documents the condition.
``recommended``  A published recommendation, not a strict acceptance rule.
``heuristic``    A practical file-level warning, not a platform guarantee.

The score is a local heuristic. It is not an official platform score and does not
predict whether a platform will skip re-compression.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .models import VideoInfo

Evidence = Literal["documented", "recommended", "heuristic"]
Severity = Literal["blocker", "warning", "recommendation"]
CheckStatus = Literal["pass", "warning", "error", "unknown"]
ReadinessStatus = Literal["ready", "review", "issues", "unknown"]

BLOCKER_PENALTY = 40
WARNING_PENALTY = 12
RECOMMENDATION_PENALTY = 3
BLOCKER_SCORE_CAP = 40
CRITICAL_UNKNOWN_SCORE_CAP = 70
OPTIONAL_UNKNOWN_SCORE_CAP = 95
ISSUES_SCORE_MAX = 49
READY_SCORE_MIN = 85

DEFAULT_PROFILE_ID = "generic"

_TIKTOK_SOURCES = (
    "https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide",
    "https://support.tiktok.com/en/using-tiktok/creating-videos/video-upload-requirements",
)
_INSTAGRAM_SOURCES = (
    "https://help.instagram.com/1038071743007909",
    "https://about.instagram.com/features/reels",
)
_YOUTUBE_SOURCES = (
    "https://support.google.com/youtube/answer/1722171",
    "https://support.google.com/youtube/answer/15424877",
    "https://support.google.com/youtube/answer/12779649",
)

_VIDEO_CODECS = frozenset({"h264", "hevc", "vp8", "vp9", "av1"})


@dataclass(frozen=True)
class PlatformProfile:
    """One supported platform profile. ``None`` disables an optional check."""

    profile_id: str
    label_key: str
    short_name: str
    prefer_mp4: bool
    video_codecs: frozenset[str]
    preferred_video_codecs: frozenset[str]
    sources: tuple[str, ...]
    notes: str
    min_dimension: int | None = None
    max_dimension: int | None = None
    dimension_severity: Severity = "warning"
    min_aspect: float | None = None
    max_aspect: float | None = None
    preferred_aspect: float | None = None
    aspect_severity: Severity = "warning"
    max_short_side: int | None = None
    min_fps: float | None = None
    max_fps: float | None = None
    preferred_min_fps: float | None = None
    fps_severity: Severity = "warning"
    max_duration_s: float | None = None
    duration_note: str = ""
    max_file_size_bytes: int | None = None
    audio_sample_rate: int | None = 48_000
    audio_max_channels: int | None = 2
    bitrate_warning_bps: int | None = None
    bitrate_evidence: Evidence = "heuristic"
    check_hdr: bool = True

    @property
    def bitrate_warning_mbps(self) -> float | None:
        if self.bitrate_warning_bps is None:
            return None
        return self.bitrate_warning_bps / 1_000_000


PLATFORM_PROFILES: dict[str, PlatformProfile] = {
    "generic": PlatformProfile(
        profile_id="generic",
        label_key="profile_generic",
        short_name="Basic",
        prefer_mp4=False,
        video_codecs=_VIDEO_CODECS,
        preferred_video_codecs=frozenset({"h264"}),
        sources=(),
        notes="General MP4/MOV compatibility checks only; no platform-specific limits.",
    ),
    "tiktok": PlatformProfile(
        profile_id="tiktok",
        label_key="profile_tiktok",
        short_name="TikTok",
        prefer_mp4=True,
        video_codecs=frozenset({"h264", "hevc", "vp8", "vp9"}),
        preferred_video_codecs=frozenset({"h264"}),
        sources=_TIKTOK_SOURCES,
        notes=(
            "TikTok's Content Posting API documents MP4/MOV/WebM, H.264/H.265/VP8/VP9, "
            "23-60 fps, 360-4096 px, 4 GB, and a 10-minute API limit. The 20 Mbps "
            "warning is a local heuristic, not a TikTok cap."
        ),
        min_dimension=360,
        max_dimension=4096,
        dimension_severity="blocker",
        preferred_aspect=9 / 16,
        aspect_severity="warning",
        min_fps=23,
        max_fps=60,
        fps_severity="blocker",
        max_duration_s=10 * 60,
        duration_note=(
            "TikTok's API accepts up to 10 minutes; in-app limits depend on the creator."
        ),
        max_file_size_bytes=4 * 1024**3,
        bitrate_warning_bps=20_000_000,
        bitrate_evidence="heuristic",
    ),
    "instagram": PlatformProfile(
        profile_id="instagram",
        label_key="profile_instagram",
        short_name="Reels",
        prefer_mp4=True,
        video_codecs=frozenset({"h264", "hevc", "vp9", "av1"}),
        preferred_video_codecs=frozenset({"h264", "hevc"}),
        sources=_INSTAGRAM_SOURCES,
        notes=(
            "Instagram Help documents a 1.91:1 to 9:16 aspect ratio range and a "
            "minimum 30 fps, with 9:16 recommended. Codec, 25 Mbps, and 1920 px "
            "limits are labelled heuristic because Meta does not publish a complete "
            "public Reels ingest spec."
        ),
        max_dimension=1920,
        dimension_severity="warning",
        min_aspect=9 / 16,
        max_aspect=1.91,
        preferred_aspect=9 / 16,
        aspect_severity="blocker",
        min_fps=30,
        max_fps=60,
        preferred_min_fps=30,
        fps_severity="warning",
        max_duration_s=180,
        duration_note=(
            "Reels over 3 minutes are not recommended to new audiences. "
            "3 minutes is the practical Reels window."
        ),
        bitrate_warning_bps=25_000_000,
        bitrate_evidence="heuristic",
    ),
    "youtube": PlatformProfile(
        profile_id="youtube",
        label_key="profile_youtube",
        short_name="Shorts",
        prefer_mp4=True,
        video_codecs=frozenset({"h264", "hevc", "vp9", "av1"}),
        preferred_video_codecs=frozenset({"h264"}),
        sources=_YOUTUBE_SOURCES,
        notes=(
            "YouTube recommends MP4, H.264, AAC-LC 48 kHz, and uploading at the "
            "source frame rate. Shorts are square or vertical and up to 3 minutes; the "
            "Shorts uploader documents a 1080p maximum. YouTube states no bitrate "
            "limit is required, so no bitrate warning is applied."
        ),
        max_aspect=1.0,
        aspect_severity="warning",
        max_short_side=1080,
        min_fps=24,
        max_fps=60,
        preferred_min_fps=24,
        fps_severity="warning",
        max_duration_s=180,
        duration_note=(
            "Square or vertical uploads longer than 3 minutes become regular videos, "
            "not Shorts."
        ),
        bitrate_warning_bps=None,
        bitrate_evidence="recommended",
    ),
}


def get_profile(profile_id: str | None) -> PlatformProfile:
    """Return a known profile, falling back to the generic profile."""
    return PLATFORM_PROFILES.get(str(profile_id or ""), PLATFORM_PROFILES[DEFAULT_PROFILE_ID])


def profile_ids() -> tuple[str, ...]:
    return tuple(PLATFORM_PROFILES)


@dataclass(frozen=True)
class ReadinessCheck:
    check_id: str
    label: str
    severity: Severity
    status: CheckStatus
    detail: str
    measured: str | None = None
    recommendation: str | None = None
    evidence: Evidence | None = None


@dataclass(frozen=True)
class ReadinessReport:
    profile_id: str
    score: int
    status: ReadinessStatus
    checks: tuple[ReadinessCheck, ...]

    @property
    def failed_checks(self) -> tuple[ReadinessCheck, ...]:
        return tuple(c for c in self.checks if c.status in ("warning", "error"))

    @property
    def unknown_checks(self) -> tuple[ReadinessCheck, ...]:
        return tuple(c for c in self.checks if c.status == "unknown")


def _check(
    check_id: str,
    label: str,
    severity: Severity,
    status: CheckStatus,
    detail: str,
    *,
    measured: str | None = None,
    recommendation: str | None = None,
    evidence: Evidence | None = None,
) -> ReadinessCheck:
    return ReadinessCheck(
        check_id=check_id,
        label=label,
        severity=severity,
        status=status,
        detail=detail,
        measured=measured,
        recommendation=recommendation,
        evidence=evidence,
    )


def _container_check(info: VideoInfo, profile: PlatformProfile) -> ReadinessCheck:
    fmt = (info.format_name or "").strip().lower()
    if fmt in ("unknown", "none"):
        fmt = ""
    suffix = info.path.suffix.lower()
    is_mp4 = "mp4" in fmt or (not fmt and suffix in (".mp4", ".m4v"))
    is_mov = "mov" in fmt or (not fmt and suffix == ".mov")
    measured = f"format={fmt or 'unknown'}, suffix={suffix or 'none'}"
    evidence: Evidence = "documented"
    if is_mp4:
        return _check(
            "container", "Container", "blocker", "pass",
            "MP4 container.", measured=measured, evidence=evidence,
        )
    if is_mov:
        if profile.prefer_mp4:
            return _check(
                "container", "Container", "recommendation", "warning",
                f"MOV is accepted by {profile.short_name}, but MP4 is the "
                "documented recommendation.",
                measured=measured,
                recommendation="Export MP4 for the widest platform compatibility.",
                evidence=evidence,
            )
        return _check(
            "container", "Container", "blocker", "pass",
            "MOV container.", measured=measured, evidence=evidence,
        )
    if not fmt and suffix in (".mp4", ".mov", ".m4v"):
        return _check(
            "container", "Container", "blocker", "pass",
            "MP4/MOV container extension.", measured=measured, evidence=evidence,
        )
    return _check(
        "container", "Container", "blocker", "error",
        "Container is not MP4 or MOV.",
        measured=measured,
        recommendation="Remux to MP4 (H.264 or HEVC) before uploading.",
        evidence=evidence,
    )


def _video_codec_check(info: VideoInfo, profile: PlatformProfile) -> ReadinessCheck:
    codec = (info.codec or "").strip().lower()
    if codec in ("", "unknown", "none"):
        return _check(
            "video_codec", "Video codec", "blocker", "unknown",
            "Video codec could not be identified from probe data.",
            recommendation="Re-probe with FFmpeg/ffprobe or export H.264.",
        )
    if codec not in profile.video_codecs:
        return _check(
            "video_codec", "Video codec", "blocker", "error",
            f"'{codec}' is not in {profile.short_name}'s documented codec list.",
            measured=codec,
            recommendation="Export H.264 (or HEVC where supported).",
            evidence="documented" if profile.profile_id != "generic" else "heuristic",
        )
    if profile.preferred_video_codecs and codec not in profile.preferred_video_codecs:
        return _check(
            "video_codec", "Video codec", "recommendation", "warning",
            f"'{codec}' is accepted, but H.264 has the widest compatibility.",
            measured=codec,
            recommendation="Use H.264 High Profile for the safest upload.",
            evidence="recommended",
        )
    return _check(
        "video_codec", "Video codec", "blocker", "pass",
        f"'{codec}' is supported.", measured=codec, evidence="documented",
    )


def _frame_geometry_check(info: VideoInfo, profile: PlatformProfile) -> ReadinessCheck | None:
    if (
        profile.min_dimension is None
        and profile.max_dimension is None
        and profile.min_aspect is None
        and profile.max_aspect is None
        and profile.preferred_aspect is None
        and profile.max_short_side is None
    ):
        return None
    width, height = info.width, info.height
    if width <= 0 or height <= 0:
        return _check(
            "frame_geometry", "Resolution / aspect ratio", "warning", "unknown",
            "Resolution is unavailable, so aspect-ratio and dimension checks cannot run.",
            recommendation="Re-probe the file with ffprobe.",
        )

    short_side = min(width, height)
    long_side = max(width, height)
    aspect = width / height
    problems: list[str] = []
    blockers: list[str] = []
    recommendations: list[str] = []

    if profile.min_dimension is not None and short_side < profile.min_dimension:
        blockers.append(f"short side {short_side}px is below {profile.min_dimension}px")
    if profile.max_dimension is not None and long_side > profile.max_dimension:
        target = blockers if profile.dimension_severity == "blocker" else problems
        target.append(f"long side {long_side}px exceeds {profile.max_dimension}px")
    if profile.min_aspect is not None and aspect < profile.min_aspect - 1e-6:
        (blockers if profile.aspect_severity == "blocker" else problems).append(
            f"aspect {aspect:.2f}:1 is wider than the supported range"
        )
    if profile.max_aspect is not None and aspect > profile.max_aspect + 1e-6:
        (blockers if profile.aspect_severity == "blocker" else problems).append(
            f"aspect {aspect:.2f}:1 is outside the supported range"
        )
    if (
        profile.preferred_aspect is not None
        and abs(aspect - profile.preferred_aspect) / profile.preferred_aspect > 0.02
    ):
        problems.append(f"aspect {aspect:.2f}:1 is not the recommended 9:16")
    if profile.max_short_side is not None and short_side > profile.max_short_side:
        problems.append(
            f"short side {short_side}px exceeds the documented "
            f"{profile.max_short_side}px upload size"
        )
        recommendations.append("Export at 1080x1920 (or 1080x1080) for Shorts.")

    measured = f"{width}x{height} ({aspect:.2f}:1)"
    if blockers:
        return _check(
            "frame_geometry", "Resolution / aspect ratio", "blocker", "error",
            "; ".join(blockers + problems),
            measured=measured,
            recommendation="Resize/crop to a supported vertical frame before uploading.",
            evidence="documented",
        )
    if problems:
        return _check(
            "frame_geometry", "Resolution / aspect ratio", "warning", "warning",
            "; ".join(problems),
            measured=measured,
            recommendation=(
                recommendations[0]
                if recommendations
                else "1080x1920 (9:16) is the safest vertical frame."
            ),
            evidence="recommended" if profile.profile_id == "youtube" else "heuristic",
        )
    return _check(
        "frame_geometry", "Resolution / aspect ratio", "warning", "pass",
        "Resolution and aspect ratio are suitable.", measured=measured,
        evidence="documented",
    )


def _frame_rate_check(info: VideoInfo, profile: PlatformProfile) -> ReadinessCheck | None:
    if profile.min_fps is None and profile.max_fps is None:
        return None
    fps = info.fps
    if fps <= 0:
        return _check(
            "frame_rate", "Frame rate", "warning", "unknown",
            "Frame rate is unavailable.",
            recommendation="Re-probe with ffprobe or export a constant frame rate.",
        )
    measured = f"{fps:.3f} fps"
    out_of_range = (
        (profile.min_fps is not None and fps < profile.min_fps)
        or (profile.max_fps is not None and fps > profile.max_fps)
    )
    below_preferred = profile.preferred_min_fps is not None and fps < profile.preferred_min_fps
    problems: list[str] = []
    if out_of_range:
        problems.append(
            f"{fps:.2f} fps is outside {profile.min_fps:g}-{profile.max_fps:g} fps"
        )
    elif below_preferred:
        problems.append(f"{fps:.2f} fps is below the recommended {profile.preferred_min_fps:g} fps")
    if info.is_vfr:
        problems.append("variable frame rate detected")

    if out_of_range and profile.fps_severity == "blocker":
        return _check(
            "frame_rate", "Frame rate", "blocker", "error", "; ".join(problems),
            measured=measured,
            recommendation="Export a constant 30 or 60 fps file.",
            evidence="documented",
        )
    if problems:
        return _check(
            "frame_rate", "Frame rate", "warning", "warning", "; ".join(problems),
            measured=measured,
            recommendation="Use a constant 30 or 60 fps export for predictable playback.",
            evidence="documented" if out_of_range else "heuristic",
        )
    return _check(
        "frame_rate", "Frame rate", "warning", "pass",
        "Frame rate is suitable.", measured=measured, evidence="documented",
    )


def _duration_check(info: VideoInfo, profile: PlatformProfile) -> ReadinessCheck | None:
    if profile.max_duration_s is None:
        return None
    if info.duration_s <= 0:
        return _check(
            "duration", "Duration", "warning", "unknown",
            "Duration is unavailable.",
            recommendation="Re-probe with ffprobe.",
        )
    limit = profile.max_duration_s
    measured = f"{info.duration_s:.1f} s"
    if info.duration_s > limit:
        return _check(
            "duration", "Duration", "warning", "warning",
            f"{info.duration_s:.1f}s exceeds the {limit:g}s window. {profile.duration_note}",
            measured=measured,
            recommendation="Trim the clip or accept that it will be treated as long-form.",
            evidence="documented",
        )
    return _check(
        "duration", "Duration", "warning", "pass",
        f"Within the {limit:g}s window.", measured=measured, evidence="documented",
    )


def _file_size_check(
    info: VideoInfo,
    profile: PlatformProfile,
    file_size_bytes: int | None,
) -> ReadinessCheck | None:
    if profile.max_file_size_bytes is None:
        return None
    size = file_size_bytes
    if size is None:
        size = info.file_size_bytes
    if size is None:
        try:
            size = Path(info.path).stat().st_size
        except OSError:
            return _check(
                "file_size", "File size", "warning", "unknown",
                "File size is unavailable.",
                recommendation="Check the file on disk before uploading.",
            )
    measured = f"{size / 1024**3:.2f} GiB"
    if size > profile.max_file_size_bytes:
        return _check(
            "file_size", "File size", "blocker", "error",
            f"{size / 1024**3:.2f} GiB exceeds the documented 4 GiB limit.",
            measured=measured,
            recommendation="Compress or split the file before uploading.",
            evidence="documented",
        )
    return _check(
        "file_size", "File size", "blocker", "pass",
        "Within the documented size limit.", measured=measured, evidence="documented",
    )


def _audio_check(info: VideoInfo, profile: PlatformProfile) -> ReadinessCheck:
    if not info.has_audio:
        return _check(
            "audio", "Audio", "warning", "pass",
            "No audio track; silence is accepted.", evidence="documented",
        )
    codec = (info.audio_codec or "").strip().lower()
    sample_rate = info.audio_sample_rate
    channels = info.audio_channels
    measured_parts: list[str] = [codec or "unknown codec"]
    if sample_rate is not None:
        measured_parts.append(f"{sample_rate} Hz")
    if channels is not None:
        measured_parts.append(f"{channels} ch")
    measured = ", ".join(measured_parts)

    problems: list[str] = []
    if not codec or codec == "unknown":
        problems.append("audio codec could not be identified")
    elif codec not in ("aac", "mp4a"):
        problems.append(f"'{codec}' is not AAC-LC")
    if (
        sample_rate is not None
        and profile.audio_sample_rate is not None
        and sample_rate != profile.audio_sample_rate
    ):
        problems.append(f"{sample_rate} Hz is not {profile.audio_sample_rate} Hz")
    if (
        channels is not None
        and profile.audio_max_channels is not None
        and channels > profile.audio_max_channels
    ):
        problems.append(f"{channels} channels exceeds {profile.audio_max_channels}")

    unknown_parts: list[str] = []
    if sample_rate is None:
        unknown_parts.append("sample rate")
    if channels is None:
        unknown_parts.append("channel count")

    if problems:
        return _check(
            "audio", "Audio", "warning", "warning", "; ".join(problems),
            measured=measured,
            recommendation="AAC-LC, 48 kHz, mono or stereo.",
            evidence="recommended",
        )
    if unknown_parts:
        return _check(
            "audio", "Audio", "warning", "unknown",
            f"AAC audio detected, but {' and '.join(unknown_parts)} could not be verified.",
            measured=measured,
            recommendation="Re-probe with ffprobe to confirm 48 kHz stereo.",
        )
    return _check(
        "audio", "Audio", "warning", "pass",
        "AAC-LC at the recommended sample rate and channel count.",
        measured=measured, evidence="recommended",
    )


def _bitrate_check(info: VideoInfo, profile: PlatformProfile) -> ReadinessCheck | None:
    threshold = profile.bitrate_warning_bps
    if threshold is None:
        return None
    if info.bit_rate is None:
        return _check(
            "bitrate", "Bitrate", "warning", "unknown",
            "Bitrate is unavailable, so the profile warning cannot be evaluated.",
            recommendation="Re-probe with ffprobe.",
            evidence=profile.bitrate_evidence,
        )
    mbps = info.bit_rate / 1_000_000
    measured = f"{mbps:.1f} Mbps"
    if info.bit_rate > threshold:
        return _check(
            "bitrate", "Bitrate", "warning", "warning",
            (
                f"{mbps:.1f} Mbps exceeds this profile's {threshold / 1_000_000:.0f} Mbps "
                "heuristic warning threshold. This is not a published platform cap."
            ),
            measured=measured,
            recommendation="Consider 12-18 Mbps for 1080p short-form exports.",
            evidence=profile.bitrate_evidence,
        )
    return _check(
        "bitrate", "Bitrate", "warning", "pass",
        f"Within this profile's {threshold / 1_000_000:.0f} Mbps heuristic warning threshold.",
        measured=measured, evidence=profile.bitrate_evidence,
    )


def _hdr_check(info: VideoInfo, profile: PlatformProfile) -> ReadinessCheck | None:
    if not profile.check_hdr:
        return None
    transfer = (info.color_transfer or "").strip().lower()
    primaries = (info.color_primaries or "").strip().lower()
    matrix = (info.color_space or "").strip().lower()
    measured_parts = [
        f"transfer={transfer or 'unknown'}",
        f"primaries={primaries or 'unknown'}",
        f"matrix={matrix or 'unknown'}",
    ]
    measured = ", ".join(measured_parts)
    if not transfer and not primaries and not matrix:
        return _check(
            "hdr_color", "Color / HDR", "recommendation", "unknown",
            "Color metadata is not tagged, so HDR status cannot be verified.",
            recommendation="Tag color metadata at export; keep any HDR signaling intact.",
        )
    is_hdr = (
        transfer in ("smpte2084", "arib-std-b67", "pq", "hlg")
        or primaries == "bt2020"
        or matrix.startswith("bt2020")
    )
    if is_hdr:
        return _check(
            "hdr_color", "Color / HDR", "warning", "warning",
            "HDR/BT.2020 source detected. Platform profiles target SDR guidance and "
            "do not convert HDR.",
            measured=measured,
            recommendation=(
                "Keep the HDR/BT.2020 metadata intact; do not force Rec.709 or strip color tags."
            ),
            evidence="recommended",
        )
    if transfer in ("bt709", "iec61966-2-1") or primaries == "bt709":
        return _check(
            "hdr_color", "Color / HDR", "recommendation", "pass",
            "SDR Rec.709 color metadata.", measured=measured, evidence="recommended",
        )
    return _check(
        "hdr_color", "Color / HDR", "recommendation", "unknown",
        "Color metadata is present but HDR status could not be verified.",
        measured=measured,
        recommendation="Review the tags before uploading; keep them unchanged if HDR.",
    )


def _score_checks(checks: tuple[ReadinessCheck, ...]) -> tuple[int, ReadinessStatus]:
    penalty = 0
    has_blocker = False
    has_warning = False
    has_critical_unknown = False
    has_optional_unknown = False
    for check in checks:
        if check.status == "error":
            penalty += {
                "blocker": BLOCKER_PENALTY,
                "warning": WARNING_PENALTY,
                "recommendation": RECOMMENDATION_PENALTY,
            }[check.severity]
            if check.severity == "blocker":
                has_blocker = True
        elif check.status == "warning":
            penalty += {
                "blocker": BLOCKER_PENALTY,
                "warning": WARNING_PENALTY,
                "recommendation": RECOMMENDATION_PENALTY,
            }[check.severity]
            if check.severity in ("blocker", "warning"):
                has_warning = True
        elif check.status == "unknown":
            if check.severity in ("blocker", "warning"):
                has_critical_unknown = True
            else:
                has_optional_unknown = True

    score = max(0, 100 - penalty)
    if has_blocker:
        score = min(score, BLOCKER_SCORE_CAP)
    if has_critical_unknown:
        score = min(score, CRITICAL_UNKNOWN_SCORE_CAP)
    elif has_optional_unknown:
        score = min(score, OPTIONAL_UNKNOWN_SCORE_CAP)

    if has_blocker or score <= ISSUES_SCORE_MAX:
        status: ReadinessStatus = "issues"
    elif has_warning or has_critical_unknown or score < READY_SCORE_MIN:
        status = "review"
    else:
        status = "ready"
    return score, status


def evaluate_readiness(
    info: VideoInfo | None,
    profile_id: str | None,
    *,
    file_size_bytes: int | None = None,
) -> ReadinessReport:
    """Compute a deterministic readiness report from existing probe data."""
    profile = get_profile(profile_id)
    if info is None:
        return ReadinessReport(
            profile_id=profile.profile_id,
            score=0,
            status="unknown",
            checks=(
                _check(
                    "probe", "Probe", "blocker", "unknown",
                    "No probe data is available for this file.",
                    recommendation="Wait for probing to finish, then review the result.",
                ),
            ),
        )

    ordered = (
        _container_check(info, profile),
        _video_codec_check(info, profile),
        _frame_geometry_check(info, profile),
        _frame_rate_check(info, profile),
        _duration_check(info, profile),
        _file_size_check(info, profile, file_size_bytes),
        _audio_check(info, profile),
        _bitrate_check(info, profile),
        _hdr_check(info, profile),
    )
    checks = tuple(check for check in ordered if check is not None)
    score, status = _score_checks(checks)
    return ReadinessReport(
        profile_id=profile.profile_id,
        score=score,
        status=status,
        checks=checks,
    )
