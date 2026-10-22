from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import pytest

from fps_patcher.core.atom_patcher import patch_video_track_timescale
from fps_patcher.core.errors import PatchError
from fps_patcher.core.ffmpeg_locator import FFmpegPaths
from fps_patcher.core.prober import probe


def _top_level_mdat_payload(path: Path) -> bytes:
    data = path.read_bytes()
    pos = 0
    while pos + 8 <= len(data):
        size32, typ = struct.unpack_from(">I4s", data, pos)
        header = 8
        if size32 == 1:
            size = struct.unpack_from(">Q", data, pos + 8)[0]
            header = 16
        elif size32 == 0:
            size = len(data) - pos
        else:
            size = size32
        if typ == b"mdat":
            return data[pos + header : pos + size]
        pos += size
    raise AssertionError("mdat not found")


def test_direct_atom_patch_preserves_media_and_timing(tmp_path: Path, ff: FFmpegPaths) -> None:
    src = tmp_path / "src.mp4"
    out = tmp_path / "out.mp4"
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
            "testsrc=size=640x360:rate=30:duration=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(src),
        ],
        check=True,
    )

    before = probe(src, ff.ffprobe)
    patch_video_track_timescale(src, out, 120000)
    after = probe(out, ff.ffprobe)

    assert after.timescale == 120000
    assert after.codec == before.codec
    assert after.width == before.width
    assert after.height == before.height
    assert after.nb_frames == before.nb_frames
    assert abs(after.fps - before.fps) < 0.01
    assert abs(after.duration_s - before.duration_s) < 0.01
    assert _top_level_mdat_payload(out) == _top_level_mdat_payload(src)


def test_direct_atom_refuses_same_path(tmp_path: Path) -> None:
    src = tmp_path / "dummy.mp4"
    src.write_bytes(b"dummy")
    with pytest.raises(PatchError, match="refusing in-place overwrite"):
        patch_video_track_timescale(src, src, 60000)


def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), typ) + payload


def test_huge_stts_sample_count_rejected_without_expansion(tmp_path: Path) -> None:
    hdlr = _box(b"hdlr", bytes(8) + b"vide" + bytes(12))
    mdhd = _box(b"mdhd", struct.pack(">B3xIIIIHH", 0, 0, 0, 600, 600, 0, 0))
    stts = _box(b"stts", struct.pack(">B3xIII", 0, 1, 0xFFFFFFFF, 1))
    stbl = _box(b"stbl", stts)
    minf = _box(b"minf", stbl)
    mdia = _box(b"mdia", mdhd + hdlr + minf)
    moov = _box(b"moov", _box(b"trak", mdia))
    src = tmp_path / "evil.mp4"
    src.write_bytes(moov + _box(b"mdat", b"\x00" * 16))
    with pytest.raises(PatchError, match="exceeds file size"):
        patch_video_track_timescale(src, tmp_path / "out.mp4", 90000)
