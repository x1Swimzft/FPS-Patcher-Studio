"""v2.0.0 Slice 3: actionable readiness / auto-remediation planning (no network)."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from fps_patcher.core import patcher
from fps_patcher.core.ffmpeg_locator import FFmpegPaths
from fps_patcher.core.models import LogEvent, PatchRequest, ProgressEvent, VideoInfo
from fps_patcher.core.patcher import patch
from fps_patcher.core.platform_profiles import (
    ReadinessCheck,
    ReadinessReport,
    evaluate_readiness,
    get_profile,
    remediable_checks,
)
from fps_patcher.core.preflight import (
    PreflightPlan,
    build_preflight_args,
    make_plan,
)


def _info(**kw: Any) -> VideoInfo:
    base: dict[str, Any] = {
        "path": Path("a.mp4"),
        "codec": "h264",
        "width": 1080,
        "height": 1920,
        "avg_fps": Fraction(30),
        "r_fps": Fraction(30),
        "duration_s": 10.0,
        "timescale": 30000,
        "nb_frames": 300,
        "has_audio": True,
        "stream_count": 2,
        "audio_codec": "aac",
        "bit_rate": 10_000_000,
        "audio_sample_rate": 48000,
        "audio_channels": 2,
        "file_size_bytes": 1024,
    }
    base.update(kw)
    return VideoInfo(**base)


def _vf(args: list[str]) -> str:
    return args[args.index("-vf") + 1]


def test_patch_request_remediation_flags_default_off() -> None:
    req = PatchRequest(src=Path("a.mp4"), out_dir=Path("out"), timescale=60000)
    assert req.auto_fix_vfr is False
    assert req.auto_fix_codec is False
    assert req.auto_cap_resolution is False


def test_make_plan_defaults_unchanged() -> None:
    info = _info(
        codec="av1",
        width=3840,
        height=2160,
        avg_fps=Fraction(30),
        r_fps=Fraction(60),
        audio_codec="pcm_s16le",
    )
    plan = make_plan(info, normalize_audio=True, cap_bitrate=False)
    assert plan == PreflightPlan(normalize_audio=True, cap_bitrate=False)
    assert plan.fix_vfr is False
    assert plan.transcode_codec is False
    assert plan.scale_width is None
    assert plan.scale_height is None
    assert plan.needs_video_encode is False


def test_vfr_fix_emits_cfr() -> None:
    vfr = _info(avg_fps=Fraction(30), r_fps=Fraction(60))
    plan = make_plan(vfr, normalize_audio=False, cap_bitrate=False, fix_vfr=True)
    assert plan.fix_vfr is True
    assert plan.needs_video_encode is True

    args = build_preflight_args(Path("in.mp4"), Path("out.mp4"), plan)
    assert args[args.index("-fps_mode") + 1] == "cfr"
    assert args[args.index("-c:v") + 1] == "libx264"

    cfr = _info(avg_fps=Fraction(30), r_fps=Fraction(30))
    cfr_plan = make_plan(cfr, normalize_audio=False, cap_bitrate=False, fix_vfr=True)
    assert cfr_plan.fix_vfr is False
    assert "-fps_mode" not in build_preflight_args(Path("in.mp4"), Path("out.mp4"), cfr_plan)


def test_codec_fix_for_unsupported_platform_codec() -> None:
    tiktok = get_profile("tiktok")
    av1 = _info(codec="av1")
    plan = make_plan(
        av1, normalize_audio=False, cap_bitrate=False, fix_codec=True, profile=tiktok
    )
    assert plan.transcode_codec is True
    assert plan.needs_video_encode is True

    h264 = make_plan(
        _info(codec="h264"),
        normalize_audio=False,
        cap_bitrate=False,
        fix_codec=True,
        profile=tiktok,
    )
    assert h264.transcode_codec is False

    generic = make_plan(
        av1,
        normalize_audio=False,
        cap_bitrate=False,
        fix_codec=True,
        profile=get_profile("generic"),
    )
    assert generic.transcode_codec is False

    no_profile = make_plan(
        av1, normalize_audio=False, cap_bitrate=False, fix_codec=True
    )
    assert no_profile.transcode_codec is False


def test_resolution_cap_long_side_for_instagram() -> None:
    plan = make_plan(
        _info(width=3840, height=2160),
        normalize_audio=False,
        cap_bitrate=False,
        cap_resolution=True,
        profile=get_profile("instagram"),
    )
    assert (plan.scale_width, plan.scale_height) == (1920, 1920)
    assert plan.needs_video_encode is True

    args = build_preflight_args(Path("in.mp4"), Path("out.mp4"), plan)
    assert _vf(args) == (
        "scale=w='min(iw,1920)':h='min(ih,1920)':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2"
    )


def test_resolution_cap_is_idempotent_at_limit() -> None:
    plan = make_plan(
        _info(width=1920, height=1080),
        normalize_audio=False,
        cap_bitrate=False,
        cap_resolution=True,
        profile=get_profile("youtube"),
    )
    assert (plan.scale_width, plan.scale_height) == (None, None)
    args = build_preflight_args(Path("in.mp4"), Path("out.mp4"), plan)
    assert "-vf" not in args


def test_resolution_cap_short_side_landscape_and_portrait() -> None:
    landscape = make_plan(
        _info(width=3840, height=2160),
        normalize_audio=False,
        cap_bitrate=False,
        cap_resolution=True,
        profile=get_profile("youtube"),
    )
    assert (landscape.scale_width, landscape.scale_height) == (3840, 1080)
    args = build_preflight_args(Path("in.mp4"), Path("out.mp4"), landscape)
    assert _vf(args).startswith("scale=w='min(iw,3840)':h='min(ih,1080)'")

    portrait = make_plan(
        _info(width=2160, height=3840),
        normalize_audio=False,
        cap_bitrate=False,
        cap_resolution=True,
        profile=get_profile("youtube"),
    )
    assert (portrait.scale_width, portrait.scale_height) == (1080, 3840)


def test_resolution_cap_respects_flag_and_profile() -> None:
    oversized = _info(width=3840, height=2160)
    assert make_plan(
        oversized, normalize_audio=False, cap_bitrate=False
    ).scale_width is None
    assert make_plan(
        oversized,
        normalize_audio=False,
        cap_bitrate=False,
        cap_resolution=True,
        profile=get_profile("tiktok"),
    ).scale_width is None


def test_needs_video_encode_controls_encoder_and_hwaccel() -> None:
    single_fix = build_preflight_args(
        Path("in.mp4"),
        Path("out.mp4"),
        PreflightPlan(normalize_audio=False, cap_bitrate=False, fix_vfr=True),
        "h264_nvenc",
        hwaccel="d3d11va",
    )
    assert single_fix[single_fix.index("-c:v") + 1] == "h264_nvenc"
    assert single_fix[single_fix.index("-hwaccel") + 1] == "d3d11va"

    audio_only = build_preflight_args(
        Path("in.mp4"),
        Path("out.mp4"),
        PreflightPlan(normalize_audio=True, cap_bitrate=False),
        "h264_nvenc",
        hwaccel="d3d11va",
    )
    assert audio_only[audio_only.index("-c:v") + 1] == "copy"
    assert "-hwaccel" not in audio_only


def test_remediable_checks_filters_unfixable_failures() -> None:
    report = ReadinessReport(
        profile_id="tiktok",
        score=20,
        status="issues",
        checks=(
            ReadinessCheck("container", "Container", "blocker", "error", ""),
            ReadinessCheck("audio", "Audio", "warning", "warning", ""),
            ReadinessCheck("duration", "Duration", "warning", "warning", ""),
            ReadinessCheck("file_size", "File size", "blocker", "error", ""),
            ReadinessCheck("frame_geometry", "Geometry", "blocker", "error", ""),
            ReadinessCheck("frame_rate", "Frame rate", "blocker", "error", ""),
            ReadinessCheck("hdr_color", "Color / HDR", "warning", "warning", ""),
            ReadinessCheck("video_codec", "Video codec", "blocker", "error", ""),
            ReadinessCheck("bitrate", "Bitrate", "warning", "warning", ""),
        ),
    )
    assert remediable_checks(report) == (
        "audio",
        "frame_geometry",
        "frame_rate",
        "video_codec",
        "bitrate",
    )


def test_remediable_checks_uses_real_readiness_report(tmp_path: Path) -> None:
    info = _info(
        path=tmp_path / "clip.mp4",
        codec="av1",
        audio_codec="pcm_s16le",
        bit_rate=30_000_000,
    )
    report = evaluate_readiness(info, "tiktok")
    assert remediable_checks(report) == ("video_codec", "audio", "bitrate")


def _hdr_info(tmp_path: Path, transfer: str, **kw: Any) -> VideoInfo:
    return _info(
        path=tmp_path / "clip.mp4",
        color_primaries="bt2020",
        color_transfer=transfer,
        color_space="bt2020nc",
        **kw,
    )


@pytest.mark.parametrize("transfer", ["smpte2084", "arib-std-b67"])
def test_patch_rejects_hdr_remediation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transfer: str
) -> None:
    from fps_patcher.core.errors import PatchError

    src = tmp_path / "clip.mp4"
    src.write_bytes(b"not media")
    info = _hdr_info(tmp_path, transfer, avg_fps=Fraction(30), r_fps=Fraction(60))
    monkeypatch.setattr(patcher, "probe", lambda *a, **k: info)

    req = PatchRequest(
        src=src,
        out_dir=tmp_path / "out",
        timescale=60000,
        strategy="direct-atom",
        auto_fix_vfr=True,
        platform_profile="tiktok",
    )
    with pytest.raises(PatchError, match="tone-mapping"):
        patch(req, None, lambda _event: None)


def test_patch_hdr_bitrate_cap_still_reaches_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fps_patcher.core.errors import PatchError

    src = tmp_path / "clip.mp4"
    src.write_bytes(b"not media")
    info = _hdr_info(tmp_path, "smpte2084", bit_rate=40_000_000)
    monkeypatch.setattr(patcher, "probe", lambda *a, **k: info)

    reached: list[bool] = []

    def fake_run_preflight(*args: Any, **kwargs: Any) -> Path:
        reached.append(True)
        raise PatchError("reached preflight")

    monkeypatch.setattr(patcher, "run_preflight", fake_run_preflight)

    req = PatchRequest(
        src=src,
        out_dir=tmp_path / "out",
        timescale=60000,
        strategy="direct-atom",
        auto_cap_bitrate=True,
        platform_profile="tiktok",
    )
    paths = FFmpegPaths(ffmpeg=Path("ffmpeg.exe"), ffprobe=Path("ffprobe.exe"), version="test")
    with pytest.raises(PatchError, match="reached preflight"):
        patch(req, paths, lambda _event: None)
    assert reached == [True]


def test_patch_warns_when_remediation_encode_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fps_patcher.core.errors import PatchError

    src = tmp_path / "clip.mp4"
    src.write_bytes(b"not media")
    info = _info(
        path=tmp_path / "clip.mp4", avg_fps=Fraction(30), r_fps=Fraction(60)
    )
    monkeypatch.setattr(patcher, "probe", lambda *a, **k: info)

    def fake_run_preflight(*args: Any, **kwargs: Any) -> Path:
        raise PatchError("stop after preflight")

    monkeypatch.setattr(patcher, "run_preflight", fake_run_preflight)

    req = PatchRequest(
        src=src,
        out_dir=tmp_path / "out",
        timescale=60000,
        strategy="direct-atom",
        auto_fix_vfr=True,
        platform_profile="tiktok",
    )
    events: list[LogEvent | ProgressEvent] = []
    paths = FFmpegPaths(ffmpeg=Path("ffmpeg.exe"), ffprobe=Path("ffprobe.exe"), version="test")
    with pytest.raises(PatchError, match="stop after preflight"):
        patch(req, paths, events.append)

    assert any(
        isinstance(event, LogEvent)
        and event.level == "WARN"
        and "Lossy video re-encode active" in event.message
        for event in events
    )
