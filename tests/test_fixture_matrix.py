"""Comprehensive Fixture Matrix Test for Method V4 Forensic Analyzer and Patcher.

Generates real MP4s with ffmpeg/ffprobe and synthetic ISO boxes covering:
1. H.264 with AAC audio
2. H.264 without audio
3. HEVC (H.265) video
4. B-frames (ctts atom present)
5. Edit lists (edts/elst present)
6. Variable Frame Rate (VFR)
7. 64-bit chunk offsets (co64)
8. Compact sample size table (stz2)
9. Version 1 headers (64-bit timestamps in mvhd/mdhd)
10. Multiple mdat boxes
11. Truncated/corrupted file

For each fixture, Method V4 is executed, recording:
- ffprobe before & after (where valid)
- forensic before & after JSON
- forensic diff report
- strict verifier result
- SHA-256 hash of mdat payload & mapped track samples
Unsupported layouts are cleanly rejected leaving inputs untouched.
"""

from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path

import pytest

from fps_patcher.core.errors import PatchError
from fps_patcher.core.ffmpeg_locator import FFmpegPaths
from fps_patcher.core.forensic_analyzer import (
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


def test_fixture_matrix_full_audit(ff: FFmpegPaths, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "matrix_artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------
    # Fixture 1: H.264 with AAC audio
    # -------------------------------------------------------------
    f1_src = tmp_path / "01_h264_aac.mp4"
    f1_out = tmp_path / "01_h264_aac_patched.mp4"
    subprocess.run(
        [
            str(ff.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(f1_src),
        ],
        check=True,
    )
    _run_and_verify_v4(f1_src, f1_out, 60000, artifacts_dir / "01_h264_aac", ff)

    # -------------------------------------------------------------
    # Fixture 2: H.264 without audio
    # -------------------------------------------------------------
    f2_src = tmp_path / "02_h264_noaudio.mp4"
    f2_out = tmp_path / "02_h264_noaudio_patched.mp4"
    subprocess.run(
        [
            str(ff.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-an", str(f2_src),
        ],
        check=True,
    )
    _run_and_verify_v4(f2_src, f2_out, 60000, artifacts_dir / "02_h264_noaudio", ff)

    # -------------------------------------------------------------
    # Fixture 3: HEVC (H.265) video
    # -------------------------------------------------------------
    f3_src = tmp_path / "03_hevc.mp4"
    f3_out = tmp_path / "03_hevc_patched.mp4"
    subprocess.run(
        [
            str(ff.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1",
            "-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-an", str(f3_src),
        ],
        check=True,
    )
    _run_and_verify_v4(f3_src, f3_out, 60000, artifacts_dir / "03_hevc", ff)

    # -------------------------------------------------------------
    # Fixture 4: B-frames (ctts atom present)
    # -------------------------------------------------------------
    f4_src = tmp_path / "04_bframes.mp4"
    f4_out = tmp_path / "04_bframes_patched.mp4"
    subprocess.run(
        [
            str(ff.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-bf", "2", "-g", "15",
            "-an", str(f4_src),
        ],
        check=True,
    )
    _run_and_verify_v4(f4_src, f4_out, 60000, artifacts_dir / "04_bframes", ff)

    # -------------------------------------------------------------
    # Fixture 5: Edit list (edts/elst present)
    # -------------------------------------------------------------
    f5_src = tmp_path / "05_editlist.mp4"
    f5_out = tmp_path / "05_editlist_patched.mp4"
    # Delay audio or use -ss on input to create edit list (elst)
    subprocess.run(
        [
            str(ff.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-ss", "0.1",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1.5",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=1.5",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-t", "1", str(f5_src),
        ],
        check=True,
    )
    _run_and_verify_v4(f5_src, f5_out, 60000, artifacts_dir / "05_editlist", ff)

    # -------------------------------------------------------------
    # Fixture 6: Variable Frame Rate (VFR)
    # -------------------------------------------------------------
    f6_src = tmp_path / "06_vfr.mp4"
    f6_out = tmp_path / "06_vfr_patched.mp4"
    subprocess.run(
        [
            str(ff.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1",
            "-vf", "mpdecimate",
            "-fps_mode", "vfr",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-an", str(f6_src),
        ],
        check=True,
    )
    _run_and_verify_v4(f6_src, f6_out, 60000, artifacts_dir / "06_vfr", ff)

    # -------------------------------------------------------------
    # Fixture 7: 64-bit chunk offsets (co64)
    # -------------------------------------------------------------
    f7_src = tmp_path / "07_co64.mp4"
    f7_out = tmp_path / "07_co64_patched.mp4"
    _make_synthetic_clip(f7_src, chunk_offset_box=b"co64")
    _run_and_verify_v4(f7_src, f7_out, 60000, artifacts_dir / "07_co64", ff=None)

    # -------------------------------------------------------------
    # Fixture 8: Compact sample size table (stz2)
    # -------------------------------------------------------------
    f8_src = tmp_path / "08_stz2.mp4"
    f8_out = tmp_path / "08_stz2_patched.mp4"
    _make_synthetic_clip(f8_src, sample_size_box=b"stz2")
    _run_and_verify_v4(f8_src, f8_out, 60000, artifacts_dir / "08_stz2", ff=None)

    # -------------------------------------------------------------
    # Fixture 9: Version 1 headers (64-bit timestamps in mvhd & mdhd)
    # -------------------------------------------------------------
    f9_src = tmp_path / "09_version1_headers.mp4"
    f9_out = tmp_path / "09_version1_headers_patched.mp4"
    _make_synthetic_clip(f9_src, header_version=1)
    _run_and_verify_v4(f9_src, f9_out, 60000, artifacts_dir / "09_version1_headers", ff=None)

    # -------------------------------------------------------------
    # Fixture 10: Multiple mdat boxes
    # -------------------------------------------------------------
    f10_src = tmp_path / "10_multiple_mdat.mp4"
    f10_out = tmp_path / "10_multiple_mdat_patched.mp4"
    _make_synthetic_clip(f10_src, multiple_mdat=True)
    _run_and_verify_v4(f10_src, f10_out, 60000, artifacts_dir / "10_multiple_mdat", ff=None)

    # -------------------------------------------------------------
    # Fixture 11: Truncated / Corrupt MP4 (Must be cleanly rejected)
    # -------------------------------------------------------------
    f11_src = tmp_path / "11_corrupt.mp4"
    f11_src.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 4)  # truncated
    f11_out = tmp_path / "11_corrupt_patched.mp4"
    orig_content = f11_src.read_bytes()

    patcher_corrupt = MethodV4DirectPatch(src=f11_src, out=f11_out, target_timescale=60000)
    with pytest.raises((PatchError, Exception)):
        patcher_corrupt.execute()

    # Input must remain completely untouched, output must not exist
    assert f11_src.read_bytes() == orig_content
    assert not f11_out.exists()


def _run_and_verify_v4(
    src: Path,
    out: Path,
    target_timescale: int,
    art_dir: Path,
    ff: FFmpegPaths | None = None,
) -> None:
    art_dir.mkdir(parents=True, exist_ok=True)

    # ffprobe before
    if ff is not None:
        p_before = probe(src, ff.ffprobe)
        (art_dir / "ffprobe_before.json").write_text(
            json.dumps(p_before.__dict__, indent=2, default=str)
        )

    orig_bytes = src.read_bytes()
    orig_analyzer = MP4ForensicAnalyzer(orig_bytes, str(src))
    orig_report = orig_analyzer.parse()
    (art_dir / "forensic_before.json").write_text(
        json.dumps(orig_report.to_dict(), indent=2, default=str)
    )

    patcher = MethodV4DirectPatch(
        src=src,
        out=out,
        target_timescale=target_timescale,
        strict_lossless=True,
        preserve_video=True,
        preserve_audio=True,
    )
    patcher.execute()
    assert out.is_file()

    # ffprobe after
    if ff is not None:
        p_after = probe(out, ff.ffprobe)
        (art_dir / "ffprobe_after.json").write_text(
            json.dumps(p_after.__dict__, indent=2, default=str)
        )
        assert p_after.timescale == target_timescale

    # forensic after
    patched_bytes = out.read_bytes()
    patch_analyzer = MP4ForensicAnalyzer(patched_bytes, str(out))
    patch_report = patch_analyzer.parse()
    (art_dir / "forensic_after.json").write_text(
        json.dumps(patch_report.to_dict(), indent=2, default=str)
    )

    # Diff artifacts
    diff = compare_mp4_files(src, out)
    export_diff_artifacts(diff, art_dir / "diff")

    # Strict verifier checks
    assert orig_report.mdat_payload_sha256 == patch_report.mdat_payload_sha256

    orig_v = next((t for t in orig_report.tracks if t.handler_type == "vide"), None)
    patch_v = next((t for t in patch_report.tracks if t.handler_type == "vide"), None)
    assert orig_v is not None and patch_v is not None
    assert orig_v.sample_payload_sha256 == patch_v.sample_payload_sha256
    assert patch_v.timescale == target_timescale

    orig_a = next((t for t in orig_report.tracks if t.handler_type == "soun"), None)
    patch_a = next((t for t in patch_report.tracks if t.handler_type == "soun"), None)
    if orig_a is not None and patch_a is not None:
        assert orig_a.sample_payload_sha256 == patch_a.sample_payload_sha256


def _make_synthetic_clip(
    target: Path,
    chunk_offset_box: bytes = b"stco",
    sample_size_box: bytes = b"stsz",
    header_version: int = 0,
    multiple_mdat: bool = False,
) -> None:
    # 2 samples of 8 bytes = 16 bytes total payload
    sample_data = b"SAMPLE_PAYLOAD_0SAMPLE_PAYLOAD_1"

    # stts: 2 samples, delta 512
    stts = _full_box(b"stts", 0, 0, struct.pack(">III", 1, 2, 512))

    # sample size table
    if sample_size_box == b"stz2":
        # 8-bit field size, 2 entries of 16 bytes each
        stsz = _full_box(b"stz2", 0, 0, struct.pack(">IBI", 0, 8, 2) + bytes([16, 16]))
    else:
        stsz = _full_box(b"stsz", 0, 0, struct.pack(">IIII", 0, 2, 16, 16))

    # chunk offset table
    if chunk_offset_box == b"co64":
        stco = _full_box(b"co64", 0, 0, struct.pack(">IIQ", 0, 1, 0))
    else:
        stco = _full_box(b"stco", 0, 0, struct.pack(">III", 0, 1, 0))

    stsc = _full_box(b"stsc", 0, 0, struct.pack(">IIII", 0, 1, 2, 1))

    stbl = _box(b"stbl", stts + stsz + stsc + stco)
    minf = _box(b"minf", stbl)
    hdlr = _full_box(b"hdlr", 0, 0, struct.pack(">4s4s12s", b"\x00" * 4, b"vide", b"\x00" * 12))

    if header_version == 1:
        # version 1 mdhd: 64-bit creation/mod times, 32-bit timescale,
        # 64-bit duration, 16-bit language, 16-bit quality
        mdhd = _full_box(
            b"mdhd",
            1,
            0,
            struct.pack(">QQIQHH", 0, 0, 1000, 1024, 0, 0),
        )
    else:
        mdhd = _full_box(
            b"mdhd",
            0,
            0,
            struct.pack(">IIIIHH", 0, 0, 1000, 1024, 0, 0),
        )

    mdia = _box(b"mdia", mdhd + hdlr + minf)
    tkhd = _full_box(b"tkhd", 0, 0, b"\x00" * 80)
    trak = _box(b"trak", tkhd + mdia)

    if header_version == 1:
        mvhd = _full_box(
            b"mvhd",
            1,
            0,
            struct.pack(">QQIQ", 0, 0, 1000, 1024) + b"\x00" * 80,
        )
    else:
        mvhd = _full_box(
            b"mvhd",
            0,
            0,
            struct.pack(">IIII", 0, 0, 1000, 1024) + b"\x00" * 80,
        )

    moov = _box(b"moov", mvhd + trak)
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2")

    if multiple_mdat:
        mdat1 = _box(b"mdat", sample_data[:16])
        mdat2 = _box(b"mdat", sample_data[16:])
        content = ftyp + moov + mdat1 + mdat2
    else:
        mdat = _box(b"mdat", sample_data)
        content = ftyp + moov + mdat

    target.write_bytes(content)
