from __future__ import annotations

import hashlib
import threading
from fractions import Fraction
from pathlib import Path

import pytest

from fps_patcher.core.errors import (
    FFmpegNotFoundError,
    OutputFileExistsError,
    PatchCancelledError,
    PatchError,
    ProbeError,
    VerifyError,
)
from fps_patcher.core.ffmpeg_locator import FFmpegPaths, locate
from fps_patcher.core.models import PatchRequest, VideoInfo
from fps_patcher.core.patcher import _parse_progress, output_path_for, patch
from fps_patcher.core.prober import parse_fraction, parse_probe, probe
from fps_patcher.core.strategies import (
    STRATEGIES,
    get_strategy,
    strategy_requires_ffmpeg,
)
from fps_patcher.core.verifier import verify


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------- locator ----------


def test_locate_finds_working_pair(ff: FFmpegPaths) -> None:
    assert ff.ffmpeg.is_file() and ff.ffprobe.is_file()
    assert "ffmpeg version" in ff.version


@pytest.mark.usefixtures("ff")  # skips when no ffmpeg is installed to fall back to
def test_locate_custom_dir_invalid_falls_back(tmp_path: Path) -> None:
    paths = locate(tmp_path)  # empty dir -> falls back to PATH/bin
    assert paths.ffmpeg.parent != tmp_path


def test_locate_missing_raises_detailed_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.setattr(
        "fps_patcher.core.ffmpeg_locator._bundled_bin_dirs", lambda: [tmp_path / "bin"]
    )
    monkeypatch.setattr(
        "fps_patcher.core.ffmpeg_locator.managed_bin_dir",
        lambda: tmp_path / "managed",
    )
    with pytest.raises(FFmpegNotFoundError) as exc_info:
        locate(tmp_path / "custom")
    msg = str(exc_info.value)
    assert "FFmpeg not found" in msg
    assert "custom directory" in msg
    assert "bundled 'bin/' directory" in msg
    assert "system PATH" in msg


# ---------- prober ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("30/1", Fraction(30)),
        ("30000/1001", Fraction(30000, 1001)),
        ("0/0", Fraction(0)),
        (None, Fraction(0)),
        ("abc", Fraction(0)),
        ("25", Fraction(25)),
    ],
)
def test_parse_fraction(raw: str | None, expected: Fraction) -> None:
    assert parse_fraction(raw) == expected


def test_parse_probe_no_video() -> None:
    with pytest.raises(ProbeError):
        parse_probe(Path("x.mp4"), {"streams": [{"codec_type": "audio"}]})


def test_probe_30fps(clip30: Path, ff: FFmpegPaths) -> None:
    info = probe(clip30, ff.ffprobe)
    assert info.codec == "h264"
    assert round(info.fps) == 30
    assert info.has_audio and info.stream_count == 2
    assert info.timescale > 0


def test_probe_5994(clip5994: Path, ff: FFmpegPaths) -> None:
    info = probe(clip5994, ff.ffprobe)
    assert abs(info.fps - 59.94) < 0.01


def test_probe_missing(ff: FFmpegPaths, tmp_path: Path) -> None:
    with pytest.raises(ProbeError):
        probe(tmp_path / "nope.mp4", ff.ffprobe)


# ---------- strategies ----------


def _info(
    codec: str = "h264",
    width: int = 1,
    height: int = 1,
    fps: Fraction = Fraction(30),
    duration: float = 1.0,
    timescale: int = 15360,
    nb_frames: int | None = 30,
    has_audio: bool = True,
    stream_count: int = 2,
) -> VideoInfo:
    return VideoInfo(
        Path("a.mp4"),
        codec,
        width,
        height,
        fps,
        fps,
        duration,
        timescale,
        nb_frames,
        has_audio,
        stream_count,
    )


def test_strategy_routing_real_objects() -> None:
    for name in ("direct-atom", "v4-forensic", "bxd-experimental", "ffmpeg-copy"):
        strat = get_strategy(name)
        assert strat.name == name
        assert strat == STRATEGIES[name]

    # V4 must not route to BXD
    assert get_strategy("v4-forensic").name == "v4-forensic"
    assert get_strategy("bxd-experimental").name == "bxd-experimental"

    # Aliases
    assert get_strategy("bxd-bypass").name == "bxd-experimental"
    assert get_strategy("timescale").name == "ffmpeg-copy"


def test_strategy_requires_ffmpeg() -> None:
    assert strategy_requires_ffmpeg("direct-atom") is False
    assert strategy_requires_ffmpeg("v4-forensic") is False
    assert strategy_requires_ffmpeg("bxd-experimental") is False
    assert strategy_requires_ffmpeg("ffmpeg-copy") is True


def test_bxd_strategy_properties() -> None:
    strat = get_strategy("bxd-experimental")
    assert strat.name == "bxd-experimental"
    assert strat.direct is True
    with pytest.raises(RuntimeError):
        strat.build_args(
            PatchRequest(src=Path("in.mp4"), out_dir=Path("."), timescale=60000),
            _info(),
            Path("out.mp4"),
        )


def test_unknown_strategy() -> None:
    with pytest.raises(ValueError):
        get_strategy("nope")


# ---------- patcher helpers ----------


def test_output_path_collision(tmp_path: Path) -> None:
    req = PatchRequest(src=tmp_path / "v.mp4", out_dir=tmp_path, timescale=60000)
    first = output_path_for(req)
    assert first.name == "v_ts60000.mp4"
    first.write_bytes(b"x")
    assert output_path_for(req).name == "v_ts60000 (1).mp4"


def test_output_path_collision_error_when_auto_rename_disabled(tmp_path: Path) -> None:
    base = tmp_path / "v_ts60000.mp4"
    base.write_bytes(b"x")
    req = PatchRequest(
        src=tmp_path / "v.mp4",
        out_dir=tmp_path,
        timescale=60000,
        auto_rename=False,
    )
    with pytest.raises(OutputFileExistsError) as exc_info:
        output_path_for(req)
    assert "already exists" in str(exc_info.value)


def test_parse_progress() -> None:
    assert _parse_progress("out_time_us=1000000", 2.0) == 0.5
    assert _parse_progress("progress=end", 2.0) == 1.0
    assert _parse_progress("frame=10", 2.0) is None
    assert _parse_progress("out_time_us=N/A", 2.0) is None


# ---------- verifier ----------


def test_verify_rejects_codec_change() -> None:
    a = _info()
    b = _info(codec="hevc", timescale=60000)
    with pytest.raises(VerifyError) as exc_info:
        verify(a, b, 60000)
    assert "codec changed" in str(exc_info.value)


def test_verify_rejects_audio_mismatch() -> None:
    a = _info(has_audio=True)
    b = _info(has_audio=False, timescale=60000)
    with pytest.raises(VerifyError) as exc_info:
        verify(a, b, 60000)
    assert "audio stream mismatch" in str(exc_info.value)


def test_verify_rejects_frame_count_mismatch() -> None:
    a = _info(nb_frames=60)
    b = _info(nb_frames=59, timescale=60000)
    with pytest.raises(VerifyError) as exc_info:
        verify(a, b, 60000)
    assert "frame count mismatch" in str(exc_info.value)


def test_verify_rejects_duration_exceeding_tolerance() -> None:
    a = _info(duration=10.0)
    b = _info(duration=10.25, timescale=60000)
    with pytest.raises(VerifyError) as exc_info:
        verify(a, b, 60000, duration_tolerance_s=0.1)
    assert "exceeds tolerance" in str(exc_info.value)


def test_verify_accepts_minor_duration_delta_with_warning() -> None:
    a = _info(duration=10.0)
    b = _info(duration=10.05, timescale=60000)
    warnings = verify(a, b, 60000, duration_tolerance_s=0.1)
    assert any("minor duration delta" in w for w in warnings)


def test_verify_dynamic_tolerance_default() -> None:
    a = _info(duration=200.0)
    # Default tolerance for 200s is max(0.1, 200 * 0.001) = 0.2s
    b_ok = _info(duration=200.15, timescale=60000)
    warnings = verify(a, b_ok, 60000)
    assert any("minor duration delta" in w for w in warnings)

    b_bad = _info(duration=200.25, timescale=60000)
    with pytest.raises(VerifyError) as exc_info:
        verify(a, b_bad, 60000)
    assert "exceeds tolerance" in str(exc_info.value)


# ---------- end-to-end ----------


@pytest.mark.parametrize("strategy", sorted(STRATEGIES))
@pytest.mark.parametrize("timescale", [60000, 120000])
def test_patch_end_to_end(
    clip30: Path, ff: FFmpegPaths, tmp_path: Path, strategy: str, timescale: int
) -> None:
    src_hash = _sha(clip30)
    events: list[object] = []
    req = PatchRequest(src=clip30, out_dir=tmp_path, timescale=timescale, strategy=strategy)
    result = patch(req, ff, events.append)

    assert result.output.is_file()
    assert not list(tmp_path.glob("*.part"))
    assert result.after.timescale == timescale
    assert result.after.codec == result.before.codec
    assert result.after.nb_frames == result.before.nb_frames
    assert abs(result.after.duration_s - result.before.duration_s) < 0.1
    assert _sha(clip30) == src_hash  # source untouched
    assert any(getattr(e, "level", "") == "OK" for e in events)


def test_patch_output_exists_error(clip30: Path, ff: FFmpegPaths, tmp_path: Path) -> None:
    existing = tmp_path / f"{clip30.stem}_ts60000{clip30.suffix}"
    existing.write_bytes(b"content")
    req = PatchRequest(
        src=clip30,
        out_dir=tmp_path,
        timescale=60000,
        overwrite=False,
        auto_rename=False,
    )
    with pytest.raises(OutputFileExistsError) as exc_info:
        patch(req, ff, lambda _: None)
    assert "already exists" in str(exc_info.value)


def test_patch_mov_and_noaudio(
    clip5994: Path, clip_noaudio: Path, ff: FFmpegPaths, tmp_path: Path
) -> None:
    # ffmpeg-copy preserves original container extension (.mov -> .mov, .mp4 -> .mp4)
    for src in (clip5994, clip_noaudio):
        r = patch(
            PatchRequest(src=src, out_dir=tmp_path, timescale=60000, strategy="ffmpeg-copy"),
            ff,
            lambda e: None,
        )
        assert r.output.suffix == src.suffix
        assert r.after.timescale == 60000

    # Default X1T strategy (x1t-mobile) normalizes .mov input to .mp4
    r_mov_x1t = patch(
        PatchRequest(src=clip5994, out_dir=tmp_path, timescale=60000, strategy="x1t-mobile"),
        ff,
        lambda e: None,
    )
    assert r_mov_x1t.output.suffix == ".mp4"
    assert r_mov_x1t.after.timescale == 60000


def test_patch_rejects_bad_ext(ff: FFmpegPaths, tmp_path: Path) -> None:
    bad = tmp_path / "x.avi"
    bad.write_bytes(b"0")
    with pytest.raises(PatchError):
        patch(PatchRequest(src=bad, out_dir=tmp_path, timescale=60000), ff, lambda e: None)


def test_patch_cancel_cleans_up(clip30: Path, ff: FFmpegPaths, tmp_path: Path) -> None:
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(PatchCancelledError):
        patch(
            PatchRequest(src=clip30, out_dir=tmp_path, timescale=60000), ff, lambda e: None, cancel
        )
    assert not list(tmp_path.glob("*.part"))


def test_stale_temp_cleanup_is_name_scoped_and_age_gated(tmp_path: Path) -> None:
    import os

    from fps_patcher.core.patcher import _cleanup_stale_temps

    final = tmp_path / "clip_ts60000.mp4"
    stale = tmp_path / ".clip_ts60000.old.mp4.part"
    fresh = tmp_path / ".clip_ts60000.new.mp4.part"
    foreign = tmp_path / "user_notes.part"
    for p in (stale, fresh, foreign):
        p.write_bytes(b"x")
    old = 1_700_000_000.0
    os.utime(stale, (old, old))
    os.utime(foreign, (old, old))

    assert _cleanup_stale_temps(final) == 1
    assert not stale.exists()
    assert fresh.exists() and foreign.exists()


def test_failed_patch_preserves_existing_output(
    clip30: Path, ff: FFmpegPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    final = tmp_path / f"{clip30.stem}_ts60000{clip30.suffix}"
    final.write_bytes(b"PREVIOUS-OUTPUT")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise VerifyError("forced verification failure")

    monkeypatch.setattr("fps_patcher.core.patcher.verify", boom)
    with pytest.raises(VerifyError):
        patch(
            PatchRequest(
                src=clip30,
                out_dir=tmp_path,
                timescale=60000,
                strategy="direct-atom",
                overwrite=True,
            ),
            ff,
            lambda _: None,
        )

    assert final.read_bytes() == b"PREVIOUS-OUTPUT"
    assert not list(tmp_path.glob("*.part"))
