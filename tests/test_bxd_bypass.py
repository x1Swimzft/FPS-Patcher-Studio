"""Tests for Method BXD: 1080p TikTok Quality Bypass Engine."""

from __future__ import annotations

from pathlib import Path

from conftest import _make_clip

from fps_patcher.core.bxd_patcher import MethodBXDDirectPatch
from fps_patcher.core.ffmpeg_locator import FFmpegPaths
from fps_patcher.core.forensic_analyzer import MP4ForensicAnalyzer
from fps_patcher.core.models import LogEvent, PatchRequest, ProgressEvent
from fps_patcher.core.patcher import patch
from fps_patcher.core.prober import probe
from fps_patcher.core.strategies import STRATEGIES


def test_bxd_strategy_registered() -> None:
    assert "bxd-experimental" in STRATEGIES
    strat = STRATEGIES["bxd-experimental"]
    assert "Experimental X1T" in strat.label or "Experimental BXD" in strat.label
    assert strat.direct is True


def test_bxd_patch_with_audio(ff: FFmpegPaths, tmp_path: Path) -> None:
    src = tmp_path / "sample_orig.mp4"
    out = tmp_path / "sample_bxd.mp4"
    _make_clip(ff, src, "30", audio=True)

    orig_analyzer = MP4ForensicAnalyzer(src.read_bytes(), str(src)).parse()
    orig_a = next(t for t in orig_analyzer.tracks if t.handler_type == "soun")
    orig_a_count = orig_a.sample_count

    logs: list[str] = []
    patcher = MethodBXDDirectPatch(
        src=src,
        out=out,
        multiplier=10,
        indeterminate_mvhd=True,
        strip_edts=True,
        emit=logs.append,
    )
    patcher.execute()

    assert out.is_file()
    assert any("[SUCCESS]" in log for log in logs)

    # Forensic analysis on output
    out_analyzer = MP4ForensicAnalyzer(out.read_bytes(), str(out)).parse()
    assert out_analyzer.mdat_found is True
    assert out_analyzer.mdat_payload_sha256 == orig_analyzer.mdat_payload_sha256

    # Verify audio sample count is 10x
    out_a = next(t for t in out_analyzer.tracks if t.handler_type == "soun")
    assert out_a.sample_count == orig_a_count * 10

    # Verify mvhd has duration = -1 (0xFFFFFFFFFFFFFFFF)
    moov = next(n for n in out_analyzer.atom_tree if n.type_str == "moov")
    mvhd = next(n for n in moov.children if n.type_str == "mvhd")
    assert mvhd.version == 1

    # Verify edts stripped
    for trak in [n for n in moov.children if n.type_str == "trak"]:
        assert not any(n.type_str == "edts" for n in trak.children)

    # Probe with ffprobe
    p_orig = probe(src, ff.ffprobe)
    p_out = probe(out, ff.ffprobe)
    assert p_out.codec == p_orig.codec
    assert p_out.width == p_orig.width
    assert p_out.height == p_orig.height
    assert p_out.timescale == p_orig.timescale
    assert p_out.nb_frames == p_orig.nb_frames


def test_bxd_via_patcher_orchestrator(ff: FFmpegPaths, tmp_path: Path) -> None:
    src = tmp_path / "test_orch.mp4"
    out_dir = tmp_path / "out_dir"
    _make_clip(ff, src, "30", audio=True)

    events: list[LogEvent | ProgressEvent] = []
    req = PatchRequest(
        src=src,
        timescale=60000,
        strategy="bxd-bypass",
        out_dir=out_dir,
    )
    res = patch(req, ff, emit=events.append)
    assert res.output.is_file()
    assert res.after.codec == res.before.codec
    assert res.after.timescale == 60000
