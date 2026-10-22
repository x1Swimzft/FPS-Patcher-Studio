"""Lossless MP4/MOV video-track timescale patcher.

Unlike FFmpeg remuxing, this module edits only timing boxes in the existing
container. Encoded sample bytes in `mdat` are left untouched.

Supported input: conventional, non-fragmented MP4/MOV with one video track.
Fragmented files (`moof`) are rejected because their timing layout differs.
"""

from __future__ import annotations

import struct
import threading
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .errors import PatchCancelledError, PatchError

_U32_MAX = 0xFFFFFFFF


@dataclass(frozen=True)
class Box:
    start: int
    size: int
    header_size: int
    typ: bytes

    @property
    def payload_start(self) -> int:
        return self.start + self.header_size

    @property
    def end(self) -> int:
        return self.start + self.size


def _read_box(data: bytes | bytearray, pos: int, limit: int) -> Box:
    if pos + 8 > limit:
        raise PatchError(f"Invalid MP4 box header at offset {pos}.")
    size32, typ = struct.unpack_from(">I4s", data, pos)
    header = 8
    if size32 == 1:
        if pos + 16 > limit:
            raise PatchError(f"Invalid extended MP4 box header at offset {pos}.")
        size = struct.unpack_from(">Q", data, pos + 8)[0]
        header = 16
    elif size32 == 0:
        size = limit - pos
    else:
        size = size32
    if size < header or pos + size > limit:
        raise PatchError(f"Invalid MP4 box size for {typ!r} at offset {pos}.")
    return Box(pos, size, header, typ)


def _children(data: bytes | bytearray, parent: Box) -> list[Box]:
    pos = parent.payload_start
    out: list[Box] = []
    while pos < parent.end:
        box = _read_box(data, pos, parent.end)
        out.append(box)
        pos = box.end
    if pos != parent.end:
        raise PatchError(f"Malformed child boxes in {parent.typ!r}.")
    return out


def _find_children(data: bytes | bytearray, parent: Box, typ: bytes) -> list[Box]:
    return [box for box in _children(data, parent) if box.typ == typ]


def _single_child(data: bytes | bytearray, parent: Box, typ: bytes) -> Box:
    matches = _find_children(data, parent, typ)
    if not matches:
        raise PatchError(f"Required MP4 box {typ.decode(errors='replace')} not found.")
    return matches[0]


def _handler_type(data: bytes | bytearray, hdlr: Box) -> bytes:
    # FullBox(4) + pre_defined(4) + handler_type(4)
    if hdlr.size < hdlr.header_size + 12:
        raise PatchError("Malformed hdlr box.")
    return bytes(data[hdlr.payload_start + 8 : hdlr.payload_start + 12])


def _scale_int(value: int, scale: Fraction, *, signed: bool, bits: int) -> int:
    if value == -1 and signed:
        return -1
    exact = Fraction(value) * scale
    scaled = int(exact + Fraction(1, 2)) if exact >= 0 else -int(-exact + Fraction(1, 2))
    lo = -(1 << (bits - 1)) if signed else 0
    hi = (1 << (bits - 1)) - 1 if signed else (1 << bits) - 1
    if not lo <= scaled <= hi:
        raise PatchError(f"Scaled timing value {scaled} does not fit {bits}-bit field.")
    return scaled


def _scale_deltas(deltas: list[int], scale: Fraction) -> list[int]:
    """Scale per-sample durations while minimizing cumulative rounding drift."""
    out: list[int] = []
    cumulative = Fraction(0)
    prev_target = 0
    for delta in deltas:
        cumulative += Fraction(delta) * scale
        target = int(cumulative + Fraction(1, 2))
        out_delta = target - prev_target
        if out_delta <= 0:
            raise PatchError("Timescale conversion produced non-positive sample duration.")
        if out_delta > _U32_MAX:
            raise PatchError("Timescale conversion produced an oversized stts delta.")
        out.append(out_delta)
        prev_target = target
    return out


def _compress_values(values: list[int]) -> list[tuple[int, int]]:
    if not values:
        return []
    runs: list[tuple[int, int]] = []
    current = values[0]
    count = 1
    for value in values[1:]:
        if value == current and count < _U32_MAX:
            count += 1
        else:
            runs.append((count, current))
            current = value
            count = 1
    runs.append((count, current))
    return runs


def _patch_mdhd(data: bytearray, box: Box, scale: Fraction, target_ts: int) -> int:
    off = box.payload_start
    version = data[off]
    if version == 0:
        if box.size < box.header_size + 24:
            raise PatchError("Malformed version-0 mdhd box.")
        timescale_off = off + 12
        duration_off = off + 16
        old_duration = struct.unpack_from(">I", data, duration_off)[0]
        new_duration = _scale_int(old_duration, scale, signed=False, bits=32)
        struct.pack_into(">I", data, timescale_off, target_ts)
        struct.pack_into(">I", data, duration_off, new_duration)
        return int(old_duration)
    if version == 1:
        if box.size < box.header_size + 36:
            raise PatchError("Malformed version-1 mdhd box.")
        timescale_off = off + 20
        duration_off = off + 24
        old_duration = struct.unpack_from(">Q", data, duration_off)[0]
        new_duration = _scale_int(old_duration, scale, signed=False, bits=64)
        struct.pack_into(">I", data, timescale_off, target_ts)
        struct.pack_into(">Q", data, duration_off, new_duration)
        return int(old_duration)
    raise PatchError(f"Unsupported mdhd version {version}.")


def _patch_stts(data: bytearray, box: Box, scale: Fraction) -> None:
    off = box.payload_start
    if box.size < box.header_size + 8:
        raise PatchError("Malformed stts box.")
    count = struct.unpack_from(">I", data, off + 4)[0]
    pos = off + 8
    end = box.end
    if pos + count * 8 != end:
        raise PatchError("Malformed stts entry count.")

    deltas: list[int] = []
    # Every sample occupies at least one byte of the file, so a larger total is a
    # malformed/hostile table (prevents multi-GB list expansion).
    max_samples = len(data)
    for _ in range(count):
        sample_count, delta = struct.unpack_from(">II", data, pos)
        if sample_count == 0:
            raise PatchError("stts contains zero-length run.")
        if len(deltas) + sample_count > max_samples:
            raise PatchError("stts sample count exceeds file size.")
        deltas.extend([delta] * sample_count)
        pos += 8

    scaled = _scale_deltas(deltas, scale)
    runs = _compress_values(scaled)
    new_payload = bytearray(8 + 8 * len(runs))
    struct.pack_into(">B3sI", new_payload, 0, data[off], bytes(data[off + 1 : off + 4]), len(runs))
    pos = 8
    for run_count, delta in runs:
        struct.pack_into(">II", new_payload, pos, run_count, delta)
        pos += 8
    if len(new_payload) > box.size - box.header_size:
        raise PatchError("stts expansion exceeds original box capacity.")
    # Preserve box size. Pad unused payload with zeros only if ever needed.
    start = box.payload_start
    old_payload_len = box.size - box.header_size
    data[start : start + old_payload_len] = new_payload + bytes(old_payload_len - len(new_payload))


def _patch_ctts(data: bytearray, box: Box, scale: Fraction) -> None:
    off = box.payload_start
    if box.size < box.header_size + 8:
        raise PatchError("Malformed ctts box.")
    version = data[off]
    if version not in (0, 1):
        raise PatchError(f"Unsupported ctts version {version}.")
    count = struct.unpack_from(">I", data, off + 4)[0]
    pos = off + 8
    end = box.end
    if pos + count * 8 != end:
        raise PatchError("Malformed ctts entry count.")

    for _ in range(count):
        sample_count = struct.unpack_from(">I", data, pos)[0]
        if sample_count == 0:
            raise PatchError("ctts contains zero-length run.")
        raw = struct.unpack_from(">i", data, pos + 4)[0]
        scaled = _scale_int(raw, scale, signed=True, bits=32)
        struct.pack_into(">i", data, pos + 4, scaled)
        pos += 8


def _patch_elst(
    data: bytearray,
    box: Box,
    scale: Fraction,
    movie_scale: Fraction | None = None,
) -> None:
    off = box.payload_start
    version = data[off]
    count = struct.unpack_from(">I", data, off + 4)[0]
    pos = off + 8
    entry_size = 20 if version == 1 else 12
    if pos + count * entry_size != box.end:
        raise PatchError("Malformed elst entry count.")
    for _ in range(count):
        if version == 1:
            if movie_scale is not None:
                seg_dur = struct.unpack_from(">q", data, pos)[0]
                new_seg_dur = _scale_int(seg_dur, movie_scale, signed=True, bits=64)
                struct.pack_into(">q", data, pos, new_seg_dur)
            media_time = struct.unpack_from(">q", data, pos + 8)[0]
            new_media_time = _scale_int(media_time, scale, signed=True, bits=64)
            struct.pack_into(">q", data, pos + 8, new_media_time)
        else:
            if movie_scale is not None:
                seg_dur = struct.unpack_from(">i", data, pos)[0]
                new_seg_dur = _scale_int(seg_dur, movie_scale, signed=True, bits=32)
                struct.pack_into(">i", data, pos, new_seg_dur)
            media_time = struct.unpack_from(">i", data, pos + 4)[0]
            new_media_time = _scale_int(media_time, scale, signed=True, bits=32)
            struct.pack_into(">i", data, pos + 4, new_media_time)
        pos += entry_size


def patch_video_track_timescale(
    src: Path,
    out: Path,
    target_timescale: int,
    cancel_event: threading.Event | None = None,
) -> None:
    if target_timescale <= 0:
        raise PatchError("Timescale must be a positive integer.")
    if src.resolve() == out.resolve():
        raise PatchError(f"Output path equals source file ('{src}'); refusing in-place overwrite.")
    raw = src.read_bytes()
    data = bytearray(raw)
    top: list[Box] = []
    pos = 0
    while pos < len(data):
        if pos + 8 > len(data):
            if any(b.typ in (b"moov", b"mdat") for b in top):
                break
            raise PatchError(f"Invalid MP4 box header at offset {pos}.")
        try:
            box = _read_box(data, pos, len(data))
        except PatchError:
            if any(b.typ in (b"moov", b"mdat") for b in top):
                break
            raise
        top.append(box)
        pos = box.end

    if any(box.typ == b"moof" for box in top):
        raise PatchError("Fragmented MP4/MOV (moof) is not supported by Direct Atom Method.")

    moov = next((box for box in top if box.typ == b"moov"), None)
    if moov is None:
        raise PatchError("moov box not found; not a standard MP4/MOV container.")

    video_trak: Box | None = None
    mdia: Box | None = None
    for trak in _find_children(data, moov, b"trak"):
        try:
            trak_mdia = _single_child(data, trak, b"mdia")
            hdlr = _single_child(data, trak_mdia, b"hdlr")
            if _handler_type(data, hdlr) == b"vide":
                if video_trak is not None:
                    raise PatchError(
                        "Multiple video tracks are not supported by Direct Atom Method."
                    )
                video_trak = trak
                mdia = trak_mdia
        except PatchError:
            continue

    if video_trak is None or mdia is None:
        raise PatchError("Video track not found.")

    mdhd = _single_child(data, mdia, b"mdhd")
    off = mdhd.payload_start
    version = data[off]
    old_ts_off = off + 12 if version == 0 else off + 20 if version == 1 else None
    if old_ts_off is None:
        raise PatchError(f"Unsupported mdhd version {version}.")
    old_timescale = struct.unpack_from(">I", data, old_ts_off)[0]
    if old_timescale <= 0:
        raise PatchError("Source video timescale is invalid.")
    if old_timescale == target_timescale:
        out.write_bytes(raw)
        return

    scale = Fraction(target_timescale, old_timescale)
    _patch_mdhd(data, mdhd, scale, target_timescale)

    edts_list = _find_children(data, video_trak, b"edts")
    for edts in edts_list:
        for elst in _find_children(data, edts, b"elst"):
            _patch_elst(data, elst, scale)

    minf = _single_child(data, mdia, b"minf")
    stbl = _single_child(data, minf, b"stbl")
    for stts in _find_children(data, stbl, b"stts"):
        _patch_stts(data, stts, scale)
    for ctts in _find_children(data, stbl, b"ctts"):
        _patch_ctts(data, ctts, scale)

    if cancel_event is not None and cancel_event.is_set():
        raise PatchCancelledError("Patch cancelled by user.")

    # Atomic write to temporary file first
    tmp = out.with_name(out.name + ".tmp_direct")
    try:
        tmp.write_bytes(data)
        # Post-patch minimal structural verification
        from .verifier import verify_atom_structure

        res = verify_atom_structure(tmp)
        if not res.is_valid:
            tmp.unlink(missing_ok=True)
            raise PatchError(f"Post-patch structural verification failed: {'; '.join(res.details)}")
        tmp.replace(out)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
