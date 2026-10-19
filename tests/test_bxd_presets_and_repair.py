"""Tests for BXD Presets, Phase 0 H1-H4, Repair Engine, and Diagnostic Logger."""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import pytest
from conftest import _make_clip

from fps_patcher.app.queue_model import InputQueue
from fps_patcher.config import Settings
from fps_patcher.core.bxd_patcher import (
    PADDING_NAL,
    MethodBXDDirectPatch,
    generate_isolation_variants,
    repair_for_mobile,
)
from fps_patcher.core.diagnostic_logger import (
    MAX_AUTO_LOGS,
    auto_save_diagnostic_log,
    build_diagnostic_report,
    export_diagnostic_log,
    format_diagnostic_text,
    mask_sensitive_text,
    summarize_int_list,
)
from fps_patcher.core.errors import PatchError
from fps_patcher.core.ffmpeg_locator import FFmpegPaths
from fps_patcher.core.forensic_analyzer import MP4ForensicAnalyzer
from fps_patcher.core.models import PatchRequest
from fps_patcher.core.patcher import patch
from fps_patcher.core.strategies import UI_PRESETS, migrate_strategy_name
from fps_patcher.core.verifier import (
    verify_atom_structure,
    verify_mobile_compatibility,
    verify_offsets,
    verify_payload_integrity,
    verify_sample_tables,
)


def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, typ) + payload


def _largesize_box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4sQ", 1, typ, len(payload) + 16) + payload


def _full_box(typ: bytes, version: int, flags: int, payload: bytes) -> bytes:
    v_flags = ((version & 0xFF) << 24) | (flags & 0x00FFFFFF)
    return struct.pack(">I4sI", len(payload) + 12, typ, v_flags) + payload


def _ffmpeg_decode_check(ff: FFmpegPaths, target: Path) -> tuple[int, str]:
    """Run external ffmpeg decode check (-v error -i target -f null -)."""
    proc = subprocess.run(
        [str(ff.ffmpeg), "-v", "error", "-i", str(target), "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stderr.strip()


def test_ui_presets_and_strategy_migration(tmp_path: Path) -> None:
    # UI_PRESETS must only expose the 4 BXD presets
    assert set(UI_PRESETS.keys()) == {"bxd-pc", "bxd-mobile", "bxd-hybrid", "bxd-clean"}
    assert UI_PRESETS["bxd-pc"].label in ("X1T For PC", "Bxd For PC")
    assert UI_PRESETS["bxd-mobile"].label in ("X1T For Mobile", "Bxd For Mobile")
    assert UI_PRESETS["x1t-pc"].label == "X1T For PC"
    assert UI_PRESETS["x1t-mobile"].label == "X1T For Mobile"

    # Legacy strategy names migrate cleanly
    assert migrate_strategy_name("bxd-experimental") == ("bxd-pc", "bxd-experimental")
    assert migrate_strategy_name("bxd-bypass") == ("bxd-pc", "bxd-bypass")
    assert migrate_strategy_name("x1t-pc") == ("bxd-pc", None)
    assert migrate_strategy_name("x1t-mobile") == ("bxd-mobile", None)
    assert migrate_strategy_name("direct-atom") == ("bxd-clean", "direct-atom")
    assert migrate_strategy_name("v4-forensic") == ("bxd-clean", "v4-forensic")
    assert migrate_strategy_name("ffmpeg-copy") == ("bxd-clean", "ffmpeg-copy")
    assert migrate_strategy_name("unknown-xyz") == ("bxd-mobile", "unknown-xyz")
    assert migrate_strategy_name("bxd-mobile") == ("bxd-mobile", None)

    # Settings._clamp migrates legacy strategy and records migrated_strategy_from
    s = Settings(strategy="ffmpeg-copy")
    s._clamp()
    assert s.strategy == "bxd-clean"
    assert s.migrated_strategy_from == "ffmpeg-copy"

    # InputQueue.load with migrate_legacy=True migrates per-item overrides
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"\x00" * 32)
    q_file = tmp_path / "queue.json"
    q = InputQueue()
    q.add([vid])
    q.set_override(vid, timescale=60000, strategy="v4-forensic")
    q.save(q_file)

    loaded = InputQueue.load(q_file, migrate_legacy=True)
    item = loaded.get(vid)
    assert item is not None
    assert item.strategy == "bxd-clean"
    assert len(loaded.migrated_overrides) == 1


def test_phase0_isolation_variants_h1_to_h4(ff: FFmpegPaths, tmp_path: Path) -> None:
    src = tmp_path / "src_h.mp4"
    _make_clip(ff, src, "30", audio=True)

    variants = generate_isolation_variants(src, tmp_path / "variants", target_timescale=60000)
    assert set(variants.keys()) == {"H1", "H2", "H3", "H4"}
    for key, p in variants.items():
        assert p.is_file(), f"Variant {key} was not created"

    # H1: indeterminate mvhd only -> valid TikTok bypass header
    rep_h1 = verify_mobile_compatibility(variants["H1"])
    assert rep_h1.mvhd_duration_defined is True
    assert rep_h1.structure_ok is True
    assert any("indeterminate" in w.lower() for w in rep_h1.warnings)

    # H2: 10x stts/stsz inside mdat -> fails audio_duration_consistent (10x audio duration)
    rep_h2 = verify_mobile_compatibility(variants["H2"])
    assert rep_h2.chunk_offsets_ok is True
    assert rep_h2.audio_duration_consistent is False
    assert rep_h2.structure_ok is False

    # H3: stco pointing to trailing bytes outside mdat -> fails atom_structure & chunk_offsets
    rep_h3 = verify_mobile_compatibility(variants["H3"])
    assert rep_h3.atom_structure_ok is False
    assert rep_h3.chunk_offsets_ok is False
    assert rep_h3.structure_ok is False

    # H4: strip edts only -> valid container structure, emits warning if ctts > 0 without edts
    rep_h4 = verify_mobile_compatibility(variants["H4"])
    assert rep_h4.atom_structure_ok is True
    assert rep_h4.chunk_offsets_ok is True


@pytest.mark.parametrize(
    "preset",
    [
        "bxd-pc",
        "bxd-mobile",
        "bxd-hybrid",
        "bxd-clean",
        "x1t-pc",
        "x1t-mobile",
        "x1t-hybrid",
        "x1t-clean",
    ],
)
def test_all_four_bxd_presets_and_external_ffmpeg(
    ff: FFmpegPaths, tmp_path: Path, preset: str
) -> None:
    src = tmp_path / "orig.mp4"
    _make_clip(ff, src, "30", audio=True)

    orig_rep = MP4ForensicAnalyzer(src.read_bytes(), str(src)).parse()
    orig_hashes = MP4ForensicAnalyzer(src.read_bytes(), str(src)).hash_real_mdat_samples(
        orig_rep.atom_tree
    )

    out_dir = tmp_path / f"out_{preset}"
    req = PatchRequest(
        src=src,
        out_dir=out_dir,
        timescale=60000,
        strategy=preset,
        bxd_padding_bytes=(
            4096
            if preset in ("bxd-mobile", "bxd-hybrid", "x1t-mobile", "x1t-hybrid")
            else 0
        ),
        bxd_max_tail_ms=40,
    )
    res = patch(req, ff, lambda _: None)
    assert res.output.is_file()
    assert res.after.timescale == 60000

    mob = verify_mobile_compatibility(res.output)
    out_bytes = res.output.read_bytes()
    out_rep = MP4ForensicAnalyzer(out_bytes, str(res.output)).parse()
    out_hashes = MP4ForensicAnalyzer(out_bytes, str(res.output)).hash_real_mdat_samples(
        out_rep.atom_tree
    )

    # All presets must apply indeterminate mvhd
    assert any("indeterminate" in w.lower() for w in mob.warnings)
    moov_node = next((n for n in out_rep.atom_tree if n.type_str == "moov"), None)
    assert moov_node is not None
    mvhd_node = next((n for n in moov_node.children if n.type_str == "mvhd"), None)
    assert mvhd_node is not None
    assert mvhd_node.fields.get("duration") in (0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF)

    # Real sample hashes inside mdat must be 100% bit-exact across ALL presets
    assert out_hashes == orig_hashes
    assert out_rep.mdat_payload_sha256 == orig_rep.mdat_payload_sha256

    if preset in ("bxd-pc", "x1t-pc"):
        assert res.experimental is True
        assert mob.structure_ok is False
        assert mob.status_label == "Non-standard (PC-oriented / likely fails on mobile)"
    else:
        assert res.experimental is False
        assert mob.structure_ok is True, f"Preset {preset} failed mobile check: {mob.issues}"
        assert mob.status_label == "Structure OK (likely mobile-compatible)"

        # All 6 verification gates must pass
        assert mob.atom_structure_ok is True
        assert mob.chunk_offsets_ok is True
        assert mob.sample_tables_ok is True
        assert mob.mvhd_duration_defined is True
        assert mob.tkhd_duration_consistent is True
        assert mob.audio_duration_consistent is True

        integ = verify_payload_integrity(src, res.output)
        assert integ["atom structure"] == "PASS"
        assert integ["trailing data"] == "PASS"
        assert integ["chunk offsets"] == "PASS"
        assert integ["sample tables"] == "PASS"
        assert integ["mobile playback"] == "PASS"
        assert integ["mdat payload"] == "PASS"

        if preset in ("bxd-mobile", "bxd-hybrid", "x1t-mobile", "x1t-hybrid"):
            assert any(n.type_str == "free" for n in out_rep.atom_tree)
        # External ffmpeg decode gate must pass with 0 errors
        rc, err = _ffmpeg_decode_check(ff, res.output)
        assert rc == 0, f"ffmpeg decode failed for {preset}: {err}"
        assert err == ""


def test_mov_input_normalization_to_mp4(ff: FFmpegPaths, tmp_path: Path) -> None:
    mov_src = tmp_path / "clip.mov"
    _make_clip(ff, mov_src, "30", audio=True)

    out_dir = tmp_path / "out_mov"
    req = PatchRequest(
        src=mov_src,
        out_dir=out_dir,
        timescale=60000,
        strategy="x1t-mobile",
    )
    res = patch(req, ff, lambda _: None)
    assert res.output.is_file()
    assert res.output.suffix == ".mp4"
    assert res.after.timescale == 60000

    raw = res.output.read_bytes()
    assert raw[4:8] == b"ftyp"
    major_brand = raw[8:12]
    compatible_brands = raw[16:32]
    assert major_brand in (b"mp42", b"isom")
    assert b"isom" in (major_brand + compatible_brands)
    assert b"mp42" in (major_brand + compatible_brands)

    forensic = MP4ForensicAnalyzer(raw, str(res.output)).parse()
    ftyp_atom = next((a for a in forensic.atom_tree if a.type_str == "ftyp"), None)
    assert ftyp_atom is not None

    mob = verify_mobile_compatibility(res.output)
    assert mob.structure_ok is True
    rc, err = _ffmpeg_decode_check(ff, res.output)
    assert rc == 0, f"ffmpeg decode failed for mov normalization: {err}"
    assert err == ""


def test_repair_for_mobile_lossless_and_bframe_elst(ff: FFmpegPaths, tmp_path: Path) -> None:
    # Create a clip with B-frames (so ctts has positive composition offset)
    src = tmp_path / "bframe_src.mp4"
    subprocess.run(
        [
            str(ff.ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=30:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-bf",
            "2",
            "-g",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            str(src),
        ],
        check=True,
    )

    orig_bytes = src.read_bytes()
    orig_rep = MP4ForensicAnalyzer(orig_bytes, str(src)).parse()
    orig_hashes = MP4ForensicAnalyzer(orig_bytes, str(src)).hash_real_mdat_samples(
        orig_rep.atom_tree
    )

    # Patch with Bxd For PC (10x ghost samples, mvhd=-1, strips edts, appends raw trailing bytes)
    pc_out = tmp_path / "bframe_pc.mp4"
    MethodBXDDirectPatch(
        src=src,
        out=pc_out,
        target_timescale=60000,
        preset_mode="bxd-pc",
    ).execute()

    pc_bytes = pc_out.read_bytes()
    pc_rep = MP4ForensicAnalyzer(pc_bytes, str(pc_out)).parse()
    trailing_size = pc_rep.trailing_data_size
    assert trailing_size > 0
    raw_ghost_bytes = pc_bytes[-trailing_size:]
    extra_free_box = _box(b"free", b"\x00" * 32)
    repaired = tmp_path / "bframe_repaired.mp4"
    logs: list[str] = []
    repair_for_mobile(pc_out, repaired, emit=logs.append)

    assert repaired.is_file()
    mob_rep = verify_mobile_compatibility(repaired)
    assert mob_rep.structure_ok is True, f"Repaired file failed mobile check: {mob_rep.issues}"

    rep_bytes = repaired.read_bytes()
    rep_forensic = MP4ForensicAnalyzer(rep_bytes, str(repaired)).parse()
    rep_hashes = MP4ForensicAnalyzer(rep_bytes, str(repaired)).hash_real_mdat_samples(
        rep_forensic.atom_tree
    )
    assert rep_hashes == orig_hashes

    # Verify video track has reconstructed edts/elst and tkhd.duration == sum(elst.segment_duration)
    v_track = next(t for t in rep_forensic.tracks if t.handler_type == "vide")
    if v_track.ctts_entries and v_track.ctts_entries[0][1] > 0:
        assert v_track.has_edts is True
        elst_sum = sum(int(e.get("segment_duration", 0)) for e in v_track.elst_entries)
        assert v_track.duration_movie_ts == elst_sum

    # External ffmpeg decode check on repaired file
    rc, err = _ffmpeg_decode_check(ff, repaired)
    assert rc == 0, f"ffmpeg decode failed on repaired file: {err}"
    assert err == ""

    # Test post-mdat valid box preservation when trailing raw bytes follow a post-mdat free box
    repaired_plus_free_and_raw = tmp_path / "repaired_plus_free_raw.mp4"
    repaired_plus_free_and_raw.write_bytes(rep_bytes + extra_free_box + raw_ghost_bytes)
    repaired_clean2 = tmp_path / "repaired_clean2.mp4"
    repair_for_mobile(repaired_plus_free_and_raw, repaired_clean2)
    rep2_tree = MP4ForensicAnalyzer(repaired_clean2.read_bytes()).parse().atom_tree
    assert any(n.type_str == "free" for n in rep2_tree)
    assert not any(n.type_str == "[trailing_data]" for n in rep2_tree)


def test_repair_failsafe_rejects_non_bxd_corrupt_offsets(ff: FFmpegPaths, tmp_path: Path) -> None:
    src = tmp_path / "clean.mp4"
    _make_clip(ff, src, "30", audio=True)
    # Create a bxd-pc file, then corrupt the trailing ghost bytes so they are NOT PADDING_NAL
    pc_out = tmp_path / "corrupt_pc.mp4"
    MethodBXDDirectPatch(
        src=src, out=pc_out, target_timescale=60000, preset_mode="bxd-pc"
    ).execute()
    raw = bytearray(pc_out.read_bytes())
    raw[-len(PADDING_NAL) :] = b"\xDE\xAD\xBE\xEF\xCA\xFE\xBA\xBE"
    pc_out.write_bytes(bytes(raw))

    with pytest.raises(PatchError, match="Confirmation Gate failed"):
        repair_for_mobile(pc_out, tmp_path / "should_not_exist.mp4")


def test_synthetic_largesize_co64_and_mvex_fragmented(tmp_path: Path) -> None:
    # 1. Synthetic 64-bit largesize mdat + co64 chunk offset
    stts = _full_box(b"stts", 0, 0, struct.pack(">III", 1, 1, 1000))
    stsz = _full_box(b"stsz", 0, 0, struct.pack(">III", 0, 1, 14))
    stsc = _full_box(b"stsc", 0, 0, struct.pack(">IIII", 1, 1, 1, 1))
    stsd = _full_box(b"stsd", 0, 0, struct.pack(">I", 0))
    hdlr = _full_box(b"hdlr", 0, 0, struct.pack(">4s4s12s", b"\x00" * 4, b"vide", b"\x00" * 12))
    mdhd = _full_box(b"mdhd", 0, 0, struct.pack(">IIIIHH", 0, 0, 1000, 1000, 0, 0))
    tkhd = _full_box(b"tkhd", 0, 0, struct.pack(">IIIII", 0, 0, 1, 0, 1000) + b"\x00" * 60)
    mvhd = _full_box(b"mvhd", 0, 0, struct.pack(">IIII", 0, 0, 1000, 1000) + b"\x00" * 80)
    ftyp = _box(b"ftyp", b"isom\x00\x00\x02\x00isom")
    mdat_large = _largesize_box(b"mdat", b"SAMPLE_PAYLOAD")

    dummy_co64 = _full_box(b"co64", 0, 0, struct.pack(">IQ", 1, 0))
    moov_dummy = _box(
        b"moov",
        mvhd
        + _box(
            b"trak",
            tkhd
            + _box(
                b"mdia",
                mdhd + hdlr + _box(b"minf", _box(b"stbl", stsd + stts + stsz + stsc + dummy_co64)),
            ),
        ),
    )
    # mdat_large has a 16-byte header
    valid_off64 = len(ftyp) + len(moov_dummy) + 16
    co64 = _full_box(b"co64", 0, 0, struct.pack(">IQ", 1, valid_off64))
    moov = _box(
        b"moov",
        mvhd
        + _box(
            b"trak",
            tkhd
            + _box(
                b"mdia",
                mdhd + hdlr + _box(b"minf", _box(b"stbl", stsd + stts + stsz + stsc + co64)),
            ),
        ),
    )

    f64 = tmp_path / "large_co64.mp4"
    f64.write_bytes(ftyp + moov + mdat_large)
    assert verify_atom_structure(f64).is_valid is True
    assert verify_offsets(f64)[0] is True
    assert verify_sample_tables(f64)[0] is True
    assert verify_mobile_compatibility(f64).structure_ok is True

    # 2. Fragmented MP4 (moov with mvex and indeterminate mvhd duration = 0xFFFFFFFF)
    mvhd_indet = _full_box(
        b"mvhd", 0, 0, struct.pack(">IIII", 0, 0, 1000, 0xFFFFFFFF) + b"\x00" * 80
    )
    mvex = _box(b"mvex", _full_box(b"mehd", 0, 0, struct.pack(">I", 0)))
    moov_frag = _box(
        b"moov",
        mvhd_indet
        + mvex
        + _box(
            b"trak",
            tkhd
            + _box(
                b"mdia",
                mdhd + hdlr + _box(b"minf", _box(b"stbl", stsd + stts + stsz + stsc + co64)),
            ),
        ),
    )
    # Recompute offset because mvex increased moov size
    valid_off_frag = len(ftyp) + len(moov_frag) + 16
    co64_frag = _full_box(b"co64", 0, 0, struct.pack(">IQ", 1, valid_off_frag))
    moov_frag = _box(
        b"moov",
        mvhd_indet
        + mvex
        + _box(
            b"trak",
            tkhd
            + _box(
                b"mdia",
                mdhd + hdlr + _box(b"minf", _box(b"stbl", stsd + stts + stsz + stsc + co64_frag)),
            ),
        ),
    )
    f_frag = tmp_path / "frag_mvex.mp4"
    f_frag.write_bytes(ftyp + moov_frag + mdat_large)
    mob_frag = verify_mobile_compatibility(f_frag)
    assert mob_frag.mvhd_duration_defined is True
    assert mob_frag.structure_ok is True


def test_video_only_multi_audio_and_mov_tmcd(ff: FFmpegPaths, tmp_path: Path) -> None:
    # 1. Video-only MP4
    v_only = tmp_path / "video_only.mp4"
    _make_clip(ff, v_only, "30", audio=False)
    v_out = tmp_path / "video_only_patched.mp4"
    MethodBXDDirectPatch(
        src=v_only, out=v_out, target_timescale=60000, preset_mode="bxd-mobile"
    ).execute()
    assert verify_mobile_compatibility(v_out).structure_ok is True

    # 2. Multi-audio MP4 (2 audio tracks)
    multi_a = tmp_path / "multi_audio.mp4"
    subprocess.run(
        [
            str(ff.ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=30:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=1",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-map",
            "2:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(multi_a),
        ],
        check=True,
    )
    ma_out = tmp_path / "multi_audio_patched.mp4"
    MethodBXDDirectPatch(
        src=multi_a, out=ma_out, target_timescale=60000, preset_mode="bxd-mobile"
    ).execute()
    assert verify_mobile_compatibility(ma_out).structure_ok is True
    assert _ffmpeg_decode_check(ff, ma_out)[0] == 0

    # 3. MOV with tmcd timecode track
    mov_tmcd = tmp_path / "clip_tmcd.mov"
    subprocess.run(
        [
            str(ff.ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=30:duration=1",
            "-timecode",
            "01:02:03:04",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(mov_tmcd),
        ],
        check=True,
    )
    mov_out = tmp_path / "clip_tmcd_patched.mov"
    MethodBXDDirectPatch(
        src=mov_tmcd, out=mov_out, target_timescale=60000, preset_mode="bxd-mobile"
    ).execute()
    assert verify_mobile_compatibility(mov_out).structure_ok is True
    assert _ffmpeg_decode_check(ff, mov_out)[0] == 0


def test_diagnostic_logger_masking_truncation_and_rotation(
    ff: FFmpegPaths, tmp_path: Path
) -> None:
    # 1. Path & username masking across Windows, forward-slash, and UNC paths
    raw_msg = (
        r"File C:\Users\SecretAlice\Videos\clip.mp4 and "
        "C:/Users/SecretAlice/Desktop/out.mp4 and "
        r"\\NASServer\PrivateShare\folder\video.mp4"
    )
    masked = mask_sensitive_text(raw_msg, mask_enabled=True)
    assert "SecretAlice" not in masked
    assert "C:\\Users\\<USER>\\" in masked
    assert "C:/Users/<USER>/" in masked
    assert "\\\\<SERVER>\\<SHARE>\\" in masked

    unmasked = mask_sensitive_text(raw_msg, mask_enabled=False)
    assert "SecretAlice" in unmasked

    # 2. Table summary truncation
    big_list = list(range(1000))
    summary = summarize_int_list(big_list, head=5, tail=5)
    assert summary["count"] == 1000
    assert summary["truncated"] == 990
    assert len(summary["head"]) == 5
    assert len(summary["tail"]) == 5

    # 3. Diagnostic report generation & size cap (< 5 MB)
    src = tmp_path / "diag_src.mp4"
    _make_clip(ff, src, "30", audio=True)
    report = build_diagnostic_report(
        target_file=src,
        source_file=src,
        preset="bxd-mobile",
        target_timescale=60000,
        console_lines=[f"Line {i}: C:\\Users\\SecretAlice\\clip.mp4" for i in range(100)],
        mask_paths=True,
    )
    txt = format_diagnostic_text(report)
    assert len(txt.encode("utf-8")) < 5 * 1024 * 1024
    assert "SecretAlice" not in txt
    assert "MOBILE COMPATIBILITY CHECK" in txt

    # 4. Auto-log rotation (caps auto_patch_*.log at MAX_AUTO_LOGS=20, preserves user logs)
    log_dir = tmp_path / "logs"
    user_log = log_dir / "my_saved_investigation.log"
    export_diagnostic_log(user_log, target_file=src, mask_paths=True)
    assert user_log.is_file()

    for _i in range(MAX_AUTO_LOGS + 5):
        p = auto_save_diagnostic_log(
            target_file=src,
            preset="bxd-mobile",
            target_timescale=60000,
            log_dir=log_dir,
        )
        # Ensure distinct mtime order
        assert p is not None

    auto_files = list(log_dir.glob("auto_patch_*.log"))
    assert len(auto_files) <= MAX_AUTO_LOGS
    # User-saved log must never be deleted by auto-log rotation
    assert user_log.is_file()
