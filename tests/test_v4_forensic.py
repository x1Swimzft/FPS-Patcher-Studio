"""Comprehensive tests for Method V4 Forensic Analyzer and Direct Lossless Patcher."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from conftest import _make_clip

from fps_patcher.core.errors import PatchError
from fps_patcher.core.ffmpeg_locator import FFmpegPaths
from fps_patcher.core.forensic_analyzer import (
    ForensicParseError,
    MP4ForensicAnalyzer,
    compare_mp4_files,
    export_diff_artifacts,
)
from fps_patcher.core.prober import probe
from fps_patcher.core.v4_patcher import MethodV4DirectPatch


def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, typ) + payload


def _full_box(typ: bytes, version: int, flags: int, payload: bytes) -> bytes:
    v_flags = ((version & 0xFF) << 24) | (flags & 0x00FFFFFF)
    return struct.pack(">I4sI", len(payload) + 12, typ, v_flags) + payload


def test_v4_real_clip_forensic_analysis_and_export(ff: FFmpegPaths, tmp_path: Path) -> None:
    src = tmp_path / "original.mp4"
    out = tmp_path / "v4-output.mp4"
    _make_clip(ff, src, "30", audio=True)

    # 1. Parse forensic baseline
    orig_bytes = src.read_bytes()
    orig_analyzer = MP4ForensicAnalyzer(orig_bytes, str(src))
    orig_rep = orig_analyzer.parse()
    assert orig_rep.mdat_found is True
    assert orig_rep.mdat_size > 0
    assert len(orig_rep.tracks) == 2  # video + audio

    # 2. Apply Method V4 Direct Patch
    logs: list[str] = []
    patcher = MethodV4DirectPatch(
        src=src,
        out=out,
        target_timescale=60000,
        sync_mvhd=False,
        strict_lossless=True,
        preserve_video=True,
        preserve_audio=True,
        export_report=True,
        emit=logs.append,
    )
    patcher.execute()
    assert out.is_file()

    # Verify structured logs format
    assert any("[INIT]" in log for log in logs)
    assert any("[READ]" in log for log in logs)
    assert any("[PARSE]" in log for log in logs)
    assert any("[ANALYZE]" in log for log in logs)
    assert any("[PATCH] mdhd.timescale" in log for log in logs)
    assert any("[VERIFY] mdat hash" in log for log in logs)
    assert any("[VERIFY] video payload" in log for log in logs)
    assert any("[VERIFY] audio payload" in log for log in logs)
    assert any("[SUCCESS]" in log for log in logs)

    # 3. Probe with real ffprobe
    before_probe = probe(src, ff.ffprobe)
    after_probe = probe(out, ff.ffprobe)
    assert after_probe.timescale == 60000
    assert after_probe.codec == before_probe.codec
    assert after_probe.width == before_probe.width
    assert after_probe.height == before_probe.height
    assert after_probe.nb_frames == before_probe.nb_frames
    assert abs(after_probe.duration_s - before_probe.duration_s) < 0.1

    # 4. Compare via Forensic Diff
    diff_res = compare_mp4_files(src, out)
    assert diff_res.mdat_match is True
    assert diff_res.video_payload_match is True
    assert diff_res.audio_payload_match is True
    assert any("mdhd" in atom for atom in diff_res.changed_atoms)

    # 5. Export JSON diff artifacts
    report_dir = tmp_path / "artifacts"
    export_diff_artifacts(diff_res, report_dir)
    assert (report_dir / "before.json").is_file()
    assert (report_dir / "after.json").is_file()
    assert (report_dir / "diff.json").is_file()

    diff_data = json.loads((report_dir / "diff.json").read_text(encoding="utf-8"))
    assert diff_data["mdatChanged"] is False
    assert diff_data["videoPayloadChanged"] is False
    assert diff_data["audioPayloadChanged"] is False
    assert len(diff_data["changedAtoms"]) > 0


def test_v4_dry_run_does_not_write_file(ff: FFmpegPaths, tmp_path: Path) -> None:
    src = tmp_path / "test_dry.mp4"
    out = tmp_path / "should_not_exist.mp4"
    _make_clip(ff, src, "30", audio=False)

    logs: list[str] = []
    patcher = MethodV4DirectPatch(
        src=src,
        out=out,
        target_timescale=120000,
        dry_run=True,
        emit=logs.append,
    )
    patcher.execute()

    assert not out.exists()
    assert any("[DRY RUN]" in log for log in logs)


def test_synthetic_constant_and_variable_stsz(tmp_path: Path) -> None:
    sample_payload = b"FAKE_VIDEO_PAYLOAD_CHUNK_1234"

    # Constant stsz (sample_size = 5, sample_count = 6)
    stsz_const = _full_box(b"stsz", 0, 0, struct.pack(">II", 5, 6))
    stco = _full_box(b"stco", 0, 0, struct.pack(">II", 1, 0))  # 1 chunk offset 0
    stsc = _full_box(b"stsc", 0, 0, struct.pack(">IIII", 1, 1, 6, 1))

    stbl = _box(b"stbl", stsz_const + stco + stsc)
    minf = _box(b"minf", stbl)
    hdlr = _full_box(b"hdlr", 0, 0, struct.pack(">4s4s12s", b"\x00" * 4, b"vide", b"\x00" * 12))
    mdhd = _full_box(b"mdhd", 0, 0, struct.pack(">IIIIHH", 0, 0, 1000, 3000, 0, 0))
    mdia = _box(b"mdia", mdhd + hdlr + minf)
    tkhd = _full_box(b"tkhd", 0, 0, b"\x00" * 80)
    trak = _box(b"trak", tkhd + mdia)
    mvhd = _full_box(b"mvhd", 0, 0, struct.pack(">IIII", 0, 0, 1000, 3000) + b"\x00" * 80)
    moov = _box(b"moov", mvhd + trak)
    mdat = _box(b"mdat", sample_payload)
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2")

    fake_mp4 = ftyp + moov + mdat
    analyzer = MP4ForensicAnalyzer(fake_mp4)
    rep = analyzer.parse()
    assert rep.mdat_found is True
    assert len(rep.tracks) == 1
    assert rep.tracks[0].sample_count == 6

    # Variable stsz (sample_size = 0, table of 3 sizes: [10, 10, 10])
    stsz_var = _full_box(b"stsz", 0, 0, struct.pack(">II", 0, 3) + struct.pack(">3I", 10, 10, 10))
    stbl_var = _box(b"stbl", stsz_var + stco + stsc)
    minf_var = _box(b"minf", stbl_var)
    mdia_var = _box(b"mdia", mdhd + hdlr + minf_var)
    trak_var = _box(b"trak", tkhd + mdia_var)
    moov_var = _box(b"moov", mvhd + trak_var)
    fake_mp4_var = ftyp + moov_var + mdat

    analyzer_var = MP4ForensicAnalyzer(fake_mp4_var)
    rep_var = analyzer_var.parse()
    assert rep_var.tracks[0].sample_count == 3


def test_synthetic_co64_and_ctts_elst(tmp_path: Path) -> None:
    # 64-bit chunk offsets (co64)
    co64 = _full_box(b"co64", 0, 0, struct.pack(">IQ", 1, 1024))
    # Composition time offsets (ctts)
    ctts = _full_box(b"ctts", 0, 0, struct.pack(">III", 1, 10, 50))
    # Edit list (elst)
    elst = _full_box(b"elst", 0, 0, struct.pack(">IIii", 1, 1000, 0, 1))
    edts = _box(b"edts", elst)

    stsz = _full_box(b"stsz", 0, 0, struct.pack(">II", 10, 1))
    stsc = _full_box(b"stsc", 0, 0, struct.pack(">IIII", 1, 1, 1, 1))
    stts = _full_box(b"stts", 0, 0, struct.pack(">III", 1, 10, 100))
    stbl = _box(b"stbl", stsz + co64 + stsc + ctts + stts)
    minf = _box(b"minf", stbl)
    hdlr = _full_box(b"hdlr", 0, 0, struct.pack(">4s4s12s", b"\x00" * 4, b"vide", b"\x00" * 12))
    mdhd = _full_box(b"mdhd", 0, 0, struct.pack(">IIIIHH", 0, 0, 1000, 1000, 0, 0))
    mdia = _box(b"mdia", mdhd + hdlr + minf)
    tkhd = _full_box(b"tkhd", 0, 0, b"\x00" * 80)
    trak = _box(b"trak", tkhd + edts + mdia)
    mvhd = _full_box(b"mvhd", 0, 0, struct.pack(">IIII", 0, 0, 1000, 1000) + b"\x00" * 80)
    moov = _box(b"moov", mvhd + trak)
    mdat = _box(b"mdat", b"SAMPLE_PAYLOAD_TEST")
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2")

    fake_mp4 = ftyp + moov + mdat
    analyzer = MP4ForensicAnalyzer(fake_mp4)
    rep = analyzer.parse()
    assert len(rep.tracks) == 1
    t = rep.tracks[0]
    assert len(t.ctts_entries) == 1
    assert len(t.elst_entries) == 1


def test_malformed_and_fragmented_boxes_rejected(tmp_path: Path) -> None:
    # 1. Truncated box header
    with pytest.raises(ForensicParseError):
        MP4ForensicAnalyzer(b"\x00\x00\x00\x04").parse()

    # 2. Fragmented MP4 with moof box rejected by patcher
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2")
    moov = _box(b"moov", b"\x00" * 20)
    moof = _box(b"moof", b"\x00" * 20)
    mdat = _box(b"mdat", b"\x00" * 20)

    bad_mp4 = tmp_path / "fragmented.mp4"
    bad_mp4.write_bytes(ftyp + moov + moof + mdat)

    out = tmp_path / "out.mp4"
    patcher = MethodV4DirectPatch(src=bad_mp4, out=out, target_timescale=60000)
    with pytest.raises(PatchError, match="Fragmented MP4"):
        patcher.execute()


def test_v4_ctts_version0_signed_offsets(tmp_path: Path) -> None:
    """QuickTime MOV writes ctts version 0 with two's complement signed offsets."""
    # ctts version 0 with 2 runs: offset +512, offset -256 (0xFFFFFF00)
    ctts = _full_box(
        b"ctts",
        0,
        0,
        struct.pack(">IIiIi", 2, 1, 512, 1, -256),
    )
    stsz = _full_box(b"stsz", 0, 0, struct.pack(">IIII", 0, 2, 8, 8))
    stco = _full_box(b"stco", 0, 0, struct.pack(">II", 1, 0))
    stsc = _full_box(b"stsc", 0, 0, struct.pack(">IIII", 1, 1, 2, 1))
    stts = _full_box(b"stts", 0, 0, struct.pack(">III", 1, 2, 512))
    stbl = _box(b"stbl", stsz + stco + stsc + ctts + stts)
    minf = _box(b"minf", stbl)
    hdlr = _full_box(b"hdlr", 0, 0, struct.pack(">4s4s12s", b"\x00" * 4, b"vide", b"\x00" * 12))
    mdhd = _full_box(b"mdhd", 0, 0, struct.pack(">IIIIHH", 0, 0, 1000, 1024, 0, 0))
    mdia = _box(b"mdia", mdhd + hdlr + minf)
    tkhd = _full_box(b"tkhd", 0, 0, b"\x00" * 80)
    trak = _box(b"trak", tkhd + mdia)
    mvhd = _full_box(b"mvhd", 0, 0, struct.pack(">IIII", 0, 0, 1000, 1024) + b"\x00" * 80)
    moov = _box(b"moov", mvhd + trak)
    mdat = _box(b"mdat", b"16_BYTES_PAYLOAD_")
    ftyp = _box(b"ftyp", b"qt  " + struct.pack(">I", 512) + b"qt  ")

    src = tmp_path / "quicktime_sample.mov"
    out = tmp_path / "quicktime_patched.mov"
    src.write_bytes(ftyp + moov + mdat)

    patcher = MethodV4DirectPatch(
        src=src,
        out=out,
        target_timescale=2000,
    )
    patcher.execute()

    assert out.is_file()
    analyzer = MP4ForensicAnalyzer(out.read_bytes())
    rep = analyzer.parse()
    assert rep.mdat_found is True
    assert len(rep.tracks) == 1
    t = rep.tracks[0]
    assert t.timescale == 2000
    assert len(t.ctts_entries) == 2
    # 512 * 2 = 1024, -256 * 2 = -512
    assert t.ctts_entries[0] == (1, 1024)
    assert t.ctts_entries[1] == (1, -512)


def test_v4_memory_guard_and_same_path(tmp_path: Path) -> None:
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"data" * 10)
    out = tmp_path / "out.mp4"

    # Same path refusal
    patcher_same = MethodV4DirectPatch(src=src, out=src, target_timescale=60000)
    with pytest.raises(PatchError, match="Refusing to patch in-place"):
        patcher_same.execute()

    # Memory guard
    patcher_limit = MethodV4DirectPatch(
        src=src,
        out=out,
        target_timescale=60000,
        max_file_size=20,  # file is 40 bytes
    )
    with pytest.raises(PatchError, match="exceeds memory safety limit"):
        patcher_limit.execute()
