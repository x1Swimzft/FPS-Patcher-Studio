"""Lossless Rec.709 ``colr`` tagging and ``udta``/``meta`` scrubbing for ISO-BMFF.

The media payload is never decoded or re-encoded. Only the ``moov`` box is parsed
and rebuilt; ``mdat`` bytes are stream-copied verbatim. Each ``stco``/``co64``
chunk offset is shifted individually when it points at media located after the
rewritten ``moov``, so layouts with ``mdat`` on both sides of ``moov`` stay valid.

Deliberate limits (see ``shortcut:`` comments):
- Fragmented MP4 (``moof``/``sidx``) is skipped rather than guessed at.
- Untagged HDR is indistinguishable from untagged SDR; only explicit HDR boxes or
  a BT.2020/PQ/HLG ``colr`` are treated as HDR.
"""

from __future__ import annotations

import os
import shutil
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

from .models import SUPPORTED_EXTENSIONS


class ColrError(Exception):
    """Raised when the container cannot be rewritten safely."""


ColorStatus = Literal["patched", "unchanged", "skipped"]


@dataclass(frozen=True)
class ColrResult:
    output: Path
    status: ColorStatus
    reason: str
    bytes_delta: int
    metadata_removed: int


def _is_supported_container(path: Path) -> bool:
    if path.suffix.lower() in SUPPORTED_EXTENSIONS:
        return True
    # Pipeline temp outputs end in ``.mp4.part`` until they are verified.
    return (
        path.name.endswith(".part")
        and path.with_suffix("").suffix.lower() in SUPPORTED_EXTENSIONS
    )


@dataclass
class _Box:
    type: bytes
    payload: bytes | None = None
    children: list[_Box] | None = None
    prefix: bytes = b""
    header: int = 8


_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl"}
_VISUAL_ENTRY_FIELDS = 78  # SampleEntry(8) + VisualSampleEntry fields(70)
_HDR_BOXES = {b"mdcv", b"clli", b"dvcC", b"dvvC"}
_HDR_PRIMARIES = {9, 12}  # BT.2020, Display P3
_HDR_TRANSFERS = {16, 18}  # PQ, HLG
_HDR_MATRIX = {9, 10}  # BT.2020 non-constant / constant luminance

# nclx: primaries=1 (BT.709), transfer=1 (BT.709), matrix=1 (BT.709), limited range.
_REC709_NCLX = b"nclx" + struct.pack(">HHHB", 1, 1, 1, 0)


def _box_bounds(buf: bytes, start: int, end: int) -> tuple[int, int, bytes, int]:
    if start + 8 > end:
        raise ColrError("truncated box header")
    size32, typ = struct.unpack_from(">I4s", buf, start)
    header = 8
    if size32 == 1:
        if start + 16 > end:
            raise ColrError("truncated 64-bit box header")
        size = struct.unpack_from(">Q", buf, start + 8)[0]
        header = 16
    elif size32 == 0:
        size = end - start
    else:
        size = size32
    if size < header or start + size > end:
        raise ColrError(f"invalid {typ!r} box size {size}")
    return start + header, start + size, typ, header


def _parse_children(buf: bytes, start: int, end: int) -> list[_Box]:
    boxes: list[_Box] = []
    pos = start
    while pos < end:
        payload_start, box_end, typ, header = _box_bounds(buf, pos, end)
        if typ in _CONTAINERS:
            boxes.append(
                _Box(
                    typ,
                    children=_parse_children(buf, payload_start, box_end),
                    header=header,
                )
            )
        else:
            boxes.append(_Box(typ, payload=buf[payload_start:box_end], header=header))
        pos = box_end
    if pos != end:
        raise ColrError("container size mismatch")
    return boxes


def _child(box: _Box, typ: bytes) -> _Box | None:
    return next((c for c in box.children or [] if c.type == typ), None)


def _expand_stsd(stsd: _Box) -> None:
    payload = stsd.payload
    if payload is None or len(payload) < 8:
        raise ColrError("invalid stsd box")
    children: list[_Box] = []
    pos = 8
    while pos < len(payload):
        payload_start, box_end, typ, header = _box_bounds(payload, pos, len(payload))
        # VisualSampleEntry: 8 (SampleEntry) + 70 visual fields = 78 bytes.
        if payload_start + _VISUAL_ENTRY_FIELDS > box_end:
            raise ColrError(f"truncated {typ!r} sample entry")
        children.append(
            _Box(
                typ,
                children=_parse_children(
                    payload, payload_start + _VISUAL_ENTRY_FIELDS, box_end
                ),
                prefix=payload[payload_start : payload_start + _VISUAL_ENTRY_FIELDS],
                header=header,
            )
        )
        pos = box_end
    stsd.children = children
    stsd.prefix = payload[:8]
    stsd.payload = None


def _video_traks(moov: _Box) -> list[_Box]:
    found: list[_Box] = []
    for trak in moov.children or []:
        if trak.type != b"trak":
            continue
        mdia = _child(trak, b"mdia")
        if mdia is None:
            continue
        hdlr = _child(mdia, b"hdlr")
        if hdlr is None or hdlr.payload is None or len(hdlr.payload) < 12:
            continue
        if hdlr.payload[8:12] == b"vide":
            found.append(mdia)
    return found


def _nclx(payload: bytes | None) -> tuple[int, int, int] | None:
    if payload is None or len(payload) < 11 or payload[:4] != b"nclx":
        return None
    primaries, transfer, matrix = struct.unpack_from(">HHH", payload, 4)
    return primaries, transfer, matrix


def _entry_is_hdr(entry: _Box) -> bool:
    for child in entry.children or []:
        if child.type in _HDR_BOXES:
            return True
        values = _nclx(child.payload) if child.type == b"colr" else None
        if values is not None:
            primaries, transfer, matrix = values
            if primaries in _HDR_PRIMARIES:
                return True
            if transfer in _HDR_TRANSFERS:
                return True
            if matrix in _HDR_MATRIX:
                return True
    return False


def _tag_entry(entry: _Box) -> ColorStatus:
    if _entry_is_hdr(entry):
        return "skipped"
    children = entry.children or []
    existing = [c for c in children if c.type == b"colr"]
    if not existing:
        entry.children = [*children, _Box(b"colr", payload=_REC709_NCLX)]
        return "patched"
    first = existing[0]
    if _nclx(first.payload) == (1, 1, 1):
        # Drop duplicate colr boxes, keep the valid first one.
        entry.children = [c for c in children if c.type != b"colr" or c is first]
        return "unchanged"
    first.payload = _REC709_NCLX
    first.children = None
    first.prefix = b""
    entry.children = [c for c in children if c.type != b"colr" or c is first]
    return "patched"


def _scrub(box: _Box) -> int:
    if box.children is None:
        return 0
    kept: list[_Box] = []
    removed = 0
    for child in box.children:
        if child.type in (b"udta", b"meta"):
            removed += 1
            continue
        removed += _scrub(child)
        kept.append(child)
    box.children = kept
    return removed


def _serialize(box: _Box) -> bytes:
    if box.children is not None:
        payload = box.prefix + b"".join(_serialize(c) for c in box.children)
    else:
        payload = box.payload or b""
    size = box.header + len(payload)
    if box.header == 16 or size > 0xFFFFFFFF:
        return struct.pack(">I4sQ", 1, box.type, 16 + len(payload)) + payload
    return struct.pack(">I4s", size, box.type) + payload


@dataclass(frozen=True)
class _Layout:
    moov_start: int
    moov_end: int
    # (payload_start, end) for every top-level mdat, in file order.
    mdat_ranges: tuple[tuple[int, int], ...]
    fragmented: bool


def _scan_layout(src: BinaryIO) -> _Layout:
    src.seek(0, os.SEEK_END)
    total = src.tell()
    pos = 0
    moov: tuple[int, int] | None = None
    mdat_ranges: list[tuple[int, int]] = []
    fragmented = False
    while pos + 8 <= total:
        src.seek(pos)
        head = src.read(16)
        size32, typ = struct.unpack_from(">I4s", head, 0)
        header = 8
        if size32 == 1:
            if len(head) < 16:
                raise ColrError("truncated top-level box")
            size = struct.unpack_from(">Q", head, 8)[0]
            header = 16
        elif size32 == 0:
            size = total - pos
        else:
            size = size32
        if size < header or pos + size > total:
            raise ColrError(f"invalid top-level {typ!r} box size {size}")
        if typ == b"moov":
            if moov is not None:
                raise ColrError("multiple moov boxes")
            moov = (pos, pos + size)
        elif typ == b"mdat":
            mdat_ranges.append((pos + header, pos + size))
        elif typ in (b"moof", b"sidx"):
            fragmented = True
        pos += size
    if moov is None:
        raise ColrError("moov box not found")
    return _Layout(moov[0], moov[1], tuple(mdat_ranges), fragmented)


def _adjust_offsets(box: _Box, delta: int, layout: _Layout) -> None:
    """Shift only chunk offsets that point at media after the rewritten ``moov``.

    A single global shift is wrong when ``mdat`` boxes exist on both sides of
    ``moov`` (``mdat -> moov -> mdat``): offsets into the first mdat must stay put
    while offsets after the new moov move by ``delta``.
    """
    if box.children is not None:
        for child in box.children:
            _adjust_offsets(child, delta, layout)
        return
    if box.type not in (b"stco", b"co64"):
        return
    payload = bytearray(box.payload or b"")
    if len(payload) < 8:
        raise ColrError(f"invalid {box.type!r} box")
    count = struct.unpack_from(">I", payload, 4)[0]
    step = 4 if box.type == b"stco" else 8
    if len(payload) != 8 + count * step:
        raise ColrError(f"invalid {box.type!r} entry count")
    fmt = ">I" if step == 4 else ">Q"
    for index in range(count):
        offset = struct.unpack_from(fmt, payload, 8 + index * step)[0]
        if offset < layout.moov_start:
            continue  # media before moov: its bytes do not move
        if offset < layout.moov_end:
            raise ColrError(f"chunk offset {offset} points inside moov; refusing to guess")
        if not any(start <= offset < end for start, end in layout.mdat_ranges):
            raise ColrError(f"chunk offset {offset} is outside every mdat")
        shifted = offset + delta
        if shifted < 0:
            raise ColrError("chunk offset underflow while shifting moov")
        if step == 4 and shifted > 0xFFFFFFFF:
            raise ColrError("chunk offset overflow while shifting moov")
        struct.pack_into(fmt, payload, 8 + index * step, shifted)
    box.payload = bytes(payload)


def _write(src_path: Path, layout: _Layout, moov_bytes: bytes) -> None:
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{src_path.name}.", suffix=".colr.tmp", dir=src_path.parent
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with src_path.open("rb") as src, tmp.open("wb") as dst:
            remaining = layout.moov_start
            while remaining:
                chunk = src.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ColrError("unexpected EOF before moov")
                dst.write(chunk)
                remaining -= len(chunk)
            dst.write(moov_bytes)
            src.seek(layout.moov_end)
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(tmp, src_path)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        if isinstance(exc, ColrError):
            raise
        raise ColrError(f"failed to rewrite {src_path.name}: {exc}") from exc


def sanitize(
    path: Path,
    *,
    fix_color: bool = True,
    scrub_metadata: bool = True,
) -> ColrResult:
    """Add/replace Rec.709 ``nclx`` and remove ``udta``/``meta`` from ``moov``.

    Returns a result describing the color action, metadata removal count, and the
    exact ``moov`` byte delta. The original file is replaced atomically; ``mdat``
    payload bytes are preserved verbatim.
    """
    path = Path(path)
    if not path.is_file():
        raise ColrError(f"file not found: {path}")
    if not _is_supported_container(path):
        raise ColrError(f"unsupported container: {path.suffix or '(none)'}")
    if not fix_color and not scrub_metadata:
        return ColrResult(path, "unchanged", "nothing requested", 0, 0)

    with path.open("rb") as src:
        layout = _scan_layout(src)
        if layout.fragmented:
            # shortcut: fragmented MP4 is skipped, add moof/trun offset repair when needed.
            return ColrResult(path, "skipped", "fragmented MP4 is not supported", 0, 0)
        src.seek(layout.moov_start)
        moov_data = src.read(layout.moov_end - layout.moov_start)

    payload_start, _, _, header = _box_bounds(moov_data, 0, len(moov_data))
    moov = _Box(
        b"moov",
        children=_parse_children(moov_data, payload_start, len(moov_data)),
        header=header,
    )
    if _serialize(moov) != moov_data:
        raise ColrError("moov round-trip changed bytes; refusing to rewrite")

    color_status: ColorStatus = "unchanged"
    reasons: list[str] = []
    if fix_color:
        statuses: list[ColorStatus] = []
        for mdia in _video_traks(moov):
            minf = _child(mdia, b"minf")
            stbl = _child(minf, b"stbl") if minf is not None else None
            stsd = _child(stbl, b"stsd") if stbl is not None else None
            if stsd is None:
                continue
            if stsd.payload is not None:
                _expand_stsd(stsd)
            for entry in stsd.children or []:
                statuses.append(_tag_entry(entry))
        if not statuses:
            color_status = "skipped"
            reasons.append("no video sample entry")
        elif "patched" in statuses:
            color_status = "patched"
            reasons.append("Rec.709 nclx written")
        elif "skipped" in statuses:
            color_status = "skipped"
            reasons.append("HDR/BT.2020 detected; color left untouched")
        else:
            reasons.append("color already Rec.709")

    removed = _scrub(moov) if scrub_metadata else 0
    if removed:
        reasons.append(f"removed {removed} udta/meta box(es)")
    if not reasons:
        reasons.append("nothing to change")

    if color_status == "unchanged" and removed == 0:
        return ColrResult(path, "unchanged", "; ".join(reasons), 0, 0)

    new_moov = _serialize(moov)
    old_moov_size = layout.moov_end - layout.moov_start
    delta = len(new_moov) - old_moov_size
    if delta:
        _adjust_offsets(moov, delta, layout)
        new_moov = _serialize(moov)
        if len(new_moov) - old_moov_size != delta:
            raise ColrError("moov size changed while shifting offsets")

    _write(path, layout, new_moov)
    return ColrResult(path, color_status, "; ".join(reasons), delta, removed)
