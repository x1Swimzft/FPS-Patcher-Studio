"""Phase 2 (v0.7.0): lossless Rec.709 colr tagging and metadata scrubbing."""

from __future__ import annotations

import hashlib
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from fps_patcher.core.colr import ColrError, sanitize
from fps_patcher.core.ffmpeg_locator import FFmpegPaths


def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), typ) + payload


def _full(typ: bytes, payload: bytes = b"", version_flags: bytes = b"\0\0\0\0") -> bytes:
    return _box(typ, version_flags + payload)


def _nclx(primaries: int, transfer: int, matrix: int) -> bytes:
    return b"nclx" + struct.pack(">HHHB", primaries, transfer, matrix, 0)


def _sample_entry(children: bytes) -> bytes:
    # 6 reserved + 2 data_reference_index + 70 VisualSampleEntry fields.
    return _box(b"avc1", b"\0" * 78 + children)


def _stco_payload(offset: int) -> bytes:
    return struct.pack(">II", 1, offset)


def _chunk_payload(offsets: list[int], *, co64: bool) -> bytes:
    fmt = ">Q" if co64 else ">I"
    return struct.pack(">I", len(offsets)) + b"".join(struct.pack(fmt, o) for o in offsets)


def _moov(
    offset: int | list[int],
    *,
    color: bytes | None,
    hdr_box: bool,
    metadata: bool,
    co64: bool = False,
) -> bytes:
    children = _box(b"colr", color) if color else b""
    if hdr_box:
        children += _box(b"mdcv", b"\0" * 24)
    entry = _sample_entry(children)
    stsd = _full(b"stsd", struct.pack(">I", 1) + entry)
    offsets = [offset] if isinstance(offset, int) else offset
    stco = _full(b"co64" if co64 else b"stco", _chunk_payload(offsets, co64=co64))
    stbl = _box(b"stbl", stsd + stco)
    minf = _box(b"minf", stbl)
    hdlr = _full(b"hdlr", b"\0\0\0\0" + b"vide" + b"\0" * 12)
    mdia = _box(b"mdia", hdlr + minf)
    trak = _box(b"trak", mdia)
    extra = b""
    if metadata:
        extra = _box(b"udta", _box(b"meta", b"\0\0\0\0" + b"editor"))
    return _box(b"moov", trak + extra)


def _build(
    path: Path,
    *,
    moov_first: bool = True,
    color: bytes | None = None,
    hdr_box: bool = False,
    metadata: bool = True,
) -> tuple[Path, str]:
    ftyp = _box(b"ftyp", b"isom\0\0\0\0isom")
    media = b"MEDIA-PAYLOAD-" * 64

    # Two passes: stco needs the final mdat payload offset, which depends on moov size.
    moov = _moov(0, color=color, hdr_box=hdr_box, metadata=metadata)
    if moov_first:
        offset = len(ftyp) + len(moov) + 8
        moov = _moov(offset, color=color, hdr_box=hdr_box, metadata=metadata)
        data = ftyp + moov + _box(b"mdat", media)
    else:
        offset = len(ftyp) + 8
        moov = _moov(offset, color=color, hdr_box=hdr_box, metadata=metadata)
        data = ftyp + _box(b"mdat", media) + moov
    path.write_bytes(data)
    return path, hashlib.sha256(media).hexdigest()


def _top(data: bytes) -> dict[bytes, tuple[int, int]]:
    found: dict[bytes, tuple[int, int]] = {}
    pos = 0
    while pos + 8 <= len(data):
        size32, typ = struct.unpack_from(">I4s", data, pos)
        if size32 == 1:
            size = struct.unpack_from(">Q", data, pos + 8)[0]
        else:
            size = size32 or len(data) - pos
        found.setdefault(typ, (pos, pos + size))
        pos += size
    return found


def _mdat_payload_sha(data: bytes) -> str:
    start, end = _top(data)[b"mdat"]
    return hashlib.sha256(data[start + 8 : end]).hexdigest()


def _first_stco_offset(data: bytes) -> int:
    moov_start, moov_end = _top(data)[b"moov"]
    pos = data.find(b"stco", moov_start, moov_end)
    assert pos > 0
    box_start = pos - 4
    payload = data[box_start + 8 : box_start + struct.unpack_from(">I", data, box_start)[0]]
    return int(struct.unpack_from(">I", payload, 8)[0])


def _chunk_offsets(data: bytes) -> list[int]:
    moov_start, moov_end = _top(data)[b"moov"]
    for typ, fmt, step in ((b"co64", ">Q", 8), (b"stco", ">I", 4)):
        pos = data.find(typ, moov_start, moov_end)
        if pos < 0:
            continue
        box_start = pos - 4
        size = struct.unpack_from(">I", data, box_start)[0]
        payload = data[box_start + 8 : box_start + size]
        count = struct.unpack_from(">I", payload, 4)[0]
        return [struct.unpack_from(fmt, payload, 8 + i * step)[0] for i in range(count)]
    return []


def _mdat_ranges(data: bytes) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    pos = 0
    while pos + 8 <= len(data):
        size32, typ = struct.unpack_from(">I4s", data, pos)
        if size32 == 1:
            size = struct.unpack_from(">Q", data, pos + 8)[0]
            header = 16
        else:
            size = size32 or len(data) - pos
            header = 8
        if typ == b"mdat":
            ranges.append((pos + header, pos + size))
        pos += size
    return ranges


def _mdat_payload_shas(data: bytes) -> list[str]:
    return [hashlib.sha256(data[start:end]).hexdigest() for start, end in _mdat_ranges(data)]


def _build_multi(
    path: Path,
    order: list[str],
    *,
    co64: bool = False,
    metadata: bool = True,
) -> tuple[Path, list[int]]:
    """Build a file from ``order`` entries: ``ftyp``, ``moov``, ``mdat:a/b/c``."""
    ftyp = _box(b"ftyp", b"isom\0\0\0\0isom")
    media = {key: key.encode() * 300 for key in "abc"}
    mdats = [k for k in order if k.startswith("mdat:")]
    placeholder = _moov([0] * len(mdats), color=None, hdr_box=False, metadata=metadata, co64=co64)

    starts: dict[str, int] = {}
    pos = 0
    for kind in order:
        if kind == "moov":
            starts["moov"] = pos
            pos += len(placeholder)
        elif kind == "ftyp":
            pos += len(ftyp)
        else:
            starts[kind] = pos + 8  # mdat payload start
            pos += 8 + len(media[kind.split(":", 1)[1]])

    offsets = [starts[k] for k in mdats]
    moov = _moov(offsets, color=None, hdr_box=False, metadata=metadata, co64=co64)
    assert len(moov) == len(placeholder)

    data = bytearray()
    for kind in order:
        if kind == "ftyp":
            data += ftyp
        elif kind == "moov":
            data += moov
        else:
            data += _box(b"mdat", media[kind.split(":", 1)[1]])
    path.write_bytes(bytes(data))
    return path, offsets


def test_adds_rec709_and_keeps_mdat_bit_exact(tmp_path: Path) -> None:
    path, media_hash = _build(tmp_path / "add.mp4", color=None, metadata=False)
    before = path.read_bytes()

    result = sanitize(path, fix_color=True, scrub_metadata=False)

    after = path.read_bytes()
    assert result.status == "patched"
    assert result.bytes_delta == 19
    assert b"nclx" in after
    assert _mdat_payload_sha(after) == media_hash
    mdat_start = _top(after)[b"mdat"][0]
    assert _first_stco_offset(after) == mdat_start + 8
    assert _mdat_payload_sha(before) == media_hash


def test_replaces_bad_tag_and_scrubs_metadata(tmp_path: Path) -> None:
    path, media_hash = _build(tmp_path / "replace.mp4", color=_nclx(1, 2, 1), metadata=True)
    before = path.read_bytes()

    result = sanitize(path, fix_color=True, scrub_metadata=True)

    after = path.read_bytes()
    assert result.status == "patched"
    assert result.metadata_removed == 1  # moov.udta (and everything inside it)
    assert b"editor" not in after
    assert _nclx(1, 1, 1) in after
    assert _mdat_payload_sha(after) == media_hash
    assert len(after) < len(before)  # metadata removal dominates +19 bytes of colr
    assert _first_stco_offset(after) == _top(after)[b"mdat"][0] + 8


def test_hdr_is_skipped_but_metadata_is_scrubbed(tmp_path: Path) -> None:
    path, media_hash = _build(
        tmp_path / "hdr.mp4",
        color=_nclx(9, 16, 9),
        hdr_box=True,
        metadata=True,
    )
    result = sanitize(path, fix_color=True, scrub_metadata=True)

    after = path.read_bytes()
    assert result.status == "skipped"
    assert _nclx(9, 16, 9) in after
    assert b"editor" not in after
    assert _mdat_payload_sha(after) == media_hash


def test_already_rec709_is_unchanged(tmp_path: Path) -> None:
    path, _ = _build(tmp_path / "same.mp4", color=_nclx(1, 1, 1), metadata=False)
    before = path.read_bytes()

    result = sanitize(path, fix_color=True, scrub_metadata=False)

    assert result.status == "unchanged"
    assert result.bytes_delta == 0
    assert path.read_bytes() == before


def test_moov_after_mdat_does_not_shift_chunk_offsets(tmp_path: Path) -> None:
    path, media_hash = _build(
        tmp_path / "late.mp4", moov_first=False, color=None, metadata=True
    )
    before_offset = _first_stco_offset(path.read_bytes())

    result = sanitize(path, fix_color=True, scrub_metadata=True)

    after = path.read_bytes()
    assert result.bytes_delta < 0
    assert _first_stco_offset(after) == before_offset
    assert _mdat_payload_sha(after) == media_hash


def test_mdat_on_both_sides_of_moov_shifts_only_late_offsets(tmp_path: Path) -> None:
    path, offsets = _build_multi(tmp_path / "mixed.mp4", ["ftyp", "mdat:a", "moov", "mdat:b"])
    before = path.read_bytes()

    result = sanitize(path, fix_color=True, scrub_metadata=True)

    after = path.read_bytes()
    delta = len(after) - len(before)
    assert result.bytes_delta == delta < 0  # udta scrubbing outweighs the added colr
    assert _chunk_offsets(after) == [offsets[0], offsets[1] + delta]
    assert _mdat_payload_shas(after) == _mdat_payload_shas(before)
    for offset in _chunk_offsets(after):
        assert any(start <= offset < end for start, end in _mdat_ranges(after))


def test_two_mdats_after_moov_shift_together(tmp_path: Path) -> None:
    path, offsets = _build_multi(tmp_path / "two.mp4", ["ftyp", "moov", "mdat:a", "mdat:b"])
    before = path.read_bytes()

    sanitize(path, fix_color=True, scrub_metadata=True)

    after = path.read_bytes()
    delta = len(after) - len(before)
    assert delta != 0
    assert _chunk_offsets(after) == [offset + delta for offset in offsets]
    assert _mdat_payload_shas(after) == _mdat_payload_shas(before)


def test_co64_offsets_are_shifted_per_entry(tmp_path: Path) -> None:
    path, offsets = _build_multi(
        tmp_path / "co64.mp4", ["ftyp", "mdat:a", "moov", "mdat:b"], co64=True
    )
    before = path.read_bytes()

    result = sanitize(path, fix_color=True, scrub_metadata=True)

    after = path.read_bytes()
    delta = len(after) - len(before)
    assert result.status == "patched"
    assert b"co64" in after
    assert _chunk_offsets(after) == [offsets[0], offsets[1] + delta]
    assert _mdat_payload_shas(after) == _mdat_payload_shas(before)


def test_chunk_offset_inside_moov_is_rejected(tmp_path: Path) -> None:
    ftyp = _box(b"ftyp", b"isom\0\0\0\0isom")
    moov_start = len(ftyp)
    moov = _moov(moov_start + 4, color=None, hdr_box=False, metadata=True)
    path = tmp_path / "inside.mp4"
    path.write_bytes(ftyp + moov + _box(b"mdat", b"x" * 64))
    before = path.read_bytes()

    with pytest.raises(ColrError, match="inside moov"):
        sanitize(path, fix_color=True, scrub_metadata=True)

    assert path.read_bytes() == before  # refused before touching the file


def test_chunk_offset_outside_every_mdat_is_rejected(tmp_path: Path) -> None:
    ftyp = _box(b"ftyp", b"isom\0\0\0\0isom")
    placeholder = _moov(0, color=None, hdr_box=False, metadata=True)
    media = b"y" * 64
    outside = len(ftyp) + len(placeholder) + 8 + len(media)
    moov = _moov(outside, color=None, hdr_box=False, metadata=True)
    path = tmp_path / "outside.mp4"
    path.write_bytes(ftyp + moov + _box(b"mdat", media))
    before = path.read_bytes()

    with pytest.raises(ColrError, match="outside every mdat"):
        sanitize(path, fix_color=True, scrub_metadata=True)

    assert path.read_bytes() == before


def test_chunk_offset_before_moov_must_point_into_an_mdat(tmp_path: Path) -> None:
    ftyp = _box(b"ftyp", b"isom\0\0\0\0isom")
    media = b"z" * 64
    # Offset 8 points into ftyp, not into the mdat that precedes moov.
    moov = _moov(8, color=None, hdr_box=False, metadata=True)
    path = tmp_path / "early-bad.mp4"
    path.write_bytes(ftyp + _box(b"mdat", media) + moov)
    before = path.read_bytes()

    with pytest.raises(ColrError, match="outside every mdat"):
        sanitize(path, fix_color=True, scrub_metadata=True)

    assert path.read_bytes() == before


def test_rejects_non_video_extension(tmp_path: Path) -> None:
    bad = tmp_path / "notes.txt"
    bad.write_text("not a video")
    with pytest.raises(ColrError):
        sanitize(bad)


def test_no_request_is_a_noop(tmp_path: Path) -> None:
    path, _ = _build(tmp_path / "noop.mp4", color=None, metadata=True)
    before = path.read_bytes()
    result = sanitize(path, fix_color=False, scrub_metadata=False)
    assert result.status == "unchanged"
    assert path.read_bytes() == before


def test_pipeline_part_suffix_is_supported(tmp_path: Path) -> None:
    path, _ = _build(tmp_path / "clip.mp4", color=None, metadata=False)
    part = path.with_name(path.name + ".part")
    path.rename(part)

    result = sanitize(part, fix_color=True, scrub_metadata=False)

    assert result.status == "patched"
    assert b"nclx" in part.read_bytes()


def _moov_entries(entries: list[bytes], offset: int, *, metadata: bool = False) -> bytes:
    stsd = _full(b"stsd", struct.pack(">I", len(entries)) + b"".join(entries))
    stco = _full(b"stco", _chunk_payload([offset], co64=False))
    stbl = _box(b"stbl", stsd + stco)
    minf = _box(b"minf", stbl)
    hdlr = _full(b"hdlr", b"\0\0\0\0" + b"vide" + b"\0" * 12)
    mdia = _box(b"mdia", hdlr + minf)
    trak = _box(b"trak", mdia)
    extra = b""
    if metadata:
        extra = _box(b"udta", _box(b"meta", b"\0\0\0\0" + b"editor"))
    return _box(b"moov", trak + extra)


def _build_with_entries(
    path: Path, entries: list[bytes], *, metadata: bool = False
) -> tuple[Path, str]:
    ftyp = _box(b"ftyp", b"isom\0\0\0\0isom")
    media = b"MEDIA-PAYLOAD-" * 64
    placeholder = _moov_entries(entries, 0, metadata=metadata)
    offset = len(ftyp) + len(placeholder) + 8
    moov = _moov_entries(entries, offset, metadata=metadata)
    assert len(moov) == len(placeholder)
    path.write_bytes(ftyp + moov + _box(b"mdat", media))
    return path, hashlib.sha256(media).hexdigest()


def test_only_unsupported_sample_entry_is_skipped_and_preserved(tmp_path: Path) -> None:
    # AudioSampleEntry layout is not VisualSampleEntry; the parser must not assume 78 bytes.
    unsupported = _box(b"mp4a", b"\0" * 28 + _box(b"esds", b"\0" * 12))
    path, media_hash = _build_with_entries(
        tmp_path / "unsupported.mp4", [unsupported], metadata=False
    )
    before = path.read_bytes()

    result = sanitize(path, fix_color=True, scrub_metadata=False)

    after = path.read_bytes()
    assert result.status == "skipped"
    assert "unsupported sample entry" in result.reason
    assert after == before
    assert _mdat_payload_sha(after) == media_hash


def test_mixed_supported_and_unsupported_entries_tag_only_supported(tmp_path: Path) -> None:
    # Shaped like VisualSampleEntry, but not on the allowlist: its tail must stay opaque.
    unsupported = _box(b"mp4a", b"\0" * 78 + _box(b"udta", b"KEEP"))
    supported = _sample_entry(b"")
    path, media_hash = _build_with_entries(
        tmp_path / "mixed.mp4", [unsupported, supported], metadata=False
    )

    result = sanitize(path, fix_color=True, scrub_metadata=True)

    after = path.read_bytes()
    assert result.status == "patched"
    assert "unsupported sample entry" in result.reason
    assert unsupported in after  # unsupported entry bytes survive verbatim
    assert b"KEEP" in after  # scrubber did not descend into the unsupported entry
    assert after.count(b"nclx") == 1
    assert _mdat_payload_sha(after) == media_hash
    assert _first_stco_offset(after) == _top(after)[b"mdat"][0] + 8


def _decoded_video_frames(ff: FFmpegPaths, path: Path) -> int:
    proc = subprocess.run(
        [
            str(ff.ffprobe),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return int(proc.stdout.strip() or 0)


def _assert_real_roundtrip(ff: FFmpegPaths, src: Path, path: Path) -> None:
    shutil.copyfile(src, path)
    before = path.read_bytes()
    before_shas = _mdat_payload_shas(before)
    assert before_shas

    result = sanitize(path, fix_color=True, scrub_metadata=True)

    after = path.read_bytes()
    assert result.status == "patched"
    assert _mdat_payload_shas(after) == before_shas
    ranges = _mdat_ranges(after)
    offsets = _chunk_offsets(after)
    assert offsets
    assert b"stco" in after or b"co64" in after
    assert all(any(start <= offset < end for start, end in ranges) for offset in offsets)
    assert b"nclx" in after
    assert _decoded_video_frames(ff, path) > 0


def test_real_mp4_roundtrip_keeps_mdat_and_decodes(
    ff: FFmpegPaths, clip30: Path, tmp_path: Path
) -> None:
    _assert_real_roundtrip(ff, clip30, tmp_path / "real.mp4")


def test_real_mov_roundtrip_keeps_mdat_and_decodes(
    ff: FFmpegPaths, clip5994: Path, tmp_path: Path
) -> None:
    _assert_real_roundtrip(ff, clip5994, tmp_path / "real.mov")


def test_real_mdat_before_moov_keeps_offsets(
    ff: FFmpegPaths, clip30: Path, tmp_path: Path
) -> None:
    path = tmp_path / "hybrid.mp4"
    subprocess.run(
        [
            str(ff.ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(clip30),
            "-c",
            "copy",
            "-movflags",
            "+hybrid_fragmented",
            str(path),
        ],
        check=True,
        timeout=60,
    )
    before = path.read_bytes()
    assert before.find(b"mdat") < before.find(b"moov")
    assert b"moof" not in before
    before_offsets = _chunk_offsets(before)
    before_shas = _mdat_payload_shas(before)

    result = sanitize(path, fix_color=True, scrub_metadata=True)

    after = path.read_bytes()
    assert result.status == "patched"
    assert _chunk_offsets(after) == before_offsets
    assert _mdat_payload_shas(after) == before_shas
    assert _decoded_video_frames(ff, path) > 0


def test_real_fragmented_mp4_is_skipped_untouched(
    ff: FFmpegPaths, clip30: Path, tmp_path: Path
) -> None:
    path = tmp_path / "fragmented.mp4"
    subprocess.run(
        [
            str(ff.ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(clip30),
            "-c",
            "copy",
            "-movflags",
            "frag_keyframe+empty_moov",
            str(path),
        ],
        check=True,
        timeout=60,
    )
    before = path.read_bytes()
    assert b"moof" in before

    result = sanitize(path, fix_color=True, scrub_metadata=True)

    assert result.status == "skipped"
    assert "fragmented" in result.reason
    assert path.read_bytes() == before
    assert _decoded_video_frames(ff, path) > 0
