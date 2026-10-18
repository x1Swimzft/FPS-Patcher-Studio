"""Tests for FFmpeg decoupling, probe_direct, capability model, and lossless verifiers."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from conftest import _make_clip

from fps_patcher.core.errors import FFmpegNotFoundError
from fps_patcher.core.ffmpeg_locator import FFmpegPaths
from fps_patcher.core.models import PatchRequest
from fps_patcher.core.patcher import patch
from fps_patcher.core.prober import probe, probe_direct
from fps_patcher.core.verifier import (
    verify_atom_structure,
    verify_offsets,
    verify_payload_integrity,
    verify_sample_tables,
)


def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, typ) + payload


def _full_box(typ: bytes, version: int, flags: int, payload: bytes) -> bytes:
    v_flags = ((version & 0xFF) << 24) | (flags & 0x00FFFFFF)
    return struct.pack(">I4sI", len(payload) + 12, typ, v_flags) + payload


def test_probe_direct_matches_real_clip(ff: FFmpegPaths, tmp_path: Path) -> None:
    src = tmp_path / "sample_probe.mp4"
    _make_clip(ff, src, "30", audio=True)

    info_direct = probe_direct(src)
    assert info_direct.path == src
    assert abs(info_direct.fps - 30.0) < 0.05
    assert info_direct.width == 320
    assert info_direct.height == 240
    assert info_direct.has_audio is True
    assert info_direct.timescale > 0

    # probe() with ffprobe=None should invoke probe_direct()
    info_fallback = probe(src, ffprobe=None)
    assert abs(info_fallback.fps - info_direct.fps) < 0.001


def test_direct_patch_without_ffmpeg(ff: FFmpegPaths, tmp_path: Path) -> None:
    src = tmp_path / "sample_src.mp4"
    _make_clip(ff, src, "30", audio=True)

    # 1. v4-forensic strategy with paths=None
    req_v4 = PatchRequest(
        src=src,
        out_dir=tmp_path / "out_v4",
        timescale=60000,
        strategy="v4-forensic",
    )
    res_v4 = patch(req_v4, paths=None, emit=lambda e: None)
    assert res_v4.output.is_file()
    assert res_v4.after.fps > 0

    # 2. bxd-experimental strategy with paths=None
    req_bxd = PatchRequest(
        src=src,
        out_dir=tmp_path / "out_bxd",
        timescale=60000,
        strategy="bxd-experimental",
    )
    res_bxd = patch(req_bxd, paths=None, emit=lambda e: None)
    assert res_bxd.output.is_file()

    # 3. direct-atom strategy with paths=None
    req_direct = PatchRequest(
        src=src,
        out_dir=tmp_path / "out_direct",
        timescale=60000,
        strategy="direct-atom",
    )
    res_direct = patch(req_direct, paths=None, emit=lambda e: None)
    assert res_direct.output.is_file()

    # 4. ffmpeg-copy strategy with paths=None MUST raise FFmpegNotFoundError
    req_ff = PatchRequest(
        src=src,
        out_dir=tmp_path / "out_ff",
        timescale=60000,
        strategy="ffmpeg-copy",
    )
    with pytest.raises(FFmpegNotFoundError):
        patch(req_ff, paths=None, emit=lambda e: None)


def test_verifier_atom_structure(tmp_path: Path) -> None:
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isom")
    mdat = _box(b"mdat", b"payload_bytes")
    mvhd = _full_box(b"mvhd", 0, 0, struct.pack(">IIII", 0, 0, 1000, 1000) + b"\x00" * 80)
    moov = _box(b"moov", mvhd)

    # Standard MP4 file
    std_file = tmp_path / "std.mp4"
    std_file.write_bytes(ftyp + moov + mdat)
    res_std = verify_atom_structure(std_file)
    assert res_std.status == "VALID"
    assert res_std.trailing_data_size == 0

    # Non-standard MP4 with trailing data (ghost bytes)
    ghost_file = tmp_path / "ghost.mp4"
    ghost_file.write_bytes(ftyp + moov + mdat + b"extra_ghost_padding")
    res_ghost = verify_atom_structure(ghost_file)
    assert res_ghost.status == "EXPERIMENTAL / NON-STANDARD"
    assert res_ghost.trailing_data_size == len(b"extra_ghost_padding")


def test_verifier_offsets_and_sample_tables(tmp_path: Path) -> None:
    # Build minimal valid trak components
    stts = _full_box(b"stts", 0, 0, struct.pack(">II", 1, 1000))
    stsz = _full_box(b"stsz", 0, 0, struct.pack(">III", 0, 1, 13))
    stsc = _full_box(b"stsc", 0, 0, struct.pack(">IIII", 1, 1, 1, 1))
    stsd = _full_box(b"stsd", 0, 0, struct.pack(">I", 0))
    hdlr = _full_box(b"hdlr", 0, 0, struct.pack(">4s4s12s", b"\x00" * 4, b"vide", b"\x00" * 12))
    mdhd = _full_box(b"mdhd", 0, 0, struct.pack(">IIIIHH", 0, 0, 1000, 1000, 0, 0))
    tkhd = _full_box(b"tkhd", 0, 0, b"\x00" * 80)
    mvhd = _full_box(b"mvhd", 0, 0, struct.pack(">IIII", 0, 0, 1000, 1000) + b"\x00" * 80)
    mdat = _box(b"mdat", b"SAMPLE_PAYLOAD")
    ftyp = _box(b"ftyp", b"isom\x00\x00\x02\x00isom")

    # Measure moov size with dummy stco
    dummy_stco = _full_box(b"stco", 0, 0, struct.pack(">II", 1, 0))
    stbl_dummy = _box(b"stbl", stsd + stts + stsz + stsc + dummy_stco)
    minf_dummy = _box(b"minf", stbl_dummy)
    mdia_dummy = _box(b"mdia", mdhd + hdlr + minf_dummy)
    trak_dummy = _box(b"trak", tkhd + mdia_dummy)
    moov_dummy = _box(b"moov", mvhd + trak_dummy)

    # Offset pointing directly to the sample data inside mdat (after 8-byte mdat header)
    valid_offset = len(ftyp) + len(moov_dummy) + 8
    stco = _full_box(b"stco", 0, 0, struct.pack(">II", 1, valid_offset))
    stbl = _box(b"stbl", stsd + stts + stsz + stsc + stco)
    minf = _box(b"minf", stbl)
    mdia = _box(b"mdia", mdhd + hdlr + minf)
    trak = _box(b"trak", tkhd + mdia)
    moov = _box(b"moov", mvhd + trak)

    valid_file = tmp_path / "valid.mp4"
    valid_file.write_bytes(ftyp + moov + mdat)

    ok_tables, _ = verify_sample_tables(valid_file)
    assert ok_tables is True

    ok_offsets, problems = verify_offsets(valid_file)
    assert ok_offsets is True
    assert len(problems) == 0

    # Negative test: stco points to offset 16 (inside moov header, outside mdat)
    bad_stco = _full_box(b"stco", 0, 0, struct.pack(">II", 1, 16))
    bad_stbl = _box(b"stbl", stsd + stts + stsz + stsc + bad_stco)
    bad_minf = _box(b"minf", bad_stbl)
    bad_mdia = _box(b"mdia", mdhd + hdlr + bad_minf)
    bad_trak = _box(b"trak", tkhd + bad_mdia)
    bad_moov = _box(b"moov", mvhd + bad_trak)

    bad_file = tmp_path / "bad_offset.mp4"
    bad_file.write_bytes(ftyp + bad_moov + mdat)

    bad_offsets, bad_problems = verify_offsets(bad_file)
    assert bad_offsets is False
    assert any("outside mdat" in p for p in bad_problems)


def test_verify_payload_integrity(ff: FFmpegPaths, tmp_path: Path) -> None:
    src = tmp_path / "orig.mp4"
    _make_clip(ff, src, "30", audio=True)

    # Comparing same file must yield PASS tags
    report = verify_payload_integrity(src, src)
    assert report["atom structure"] == "PASS"
    assert report["mdat payload"] == "PASS"
    assert report["video payload"] == "PASS"
