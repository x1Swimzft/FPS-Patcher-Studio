"""Tests for the lossy TikTok MPEG-TS presets."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest
from conftest import _make_clip

from fps_patcher.config import Settings
from fps_patcher.core.errors import PatchError, VerifyError
from fps_patcher.core.ffmpeg_locator import FFmpegPaths
from fps_patcher.core.models import LogEvent, PatchRequest, VideoInfo
from fps_patcher.core.patcher import _verify_ts_output, output_base_for, patch
from fps_patcher.core.strategies import (
    UI_PRESETS,
    VISIBLE_PRESET_KEYS,
    get_strategy,
)

_TS_1080_VF = (
    "scale=1920:1080:force_original_aspect_ratio=decrease"
    ":force_divisible_by=2,"
    "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=60"
)


def _opt(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def _info(src: Path) -> VideoInfo:
    return VideoInfo(
        path=src,
        codec="h264",
        width=640,
        height=360,
        avg_fps=Fraction(30),
        r_fps=Fraction(30),
        duration_s=2.0,
        timescale=15360,
        nb_frames=60,
        has_audio=True,
        stream_count=2,
    )


def _request(src: Path, out_dir: Path, strategy: str) -> PatchRequest:
    return PatchRequest(src=src, out_dir=out_dir, timescale=60000, strategy=strategy)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _has_h264_mf(ff: FFmpegPaths) -> bool:
    proc = _run([str(ff.ffmpeg), "-hide_banner", "-encoders"])
    return "h264_mf" in proc.stdout


def _trace_first_headers(ff: FFmpegPaths, path: Path) -> str:
    proc = _run(
        [
            str(ff.ffmpeg),
            "-hide_banner",
            "-v",
            "trace",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-c",
            "copy",
            "-bsf:v",
            "trace_headers",
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        ]
    )
    return proc.stderr


def test_build_args_common_flags() -> None:
    req = _request(Path("in.mp4"), Path("."), "tiktok-ts")
    args = get_strategy("tiktok-ts").build_args(req, _info(Path("in.mp4")), Path("out.mp4"))

    assert _opt(args, "-c:v") == "h264_mf"
    assert _opt(args, "-profile:v") == "77"
    assert _opt(args, "-rate_control") == "u_vbr"
    assert _opt(args, "-b:v") == "20480k"
    assert _opt(args, "-g") == "60"
    assert _opt(args, "-bf") == "2"
    assert _opt(args, "-pix_fmt") == "nv12"
    assert _opt(args, "-f") == "mpegts"
    assert _opt(args, "-c:a") == "aac"
    assert _opt(args, "-b:a") == "128k"
    assert _opt(args, "-ar") == "48000"
    assert _opt(args, "-ac") == "2"
    assert args[-1] == "out.mp4"
    assert args.count("-map") == 2
    assert "0:a:0?" in args
    assert _opt(args, "-vf") == "fps=60"


def test_build_args_1080_scales_and_pads() -> None:
    req = _request(Path("in.mp4"), Path("."), "tiktok-ts-1080")
    args = get_strategy("tiktok-ts-1080").build_args(
        req, _info(Path("in.mp4")), Path("out.mp4")
    )

    assert _opt(args, "-vf") == _TS_1080_VF


def test_output_base_for_ts_forces_mp4(tmp_path: Path) -> None:
    req = _request(tmp_path / "clip.mov", tmp_path / "out", "tiktok-ts")
    assert output_base_for(req).name == "clip_ts60000.mp4"


def test_build_args_remux_copies_video() -> None:
    req = _request(Path("in.mp4"), Path("."), "tiktok-ts-remux")
    args = get_strategy("tiktok-ts-remux").build_args(
        req, _info(Path("in.mp4")), Path("out.mp4")
    )

    assert _opt(args, "-c:v") == "copy"
    assert "-vf" not in args
    assert _opt(args, "-c:a") == "aac"
    assert _opt(args, "-b:a") == "128k"
    assert _opt(args, "-ar") == "48000"
    assert _opt(args, "-ac") == "2"
    assert _opt(args, "-f") == "mpegts"
    assert args[-1] == "out.mp4"
    assert "0:a:0?" in args


def test_tiktok_ts_encode_fingerprint(ff: FFmpegPaths, tmp_path: Path) -> None:
    if not _has_h264_mf(ff):
        pytest.skip("h264_mf encoder not available")
    src = _make_clip(ff, tmp_path / "src.mp4", "30")
    for strategy, size in (("tiktok-ts", (320, 240)), ("tiktok-ts-1080", (1920, 1080))):
        out = tmp_path / f"out_{strategy}.mp4"
        args = get_strategy(strategy).build_args(
            _request(src, tmp_path, strategy), _info(src), out
        )
        proc = _run([str(ff.ffmpeg), *args])
        assert proc.returncode == 0, proc.stderr

        data = out.read_bytes()
        assert data[:1] == b"\x47"
        assert b"Microsoft H.264 Encoder" in data
        assert b"cabac:0" in data
        assert b"gop:60" in data
        assert b"pf:77" in data

        probe = _run(
            [
                str(ff.ffprobe),
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(out),
            ]
        )
        meta = json.loads(probe.stdout)
        video = next(s for s in meta["streams"] if s["codec_type"] == "video")
        audio = next(s for s in meta["streams"] if s["codec_type"] == "audio")
        assert meta["format"]["format_name"] == "mpegts"
        assert video["codec_name"] == "h264"
        assert video["profile"] == "Main"
        assert video["r_frame_rate"] == "60/1"
        assert (video["width"], video["height"]) == size
        assert audio["codec_name"] == "aac"
        assert audio["sample_rate"] == "48000"
        assert str(audio["channels"]) == "2"

        trace = _trace_first_headers(ff, out)
        entropy = next(
            line for line in trace.splitlines() if "entropy_coding_mode_flag" in line
        )
        assert entropy.rstrip().endswith("= 0")
        time_scale = next(line for line in trace.splitlines() if "time_scale" in line)
        assert time_scale.rstrip().endswith("= 120")


def test_patch_tiktok_ts_runs_ts_branches(ff: FFmpegPaths, tmp_path: Path) -> None:
    if not _has_h264_mf(ff):
        pytest.skip("h264_mf encoder not available")
    src = _make_clip(ff, tmp_path / "src.mp4", "30")
    events: list[object] = []
    req = PatchRequest(
        src=src,
        out_dir=tmp_path / "out",
        timescale=60000,
        strategy="tiktok-ts",
        auto_normalize_audio=True,
        auto_cap_bitrate=True,
        fix_color_tag=True,
        scrub_metadata=True,
    )
    result = patch(req, ff, events.append)
    messages = [e.message for e in events if isinstance(e, LogEvent)]

    assert result.output.suffix == ".mp4"
    assert result.after.format_name == "mpegts"
    assert result.after.codec == "h264"
    assert result.after.r_fps == Fraction(60)
    assert result.output.read_bytes()[:1] == b"\x47"
    assert not any(m.startswith("[PREFLIGHT]") for m in messages)
    assert any("[COLOR] skipped: not ISO-BMFF" in m for m in messages)
    assert any("[VERIFY] MPEG-TS" in m for m in messages)


def test_x1t_presets_are_hidden_from_pickers() -> None:
    assert VISIBLE_PRESET_KEYS == (
        "tiktok-ts",
        "tiktok-ts-1080",
        "tiktok-ts-remux",
    )
    hidden = {"bxd-pc", "bxd-mobile", "bxd-hybrid", "bxd-clean"}
    assert set(UI_PRESETS) - set(VISIBLE_PRESET_KEYS) == hidden
    for key in hidden:
        assert get_strategy(key).name == key


def test_new_install_defaults_to_tiktok_ts() -> None:
    assert Settings().strategy == "tiktok-ts"


def test_ts_verify_rejects_wrong_1080_size(tmp_path: Path) -> None:
    out = tmp_path / "out.mp4"
    out.write_bytes(b"\x47")
    before = _info(Path("in.mp4"))
    after = replace(
        before,
        width=1280,
        height=720,
        avg_fps=Fraction(60),
        r_fps=Fraction(60),
    )
    with pytest.raises(VerifyError, match="1920x1080"):
        _verify_ts_output(
            before, after, out, expected_size=(1920, 1080), expected_fps=60.0
        )


def test_ts_verify_rejects_wrong_frame_rate(tmp_path: Path) -> None:
    out = tmp_path / "out.mp4"
    out.write_bytes(b"\x47")
    before = _info(Path("in.mp4"))
    after = replace(before, width=1920, height=1080)
    with pytest.raises(VerifyError, match="60 fps"):
        _verify_ts_output(
            before, after, out, expected_size=(1920, 1080), expected_fps=60.0
        )


def test_ts_verify_accepts_1080p60(tmp_path: Path) -> None:
    out = tmp_path / "out.mp4"
    out.write_bytes(b"\x47")
    before = _info(Path("in.mp4"))
    after = replace(
        before,
        width=1920,
        height=1080,
        avg_fps=Fraction(60),
        r_fps=Fraction(60),
    )
    _verify_ts_output(
        before, after, out, expected_size=(1920, 1080), expected_fps=60.0
    )


def test_ts_verify_accepts_remux_source_frame_rate(tmp_path: Path) -> None:
    out = tmp_path / "out.mp4"
    out.write_bytes(b"\x47")
    before = _info(Path("in.mp4"))
    _verify_ts_output(before, replace(before), out)


def test_patch_tiktok_ts_remux_copies_video(ff: FFmpegPaths, tmp_path: Path) -> None:
    src = _make_clip(ff, tmp_path / "src.mp4", "30")
    assert b"x264 - core" in src.read_bytes()

    events: list[object] = []
    req = PatchRequest(
        src=src,
        out_dir=tmp_path / "out",
        timescale=60000,
        strategy="tiktok-ts-remux",
        auto_normalize_audio=True,
        fix_color_tag=True,
        scrub_metadata=True,
    )
    result = patch(req, ff, events.append)
    messages = [e.message for e in events if isinstance(e, LogEvent)]
    out = result.output.read_bytes()

    assert result.after.format_name == "mpegts"
    assert result.after.codec == "h264"
    assert b"x264 - core" in out
    assert b"Microsoft H.264 Encoder" not in out
    assert result.after.audio_codec == "aac"
    assert result.after.audio_sample_rate == 48000
    assert result.after.audio_channels == 2
    assert not any(m.startswith("[PREFLIGHT]") for m in messages)
    assert any("[COLOR] skipped: not ISO-BMFF" in m for m in messages)
    assert any("[VERIFY] MPEG-TS" in m for m in messages)


def test_patch_tiktok_ts_remux_rejects_non_h264(
    ff: FFmpegPaths, tmp_path: Path
) -> None:
    encoders = _run([str(ff.ffmpeg), "-hide_banner", "-encoders"]).stdout
    if "libx265" not in encoders:
        pytest.skip("libx265 encoder not available")
    src = tmp_path / "hevc.mp4"
    proc = _run(
        [
            str(ff.ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=30:duration=1",
            "-c:v",
            "libx265",
            "-pix_fmt",
            "yuv420p",
            "-tag:v",
            "hvc1",
            str(src),
        ]
    )
    assert proc.returncode == 0, proc.stderr

    req = PatchRequest(
        src=src,
        out_dir=tmp_path / "out",
        timescale=60000,
        strategy="tiktok-ts-remux",
    )
    with pytest.raises(PatchError, match="requires an H.264 source"):
        patch(req, ff, lambda _: None)
