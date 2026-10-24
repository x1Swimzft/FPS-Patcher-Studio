"""Phase 2 (v0.7.0): lossless Rec.709 colr tagging and metadata scrubbing."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from fps_patcher.core.colr import ColrError, sanitize


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
