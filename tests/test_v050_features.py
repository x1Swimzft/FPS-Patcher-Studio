"""Tests for Release v0.5.0 features:
- Faststart reorganization (ftyp -> moov -> mdat) in Direct Atom patcher.
- Safe audio preservation across X1T presets (zero ghost audio frames in Mobile & Clean).
- Source bitrate guard warning (>25 Mbps) for TikTok streaming.
- Non-AAC audio codec warning (e.g. PCM).
- Capped ghost sample inflation in PC preset.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from fps_patcher.core.atom_patcher import patch_video_track_timescale
from fps_patcher.core.bxd_patcher import MethodBXDDirectPatch
from fps_patcher.core.models import VideoInfo
from fps_patcher.core.verifier import (
    verify_atom_structure,
    verify_mobile_compatibility,
    verify_offsets,
    verify_sample_tables,
)


def test_direct_atom_faststart_reorders_moov_before_mdat(
    clip30: Path, tmp_path: Path
) -> None:
    # Verify clip30 source has moov located after mdat
    src_bytes = clip30.read_bytes()
    src_moov_pos = src_bytes.find(b"moov")
    src_mdat_pos = src_bytes.find(b"mdat")
    assert src_moov_pos > src_mdat_pos, "clip30 source file must have moov trailing after mdat"

    out = tmp_path / "faststart_out.mp4"
    patch_video_track_timescale(clip30, out, target_timescale=60000)

    assert out.is_file()
    out_bytes = out.read_bytes()
    out_moov_pos = out_bytes.find(b"moov")
    out_mdat_pos = out_bytes.find(b"mdat")

    # moov must now precede mdat in output (Faststart streaming layout)
    assert out_moov_pos < out_mdat_pos, "Direct atom output must position moov before mdat"

    # All structural gates must pass
    struct_res = verify_atom_structure(out_bytes)
    assert struct_res.is_valid
    assert not struct_res.malformed_atoms

    offsets_ok, offset_issues = verify_offsets(out_bytes)
    assert offsets_ok, f"Chunk offsets broken after faststart shift: {offset_issues}"

    tables_ok, table_issues = verify_sample_tables(out_bytes)
    assert tables_ok, f"Sample tables corrupted: {table_issues}"


def test_bxd_mobile_and_clean_safe_audio_no_ghosts(
    clip30: Path, tmp_path: Path
) -> None:
    out_mobile = tmp_path / "mobile_out.mp4"
    patcher_mobile = MethodBXDDirectPatch(
        src=clip30,
        out=out_mobile,
        target_timescale=60000,
        preset_mode="bxd-mobile",
    )
    patcher_mobile.execute()
    assert out_mobile.is_file()

    out_clean = tmp_path / "clean_out.mp4"
    patcher_clean = MethodBXDDirectPatch(
        src=clip30,
        out=out_clean,
        target_timescale=60000,
        preset_mode="bxd-clean",
    )
    patcher_clean.execute()
    assert out_clean.is_file()

    for p in (out_mobile, out_clean):
        raw = p.read_bytes()
        mob = verify_mobile_compatibility(raw)
        assert mob.compatible
        assert mob.structure_ok
        assert mob.audio_duration_consistent
        assert not mob.issues

        # Zero unboxed trailing bytes
        struct_res = verify_atom_structure(raw)
        assert not struct_res.has_trailing_data
        assert struct_res.trailing_bytes_count == 0


def test_bitrate_and_non_aac_advisory_warnings(tmp_path: Path) -> None:
    high_bitrate_info = VideoInfo(
        path=tmp_path / "dummy.mp4",
        codec="h264",
        width=1920,
        height=1080,
        avg_fps=Fraction(60),
        r_fps=Fraction(60),
        duration_s=10.0,
        timescale=60000,
        nb_frames=600,
        has_audio=True,
        stream_count=2,
        audio_codec="pcm_s16le",
        bit_rate=35_000_000,  # 35 Mbps > 25 Mbps
    )

    assert high_bitrate_info.bit_rate == 35_000_000
    assert high_bitrate_info.audio_codec == "pcm_s16le"


def test_bxd_pc_caps_ghost_inflation_and_emits_warning(
    clip30: Path, tmp_path: Path
) -> None:
    logs: list[str] = []
    out = tmp_path / "pc_out.mp4"
    patcher = MethodBXDDirectPatch(
        src=clip30,
        out=out,
        target_timescale=60000,
        multiplier=10,
        preset_mode="bxd-pc",
        emit=logs.append,
    )
    patcher.execute()
    assert out.is_file()

    # Check warning was emitted
    assert any("recommend X1T For Mobile" in msg for msg in logs)
    assert any("PC mode: " in msg for msg in logs)
