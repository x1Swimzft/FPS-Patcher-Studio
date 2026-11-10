"""X1T Zilem: container-only MP4 patch with no video or audio re-encode.

The patcher copies the source file byte-for-byte, converts the old ``moov``
box into a ``free`` box, appends a 17-frame AAC silence ``mdat`` and writes a
rebuilt ``moov`` at the end. The rebuilt movie keeps the original video sample
tables and adds a second audio track that shares the original audio chunks.

This reproduces the Zilem v1 container fingerprint:

* one H.264 video track, unchanged sample data and sample tables;
* one original AAC-LC 48 kHz stereo track extended by 17 silent frames;
* a duplicate audio track (same chunks, no extra media bytes);
* a ``udta/meta/ilst`` tag inside the video track;
* ``mvhd`` and audio durations extended by the appended 0.3627 s;
* no trailing custom box, unless the reference-exact preset asks for one.

The method is deliberately strict about its input. It never calls FFmpeg and
never re-encodes media.
"""

from __future__ import annotations

import copy
import hashlib
import mmap
import os
import struct
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .errors import PatchCancelledError, PatchError, VerifyError

ZILEM_TAG = "X1T Zilem v1"
PRODUCTION_TAG = ZILEM_TAG
# The tag and trailer written by the original reference method. Only the
# reference-exact preset uses these; the default preset stays neutral.
REFERENCE_TAG = "TikQuick Quality Method - https://tikquick.online/ - v25 - Orion"
ZETA_TRAILER_PREFIX = "ZETA_OPTIMIZED/3"

# A 6-byte AAC-LC frame used by the reference method for silent padding.
SILENCE_FRAME = bytes.fromhex("211004608c1c")
APPENDED_SAMPLES = 17
APPENDED_CHUNK_SIZES: tuple[int, int] = (9, 8)
AUDIO_FRAME_SAMPLES = 1024
NEW_TRACK_DESCRIPTION = b"\x11\x80\x04\xc0\x40\x00\x20\x00"
REQUIRED_AAC_ASC = b"\x11\x90"  # AAC-LC, 48 kHz, stereo core config
_MDAT2_SIZE = 8 + len(SILENCE_FRAME) * APPENDED_SAMPLES
_COPY_CHUNK = 1024 * 1024
_MAX_STCO_OFFSET = 0xFFFFFFFF

_CONTAINER_TYPES = frozenset(
    {
        b"moov",
        b"trak",
        b"mdia",
        b"minf",
        b"stbl",
        b"edts",
        b"udta",
        b"ilst",
        b"\xa9too",
    }
)
_VIDEO_CODECS = {
    b"avc1": "h264",
    b"avc3": "h264",
    b"hvc1": "hevc",
    b"hev1": "hevc",
    b"av01": "av1",
    b"vp09": "vp9",
    b"mp4v": "mpeg4",
}

_Buffer = bytes | mmap.mmap


class ZilemSourceError(PatchError):
    """The source container is not compatible with X1T Zilem."""


@dataclass
class _Atom:
    """A parsed ISO-BMFF box. Containers keep children; leaves keep payload."""

    type: bytes
    data: bytes = b""
    children: list[_Atom] | None = None
    prefix: bytes = b""

    def payload(self) -> bytes:
        if self.children is None:
            return self.data
        return self.prefix + b"".join(child.to_bytes() for child in self.children)

    def to_bytes(self) -> bytes:
        payload = self.payload()
        return struct.pack(">I4s", 8 + len(payload), self.type) + payload

    def find(self, atom_type: bytes) -> _Atom | None:
        if self.children is None:
            return None
        for child in self.children:
            if child.type == atom_type:
                return child
        return None

    def require(self, atom_type: bytes) -> _Atom:
        found = self.find(atom_type)
        if found is None:
            raise ZilemSourceError(
                f"missing '{atom_type.decode('latin1')}' box inside "
                f"'{self.type.decode('latin1')}'"
            )
        return found


@dataclass(frozen=True)
class _Entry:
    """A sample description entry, kept as its 8-byte box header plus body."""

    type: bytes
    body: bytes

    @property
    def raw(self) -> bytes:
        return struct.pack(">I4s", 8 + len(self.body), self.type) + self.body


@dataclass(frozen=True)
class ZilemSourceInfo:
    """Facts about a validated Zilem source."""

    path: Path
    video_codec: str
    audio_codec: str
    audio_sample_rate: int
    audio_channels: int
    audio_samples: int
    audio_chunks: int
    video_samples: int
    movie_timescale: int
    audio_timescale: int
    track_ids: tuple[int, ...]


@dataclass(frozen=True)
class ZilemStats:
    """Result metrics for one Zilem build."""

    source_size: int
    output_size: int
    moov_size: int
    video_samples: int
    audio_samples_before: int
    audio_samples_after: int
    audio_chunks_before: int
    audio_chunks_after: int
    new_track_id: int
    movie_duration: int
    tag: str
    trailer: bytes = b""


@dataclass(frozen=True)
class _Structure:
    size: int
    top: tuple[tuple[int, int, int, bytes], ...]
    moov_offset: int
    moov_size: int
    moov: _Atom


def _read_header(buf: _Buffer, start: int, end: int) -> tuple[int, bytes, int]:
    if start + 8 > end:
        raise ZilemSourceError("truncated MP4 box header")
    size32, atom_type = struct.unpack_from(">I4s", buf, start)
    header = 8
    if size32 == 1:
        if start + 16 > end:
            raise ZilemSourceError("truncated 64-bit MP4 box header")
        size = struct.unpack_from(">Q", buf, start + 8)[0]
        header = 16
    elif size32 == 0:
        size = end - start
    else:
        size = size32
    if size < header or start + size > end:
        raise ZilemSourceError(
            f"invalid MP4 box '{atom_type.decode('latin1')}' at offset {start}"
        )
    return size, atom_type, header


def _iter_atoms(
    buf: _Buffer, start: int, end: int
) -> Iterator[tuple[int, int, int, bytes]]:
    position = start
    while position + 8 <= end:
        size, atom_type, header = _read_header(buf, position, end)
        yield position, size, header, atom_type
        position += size


def _parse_children(data: bytes, start: int, end: int) -> list[_Atom]:
    children: list[_Atom] = []
    for position, size, header, atom_type in _iter_atoms(data, start, end):
        payload = data[position + header : position + size]
        if atom_type == b"meta":
            children.append(
                _Atom(
                    atom_type,
                    prefix=payload[:4],
                    children=_parse_children(payload, 4, len(payload)),
                )
            )
        elif atom_type in _CONTAINER_TYPES:
            children.append(
                _Atom(
                    atom_type,
                    children=_parse_children(payload, 0, len(payload)),
                )
            )
        else:
            children.append(_Atom(atom_type, data=payload))
    return children


def _read_structure(path: Path) -> _Structure:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ZilemSourceError(f"cannot read source: {exc}") from exc
    if size < 8:
        raise ZilemSourceError("source is too small to be an MP4 file")
    try:
        with (
            path.open("rb") as handle,
            mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
        ):
            top = tuple(_iter_atoms(mapped, 0, size))
            moovs = [item for item in top if item[3] == b"moov"]
            if not moovs:
                raise ZilemSourceError(
                    "no moov box found; this is not a non-fragmented MP4"
                )
            if len(moovs) > 1:
                raise ZilemSourceError("multiple moov boxes are not supported")
            if any(item[3] == b"moof" for item in top):
                raise ZilemSourceError(
                    "fragmented MP4 is not supported; remux it to a regular MP4 first"
                )
            if not any(item[3] == b"mdat" for item in top):
                raise ZilemSourceError("no mdat box found; the MP4 has no media data")
            moov_offset, moov_size, _, _ = moovs[0]
            moov_bytes = mapped[moov_offset : moov_offset + moov_size]
    except OSError as exc:
        raise ZilemSourceError(f"cannot read source: {exc}") from exc
    return _Structure(
        size=size,
        top=top,
        moov_offset=moov_offset,
        moov_size=moov_size,
        moov=_parse_tree(moov_bytes),
    )


def _parse_tree(data: bytes) -> _Atom:
    if len(data) < 8:
        raise ZilemSourceError("moov box is truncated")
    size, atom_type, header = _read_header(data, 0, len(data))
    payload = data[header:size]
    if atom_type == b"meta":
        return _Atom(
            atom_type,
            prefix=payload[:4],
            children=_parse_children(payload, 4, len(payload)),
        )
    if atom_type in _CONTAINER_TYPES:
        return _Atom(
            atom_type,
            children=_parse_children(payload, 0, len(payload)),
        )
    return _Atom(atom_type, data=payload)


def _handler_type(trak: _Atom) -> bytes:
    hdlr = trak.require(b"mdia").require(b"hdlr")
    if len(hdlr.data) < 12:
        raise ZilemSourceError("malformed hdlr box")
    return hdlr.data[8:12]


def _stsd_entries(stsd: _Atom) -> list[_Entry]:
    if len(stsd.data) < 8:
        raise ZilemSourceError("malformed stsd box")
    count = struct.unpack_from(">I", stsd.data, 4)[0]
    entries: list[_Entry] = []
    position = 8
    for _ in range(count):
        if position + 8 > len(stsd.data):
            raise ZilemSourceError("stsd entry table is truncated")
        size, entry_type = struct.unpack_from(">I4s", stsd.data, position)
        if size < 8 or position + size > len(stsd.data):
            raise ZilemSourceError("invalid stsd sample entry")
        entries.append(
            _Entry(entry_type, stsd.data[position + 8 : position + size])
        )
        position += size
    return entries


def _find_child_box(body: bytes, start: int, atom_type: bytes) -> tuple[int, int] | None:
    for position, size, _, found_type in _iter_atoms(body, start, len(body)):
        if found_type == atom_type:
            return position, size
    return None


def _read_descriptor(data: bytes, position: int) -> tuple[int, bytes, int]:
    if position >= len(data):
        raise ZilemSourceError("truncated ESDS descriptor")
    tag = data[position]
    position += 1
    length = 0
    for _ in range(4):
        if position >= len(data):
            raise ZilemSourceError("truncated ESDS descriptor length")
        byte = data[position]
        position += 1
        length = (length << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return tag, data[position : position + length], position + length
    raise ZilemSourceError("unsupported ESDS descriptor length encoding")


def _esds_audio_specific_config(entry: _Entry) -> bytes:
    found = _find_child_box(entry.body, 28, b"esds")
    if found is None:
        raise ZilemSourceError("AAC sample entry has no esds box")
    offset, size = found
    esds = entry.body[offset : offset + size]
    if len(esds) < 12 or esds[4:8] != b"esds":
        raise ZilemSourceError("malformed esds box")
    descriptors = esds[12:]
    tag3, payload3, _ = _read_descriptor(descriptors, 0)
    if tag3 != 3:
        raise ZilemSourceError("unsupported ESDS layout (missing ES_Descriptor)")
    tag4, payload4, _ = _read_descriptor(payload3, 3)
    if tag4 != 4:
        raise ZilemSourceError(
            "unsupported ESDS layout (missing DecoderConfigDescriptor)"
        )
    tag5, asc, _ = _read_descriptor(payload4, 13)
    if tag5 != 5:
        raise ZilemSourceError(
            "unsupported ESDS layout (missing DecSpecificInfo)"
        )
    return asc


def _is_aac_lc_48k_stereo(asc: bytes) -> bool:
    """True for an AAC-LC, 48 kHz, stereo AudioSpecificConfig header.

    FFmpeg may append a sync-extension tail to the two-byte core config; the
    first 13 bits still describe the stream the Zilem transform needs.
    """
    if len(asc) < 2:
        return False
    value = (asc[0] << 8) | asc[1]
    audio_object_type = value >> 11
    frequency_index = (value >> 7) & 0x0F
    channel_configuration = (value >> 3) & 0x0F
    return (
        audio_object_type == 2
        and frequency_index == 3
        and channel_configuration == 2
    )


def _encode_descriptor(tag: int, payload: bytes) -> bytes:
    length = len(payload)
    if length > 0x0FFFFFFF:
        raise ZilemSourceError("ESDS descriptor is too large")
    return bytes(
        [
            tag,
            0x80 | ((length >> 21) & 0x7F),
            0x80 | ((length >> 14) & 0x7F),
            0x80 | ((length >> 7) & 0x7F),
            length & 0x7F,
        ]
    ) + payload


def _alternate_entry(entry: _Entry) -> _Entry:
    """Build the second AAC sample entry used by the Zilem audio track."""
    found = _find_child_box(entry.body, 28, b"esds")
    if found is None:
        raise ZilemSourceError("AAC sample entry has no esds box")
    offset, size = found
    esds = entry.body[offset : offset + size]
    if len(esds) < 12 or esds[4:8] != b"esds":
        raise ZilemSourceError("malformed esds box")
    descriptors = esds[12:]
    tag3, payload3, _ = _read_descriptor(descriptors, 0)
    if tag3 != 3:
        raise ZilemSourceError("unsupported ESDS layout (missing ES_Descriptor)")
    tag4, payload4, _ = _read_descriptor(payload3, 3)
    if tag4 != 4:
        raise ZilemSourceError(
            "unsupported ESDS layout (missing DecoderConfigDescriptor)"
        )
    tag5, asc, _ = _read_descriptor(payload4, 13)
    if tag5 != 5:
        raise ZilemSourceError(
            "unsupported ESDS layout (missing DecSpecificInfo)"
        )
    if not _is_aac_lc_48k_stereo(asc):
        raise ZilemSourceError(
            "X1T Zilem requires AAC-LC 48 kHz stereo audio "
            f"(found AudioSpecificConfig {asc.hex()})"
        )
    descriptor_4_length = len(payload4)
    tail = payload3[3 + 5 + descriptor_4_length :]
    new_decoder_payload = (
        payload4[:13] + _encode_descriptor(5, NEW_TRACK_DESCRIPTION)
    )
    new_es_payload = (
        payload3[:3]
        + _encode_descriptor(4, new_decoder_payload)
        + tail
    )
    new_descriptors = _encode_descriptor(3, new_es_payload)
    new_esds = (
        struct.pack(">I4s", 12 + len(new_descriptors), b"esds")
        + b"\x00\x00\x00\x00"
        + new_descriptors
    )
    new_body = entry.body[:offset] + new_esds + entry.body[offset + size :]
    return _Entry(entry.type, new_body)


def _u32(data: bytes, offset: int) -> int:
    return int(struct.unpack_from(">I", data, offset)[0])


def _u64(data: bytes, offset: int) -> int:
    return int(struct.unpack_from(">Q", data, offset)[0])


def _patch_u32(atom: _Atom, offset: int, value: int) -> None:
    data = bytearray(atom.data)
    struct.pack_into(">I", data, offset, value)
    atom.data = bytes(data)


def _patch_u64(atom: _Atom, offset: int, value: int) -> None:
    data = bytearray(atom.data)
    struct.pack_into(">Q", data, offset, value)
    atom.data = bytes(data)


def _tkhd_duration(trak: _Atom) -> int:
    tkhd = trak.require(b"tkhd")
    version = tkhd.data[0]
    if version == 0:
        return _u32(tkhd.data, 20)
    if version == 1:
        return _u64(tkhd.data, 28)
    raise ZilemSourceError(f"unsupported tkhd version {version}")


def _tkhd_track_id(trak: _Atom) -> int:
    tkhd = trak.require(b"tkhd")
    version = tkhd.data[0]
    if version == 0:
        return _u32(tkhd.data, 12)
    if version == 1:
        return _u32(tkhd.data, 20)
    raise ZilemSourceError(f"unsupported tkhd version {version}")


def _patch_tkhd(tkhd: _Atom, track_id: int, duration: int) -> None:
    version = tkhd.data[0]
    if version == 0:
        _patch_u32(tkhd, 12, track_id)
        _patch_u32(tkhd, 20, duration)
    elif version == 1:
        _patch_u32(tkhd, 20, track_id)
        _patch_u64(tkhd, 28, duration)
    else:
        raise ZilemSourceError(f"unsupported tkhd version {version}")


def _mdhd_timing(mdhd: _Atom) -> tuple[int, int]:
    version = mdhd.data[0]
    if version == 0:
        return _u32(mdhd.data, 12), _u32(mdhd.data, 16)
    if version == 1:
        return _u32(mdhd.data, 20), _u64(mdhd.data, 24)
    raise ZilemSourceError(f"unsupported mdhd version {version}")


def _patch_mdhd(mdhd: _Atom, duration: int) -> None:
    version = mdhd.data[0]
    if version == 0:
        _patch_u32(mdhd, 16, duration)
    elif version == 1:
        _patch_u64(mdhd, 24, duration)
    else:
        raise ZilemSourceError(f"unsupported mdhd version {version}")


def _patch_elst(elst: _Atom, duration: int) -> None:
    version = elst.data[0]
    if version == 0:
        _patch_u32(elst, 8, duration)
    elif version == 1:
        _patch_u64(elst, 8, duration)
    else:
        raise ZilemSourceError(f"unsupported elst version {version}")


def _mvhd_info(mvhd: _Atom) -> tuple[int, int, int]:
    version = mvhd.data[0]
    if version == 0:
        return _u32(mvhd.data, 12), _u32(mvhd.data, 16), _u32(mvhd.data, 96)
    if version == 1:
        return _u32(mvhd.data, 20), _u64(mvhd.data, 24), _u32(mvhd.data, 108)
    raise ZilemSourceError(f"unsupported mvhd version {version}")


def _is_indeterminate_movie_duration(mvhd: _Atom, duration: int) -> bool:
    """True for the all-ones duration some PC patchers write."""
    version = mvhd.data[0]
    if version == 0:
        return duration == 0xFFFFFFFF
    if version == 1:
        return duration == 0xFFFFFFFFFFFFFFFF
    return False


def _patch_mvhd(mvhd: _Atom, duration: int, next_track_id: int) -> None:
    version = mvhd.data[0]
    if version == 0:
        _patch_u32(mvhd, 16, duration)
        _patch_u32(mvhd, 96, next_track_id)
    elif version == 1:
        _patch_u64(mvhd, 24, duration)
        _patch_u32(mvhd, 108, next_track_id)
    else:
        raise ZilemSourceError(f"unsupported mvhd version {version}")


def _audio_sample_entry(trak: _Atom) -> _Entry:
    stsd = trak.require(b"mdia").require(b"minf").require(b"stbl").require(b"stsd")
    entries = _stsd_entries(stsd)
    if len(entries) != 1:
        raise ZilemSourceError(
            "X1T Zilem needs a single AAC audio sample description; "
            f"found {len(entries)}"
        )
    return entries[0]


def _validate_source(structure: _Structure) -> ZilemSourceInfo:
    moov = structure.moov
    if moov.find(b"mvex") is not None:
        raise ZilemSourceError(
            "fragmented MP4 is not supported; remux it to a regular MP4 first"
        )
    if moov.find(b"mvhd") is None:
        raise ZilemSourceError("moov has no mvhd box")
    traks = [child for child in moov.children or [] if child.type == b"trak"]
    video_traks = [trak for trak in traks if _handler_type(trak) == b"vide"]
    audio_traks = [trak for trak in traks if _handler_type(trak) == b"soun"]
    if not video_traks:
        raise ZilemSourceError("no video track found")
    if len(video_traks) > 1:
        raise ZilemSourceError(
            "X1T Zilem supports one video track; "
            f"found {len(video_traks)}"
        )
    if not audio_traks:
        raise ZilemSourceError(
            "no audio track found; X1T Zilem needs one AAC-LC 48 kHz stereo track"
        )
    if len(audio_traks) > 1:
        raise ZilemSourceError(
            "X1T Zilem supports one audio track; "
            f"found {len(audio_traks)}"
        )

    video = video_traks[0]
    audio = audio_traks[0]
    video_stsd = (
        video.require(b"mdia").require(b"minf").require(b"stbl").require(b"stsd")
    )
    video_entries = _stsd_entries(video_stsd)
    if not video_entries:
        raise ZilemSourceError("video track has no sample description")
    video_codec = _VIDEO_CODECS.get(video_entries[0].type, "unknown")
    if video_codec != "h264":
        found = video_entries[0].type.decode("latin1", errors="replace")
        raise ZilemSourceError(
            f"X1T Zilem requires an H.264 video track; found '{found}' "
            "(convert HEVC/AV1 sources to H.264 first)"
        )

    entry = _audio_sample_entry(audio)
    if entry.type != b"mp4a":
        found = entry.type.decode("latin1", errors="replace")
        raise ZilemSourceError(
            f"X1T Zilem requires AAC audio; found '{found}'"
        )
    if len(entry.body) < 28:
        raise ZilemSourceError("malformed AAC sample entry")
    channels = struct.unpack_from(">H", entry.body, 16)[0]
    sample_rate = struct.unpack_from(">I", entry.body, 24)[0] >> 16
    if channels != 2 or sample_rate != 48000:
        raise ZilemSourceError(
            "X1T Zilem requires AAC-LC 48 kHz stereo audio; "
            f"found {sample_rate} Hz, {channels} channel(s)"
        )
    asc = _esds_audio_specific_config(entry)
    if not _is_aac_lc_48k_stereo(asc):
        raise ZilemSourceError(
            "X1T Zilem requires AAC-LC 48 kHz stereo audio "
            f"(found AudioSpecificConfig {asc.hex()})"
        )

    stbl = audio.require(b"mdia").require(b"minf").require(b"stbl")
    stsz = stbl.require(b"stsz")
    sample_size, sample_count = struct.unpack_from(">II", stsz.data, 4)
    if sample_size != 0:
        raise ZilemSourceError(
            "fixed-size audio sample tables are not supported by X1T Zilem"
        )
    if sample_count < 1:
        raise ZilemSourceError("audio track has no samples")
    stco = stbl.require(b"stco")
    chunk_count = _u32(stco.data, 4)
    if chunk_count < 1:
        raise ZilemSourceError("audio track has no chunks")
    if structure.size + 8 > _MAX_STCO_OFFSET:
        raise ZilemSourceError(
            "source is too large for the 32-bit chunk offsets used by X1T Zilem"
        )

    mvhd = moov.require(b"mvhd")
    movie_timescale, _, _ = _mvhd_info(mvhd)
    audio_timescale, audio_duration = _mdhd_timing(
        audio.require(b"mdia").require(b"mdhd")
    )
    if audio_timescale <= 0 or audio_duration <= 0:
        raise ZilemSourceError("audio track has an invalid timescale or duration")

    video_stbl = video.require(b"mdia").require(b"minf").require(b"stbl")
    video_stsz = video_stbl.require(b"stsz")
    video_sample_size, video_samples = struct.unpack_from(">II", video_stsz.data, 4)
    if video_sample_size != 0 or video_samples < 1:
        raise ZilemSourceError("video track has an unsupported sample table")

    track_ids = tuple(_tkhd_track_id(trak) for trak in traks)
    return ZilemSourceInfo(
        path=Path(),
        video_codec=video_codec,
        audio_codec="aac",
        audio_sample_rate=sample_rate,
        audio_channels=channels,
        audio_samples=sample_count,
        audio_chunks=chunk_count,
        video_samples=video_samples,
        movie_timescale=movie_timescale,
        audio_timescale=audio_timescale,
        track_ids=track_ids,
    )


def inspect_zilem_source(path: Path) -> ZilemSourceInfo:
    """Validate a Zilem source and return its container facts."""
    structure = _read_structure(path)
    info = _validate_source(structure)
    return ZilemSourceInfo(
        path=path,
        video_codec=info.video_codec,
        audio_codec=info.audio_codec,
        audio_sample_rate=info.audio_sample_rate,
        audio_channels=info.audio_channels,
        audio_samples=info.audio_samples,
        audio_chunks=info.audio_chunks,
        video_samples=info.video_samples,
        movie_timescale=info.movie_timescale,
        audio_timescale=info.audio_timescale,
        track_ids=info.track_ids,
    )


def _build_tag_metadata(text: str) -> _Atom:
    hdlr = _Atom(
        b"hdlr",
        data=b"\x00" * 8 + b"mdir" + b"\x00" * 12 + b"\x00",
    )
    data = _Atom(
        b"data",
        data=struct.pack(">II", 1, 0) + text.encode("utf-8") + b"\x00",
    )
    too = _Atom(b"\xa9too", children=[data])
    ilst = _Atom(b"ilst", children=[too])
    meta = _Atom(b"meta", prefix=b"\x00\x00\x00\x00", children=[hdlr, ilst])
    return _Atom(b"udta", children=[meta])


def _replace_tag_item(ilst: _Atom, text: str) -> None:
    new_too = _build_tag_metadata(text).require(b"meta").require(b"ilst").require(
        b"\xa9too"
    )
    if ilst.children is None:
        ilst.children = []
    for index, child in enumerate(ilst.children):
        if child.type == b"\xa9too":
            ilst.children[index] = new_too
            return
    ilst.children.append(new_too)


def _apply_video_tag(trak: _Atom, text: str) -> None:
    """Attach the Zilem tag without discarding existing track metadata."""
    if trak.children is None:
        trak.children = []
    udta = trak.find(b"udta")
    if udta is None:
        trak.children.append(_build_tag_metadata(text))
        return
    meta = udta.find(b"meta")
    if meta is None:
        meta = _build_tag_metadata(text).require(b"udta").require(b"meta")
        if udta.children is None:
            udta.children = []
        udta.children.append(meta)
        return
    ilst = meta.find(b"ilst")
    if ilst is None:
        ilst = _build_tag_metadata(text).require(b"udta").require(b"meta").require(
            b"ilst"
        )
        if meta.children is None:
            meta.children = []
        meta.children.append(ilst)
        return
    _replace_tag_item(ilst, text)


def _rebuild_stts(stbl: _Atom) -> None:
    stts = stbl.require(b"stts")
    version_flags = stts.data[:4]
    count = _u32(stts.data, 4)
    entries: list[tuple[int, int]] = []
    position = 8
    for _ in range(count):
        if position + 8 > len(stts.data):
            raise ZilemSourceError("stts table is truncated")
        entries.append(struct.unpack_from(">II", stts.data, position))
        position += 8
    if not entries:
        raise ZilemSourceError("audio stts table is empty")
    sample_count, delta = entries[-1]
    if delta == AUDIO_FRAME_SAMPLES:
        entries[-1] = (sample_count + APPENDED_SAMPLES, delta)
    else:
        entries.append((APPENDED_SAMPLES, AUDIO_FRAME_SAMPLES))
    body = version_flags + struct.pack(">I", len(entries))
    body += b"".join(struct.pack(">II", *item) for item in entries)
    stts.data = body


def _rebuild_stsc(stbl: _Atom, chunk_count: int, *, clone: bool) -> None:
    stsc = stbl.require(b"stsc")
    version_flags = stsc.data[:4]
    count = _u32(stsc.data, 4)
    entries: list[tuple[int, int, int]] = []
    position = 8
    for _ in range(count):
        if position + 12 > len(stsc.data):
            raise ZilemSourceError("stsc table is truncated")
        entries.append(struct.unpack_from(">III", stsc.data, position))
        position += 12
    entries.append((chunk_count + 1, APPENDED_CHUNK_SIZES[0], 1))
    entries.append(
        (
            chunk_count + 2,
            APPENDED_CHUNK_SIZES[1],
            1 if clone else 2,
        )
    )
    body = version_flags + struct.pack(">I", len(entries))
    body += b"".join(struct.pack(">III", *item) for item in entries)
    stsc.data = body


def _rebuild_stsz(stbl: _Atom) -> None:
    stsz = stbl.require(b"stsz")
    version_flags = stsz.data[:4]
    sample_size, count = struct.unpack_from(">II", stsz.data, 4)
    if sample_size != 0:
        raise ZilemSourceError(
            "fixed-size audio sample tables are not supported by X1T Zilem"
        )
    if len(stsz.data) < 12 + count * 4:
        raise ZilemSourceError("stsz table is truncated")
    body = (
        version_flags
        + struct.pack(">II", sample_size, count + APPENDED_SAMPLES)
        + stsz.data[12 : 12 + count * 4]
        + struct.pack(">I", len(SILENCE_FRAME)) * APPENDED_SAMPLES
    )
    stsz.data = body


def _rebuild_stco(stbl: _Atom, new_offsets: tuple[int, int]) -> None:
    stco = stbl.require(b"stco")
    version_flags = stco.data[:4]
    count = _u32(stco.data, 4)
    if len(stco.data) < 8 + count * 4:
        raise ZilemSourceError("stco table is truncated")
    body = (
        version_flags
        + struct.pack(">I", count + 2)
        + stco.data[8 : 8 + count * 4]
        + struct.pack(">II", *new_offsets)
    )
    stco.data = body


def _make_roll_sgpd() -> _Atom:
    return _Atom(
        b"sgpd",
        data=(
            struct.pack(">I", 1)
            + b"roll"
            + struct.pack(">I", 2)
            + struct.pack(">I", 1)
            + b"\xff\xff"
        ),
    )


def _make_roll_sbgp(sample_count: int) -> _Atom:
    return _Atom(
        b"sbgp",
        data=(
            struct.pack(">I", 0)
            + b"roll"
            + struct.pack(">I", 2)
            + struct.pack(">III", sample_count, 1, APPENDED_SAMPLES)
            + struct.pack(">I", 0)
        ),
    )


def _rebuild_audio_groups(stbl: _Atom, sample_count: int) -> None:
    sgpd = None
    for child in stbl.children or []:
        if (
            child.type == b"sgpd"
            and len(child.data) >= 8
            and child.data[4:8] == b"roll"
        ):
            sgpd = child
            break
    if sgpd is None:
        if stbl.children is None:
            stbl.children = []
        stbl.children.append(_make_roll_sgpd())

    sbgp = None
    for child in stbl.children or []:
        if (
            child.type == b"sbgp"
            and len(child.data) >= 8
            and child.data[4:8] == b"roll"
        ):
            sbgp = child
            break
    if sbgp is None:
        if stbl.children is None:
            stbl.children = []
        stbl.children.append(_make_roll_sbgp(sample_count))
        return
    sbgp.data = _make_roll_sbgp(sample_count).data


def _rebuild_audio_track(
    source: _Atom,
    *,
    track_id: int,
    track_duration: int,
    media_duration: int,
    chunk_count: int,
    new_offsets: tuple[int, int],
    clone: bool,
) -> _Atom:
    trak = copy.deepcopy(source)
    tkhd = trak.require(b"tkhd")
    _patch_tkhd(tkhd, track_id, track_duration)
    elst = trak.require(b"edts").require(b"elst")
    _patch_elst(elst, track_duration)
    mdia = trak.require(b"mdia")
    mdhd = mdia.require(b"mdhd")
    _patch_mdhd(mdhd, media_duration)
    stbl = mdia.require(b"minf").require(b"stbl")
    entry = _audio_sample_entry(trak)
    stsd = stbl.require(b"stsd")
    if clone:
        stsd.data = struct.pack(">II", 0, 1) + entry.raw
    else:
        alternate = _alternate_entry(entry)
        stsd.data = (
            struct.pack(">II", 0, 2) + entry.raw + alternate.raw
        )
    _rebuild_stts(stbl)
    _rebuild_stsc(stbl, chunk_count, clone=clone)
    _rebuild_stsz(stbl)
    _rebuild_stco(stbl, new_offsets)
    _rebuild_audio_groups(stbl, _audio_sample_count(trak) - APPENDED_SAMPLES)
    return trak


def _audio_sample_count(trak: _Atom) -> int:
    stsz = trak.require(b"mdia").require(b"minf").require(b"stbl").require(b"stsz")
    return _u32(stsz.data, 8)


def _new_moov(
    structure: _Structure,
    info: ZilemSourceInfo,
    tag: str,
    source_size: int,
) -> tuple[_Atom, int, int]:
    moov = copy.deepcopy(structure.moov)
    children = moov.children or []
    mvhd = moov.find(b"mvhd")
    if mvhd is None:
        raise ZilemSourceError("moov has no mvhd box")
    movie_timescale, old_movie_duration, old_next_track = _mvhd_info(mvhd)
    base_movie_duration = (
        0
        if _is_indeterminate_movie_duration(mvhd, old_movie_duration)
        else old_movie_duration
    )

    traks = [child for child in children if child.type == b"trak"]
    video = [trak for trak in traks if _handler_type(trak) == b"vide"][0]
    audio = [trak for trak in traks if _handler_type(trak) == b"soun"][0]
    audio_mdhd = audio.require(b"mdia").require(b"mdhd")
    _, old_media_duration = _mdhd_timing(audio_mdhd)
    old_track_duration = _tkhd_duration(audio)

    delta_ticks = (
        APPENDED_SAMPLES * AUDIO_FRAME_SAMPLES * movie_timescale
        + info.audio_timescale
        - 1
    ) // info.audio_timescale
    new_track_duration = old_track_duration + delta_ticks
    new_media_duration = old_media_duration + APPENDED_SAMPLES * AUDIO_FRAME_SAMPLES

    used_ids = set(info.track_ids)
    new_track_id = old_next_track
    if new_track_id in used_ids:
        new_track_id = max(used_ids) + 1
    new_next_track = max(old_next_track, new_track_id + 1)

    payload_start = source_size + 8
    new_offsets = (
        payload_start,
        payload_start + APPENDED_CHUNK_SIZES[0] * len(SILENCE_FRAME),
    )
    new_audio = _rebuild_audio_track(
        audio,
        track_id=_tkhd_track_id(audio),
        track_duration=new_track_duration,
        media_duration=new_media_duration,
        chunk_count=info.audio_chunks,
        new_offsets=new_offsets,
        clone=False,
    )
    clone = _rebuild_audio_track(
        audio,
        track_id=new_track_id,
        track_duration=new_track_duration,
        media_duration=new_media_duration,
        chunk_count=info.audio_chunks,
        new_offsets=new_offsets,
        clone=True,
    )
    _apply_video_tag(video, tag)

    rebuilt: list[_Atom] = []
    for child in children:
        if child.type == b"udta":
            # The old movie-level metadata is intentionally not copied; the
            # reference container keeps only track metadata and the new tag.
            continue
        if child is audio:
            # Replace the original audio track with the extended track plus
            # the duplicate that shares its chunks.
            rebuilt.append(new_audio)
            rebuilt.append(clone)
            continue
        rebuilt.append(child)
    moov.children = rebuilt

    track_durations = [
        _tkhd_duration(trak)
        for trak in rebuilt
        if trak.type == b"trak"
        and _handler_type(trak) in (b"vide", b"soun")
    ]
    movie_duration = max([base_movie_duration, *track_durations])
    _patch_mvhd(mvhd, movie_duration, new_next_track)
    return moov, movie_duration, new_track_id


def _hash_range(mapped: mmap.mmap, start: int, size: int) -> str:
    digest = hashlib.sha256()
    view = memoryview(mapped)
    step = 4 * 1024 * 1024
    position = start
    remaining = size
    while remaining > 0:
        take = min(step, remaining)
        digest.update(view[position : position + take])
        position += take
        remaining -= take
    return digest.hexdigest()


def build_zeta_trailer(name: str, when: datetime | None = None) -> bytes:
    """Build the 71-byte-class ``free`` trailer used by the reference method.

    The payload is ``ZETA_OPTIMIZED/3 <UTC timestamp with milliseconds> <name>``.
    The box size follows the name length, so it is only exactly 71 bytes when
    the output name is 21 characters long.
    """
    stamp = (when or datetime.now(UTC)).astimezone(UTC)
    text = (
        f"{ZETA_TRAILER_PREFIX} "
        f"{stamp.strftime('%Y-%m-%dT%H:%M:%S.')}{stamp.microsecond // 1000:03d}Z "
        f"{name}"
    )
    payload = text.encode("utf-8")
    return struct.pack(">I4s", 8 + len(payload), b"free") + payload


def build_zilem(
    src: Path,
    out: Path,
    *,
    tag: str = PRODUCTION_TAG,
    trailer_name: str | None = None,
    trailer_time: datetime | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[float], None] | None = None,
    on_log: Callable[[str], None] | None = None,
) -> ZilemStats:
    """Build an X1T Zilem container from *src* into *out*.

    The source is copied unchanged except for the old ``moov`` type; no media
    bytes are re-encoded. ``tag`` is exposed for golden tests and should stay
    at :data:`PRODUCTION_TAG` in the application. Passing ``trailer_name``
    appends the reference method's ``ZETA_OPTIMIZED/3`` free box after the
    rebuilt ``moov``.
    """
    if src.resolve() == out.resolve():
        raise ZilemSourceError("output path equals source; refusing to overwrite")
    structure = _read_structure(src)
    info = _validate_source(structure)
    if structure.size + 8 + 54 > _MAX_STCO_OFFSET:
        raise ZilemSourceError(
            "source is too large for the 32-bit chunk offsets used by X1T Zilem"
        )
    moov, movie_duration, new_track_id = _new_moov(
        structure, info, tag, structure.size
    )
    moov_bytes = moov.to_bytes()
    trailer = (
        build_zeta_trailer(trailer_name, trailer_time) if trailer_name else b""
    )
    output_size = structure.size + _MDAT2_SIZE + len(moov_bytes) + len(trailer)

    def progress(fraction: float) -> None:
        if on_progress is not None:
            on_progress(max(0.0, min(1.0, fraction)))

    copied = 0
    try:
        with src.open("rb") as reader, out.open("wb") as writer:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise PatchCancelledError("Zilem patch cancelled by user.")
                chunk = reader.read(_COPY_CHUNK)
                if not chunk:
                    break
                writer.write(chunk)
                copied += len(chunk)
                progress(0.90 * copied / structure.size)
            if copied != structure.size:
                raise ZilemSourceError(
                    "source changed or was truncated while copying"
                )
            # The old movie header becomes a free box so players ignore it.
            writer.seek(structure.moov_offset + 4)
            writer.write(b"free")
            writer.seek(0, os.SEEK_END)
            writer.write(
                struct.pack(">I4s", _MDAT2_SIZE, b"mdat")
                + SILENCE_FRAME * APPENDED_SAMPLES
            )
            writer.write(moov_bytes)
            if trailer:
                writer.write(trailer)
    except OSError as exc:
        out.unlink(missing_ok=True)
        raise ZilemSourceError(f"could not write Zilem output: {exc}") from exc
    progress(1.0)
    if on_log is not None:
        suffix = f", trailer {len(trailer)} bytes" if trailer else ""
        on_log(
            f"[ZILEM] {info.video_samples} video samples copied, "
            f"{info.audio_samples} -> {info.audio_samples + APPENDED_SAMPLES} "
            f"audio samples, tag '{tag}'{suffix}"
        )
    return ZilemStats(
        source_size=structure.size,
        output_size=output_size,
        moov_size=len(moov_bytes),
        video_samples=info.video_samples,
        audio_samples_before=info.audio_samples,
        audio_samples_after=info.audio_samples + APPENDED_SAMPLES,
        audio_chunks_before=info.audio_chunks,
        audio_chunks_after=info.audio_chunks + 2,
        new_track_id=new_track_id,
        movie_duration=movie_duration,
        tag=tag,
        trailer=trailer,
    )


def _trak_list(moov: _Atom) -> list[_Atom]:
    return [child for child in moov.children or [] if child.type == b"trak"]


def _audio_traks(moov: _Atom) -> list[_Atom]:
    return [trak for trak in _trak_list(moov) if _handler_type(trak) == b"soun"]


def _video_traks(moov: _Atom) -> list[_Atom]:
    return [trak for trak in _trak_list(moov) if _handler_type(trak) == b"vide"]


def _serialized_stbl(trak: _Atom) -> bytes:
    return (
        trak.require(b"mdia")
        .require(b"minf")
        .require(b"stbl")
        .to_bytes()
    )


def _tag_text_in_video(video: _Atom) -> str | None:
    udta = video.find(b"udta")
    if udta is None:
        return None
    meta = udta.find(b"meta")
    if meta is None:
        return None
    ilst = meta.find(b"ilst")
    if ilst is None:
        return None
    too = ilst.find(b"\xa9too")
    if too is None or not too.children:
        return None
    data = too.children[0]
    if len(data.data) < 8:
        return None
    raw = data.data[8:]
    if raw.endswith(b"\x00"):
        raw = raw[:-1]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def verify_zilem_output(
    src: Path,
    out: Path,
    *,
    tag: str = PRODUCTION_TAG,
    trailer: bytes | None = None,
) -> None:
    """Raise :class:`VerifyError` unless *out* is a valid Zilem build of *src*.

    When ``trailer`` is provided, the output must end with exactly those bytes
    as a ``free`` box after the rebuilt ``moov``.
    """
    source_structure = _read_structure(src)
    source_info = _validate_source(source_structure)
    target = _read_structure(out)

    expected_trailer = trailer or b""
    expected_size = (
        source_structure.size
        + _MDAT2_SIZE
        + target.moov_size
        + len(expected_trailer)
    )
    if target.size != expected_size:
        raise VerifyError(
            f"output size {target.size} != source + mdat2 + moov + trailer "
            f"({expected_size})"
        )
    moov_start = source_structure.size + _MDAT2_SIZE
    moov_end = moov_start + target.moov_size
    if target.moov_offset != moov_start:
        raise VerifyError("rebuilt moov is not at the expected offset")
    if moov_end + len(expected_trailer) != target.size:
        raise VerifyError("trailing bytes after the final moov box")
    if expected_trailer:
        trailer_box = target.top[-1]
        if (
            trailer_box[3] != b"free"
            or trailer_box[0] != moov_end
            or trailer_box[1] != len(expected_trailer)
        ):
            raise VerifyError("reference trailer box is missing or malformed")
        with out.open("rb") as handle:
            handle.seek(moov_end)
            if handle.read(len(expected_trailer)) != expected_trailer:
                raise VerifyError("reference trailer content mismatch")
    elif target.top[-1][3] != b"moov":
        raise VerifyError("output does not end with a moov box (unexpected trailer)")

    # The old moov must be a byte-identical free box.
    ftyp = next((item for item in source_structure.top if item[3] == b"ftyp"), None)
    old_free = next(
        (
            item
            for item in target.top
            if item[0] == source_structure.moov_offset
            and item[1] == source_structure.moov_size
        ),
        None,
    )
    if old_free is None or old_free[3] != b"free":
        raise VerifyError("old moov box was not converted to free")

    with (
        src.open("rb") as source_handle,
        out.open("rb") as target_handle,
        mmap.mmap(source_handle.fileno(), 0, access=mmap.ACCESS_READ) as s,
        mmap.mmap(target_handle.fileno(), 0, access=mmap.ACCESS_READ) as t,
    ):
        if ftyp is not None:
            offset, size = ftyp[0], ftyp[1]
            if s[offset : offset + size] != t[offset : offset + size]:
                raise VerifyError("ftyp box changed")

        s_payload = s[
            source_structure.moov_offset + 8 :
            source_structure.moov_offset + source_structure.moov_size
        ]
        t_payload = t[
            source_structure.moov_offset + 8 :
            source_structure.moov_offset + source_structure.moov_size
        ]
        if s_payload != t_payload:
            raise VerifyError("old moov payload changed while converting to free")

        for offset, size, _, atom_type in source_structure.top:
            if atom_type != b"mdat":
                continue
            if _hash_range(s, offset, size) != _hash_range(t, offset, size):
                raise VerifyError(f"media data changed in mdat at offset {offset}")

        mdat2_offset = source_structure.size
        if mdat2_offset + _MDAT2_SIZE > target.size:
            raise VerifyError("mdat2 box is missing")
        mdat2 = t[mdat2_offset : mdat2_offset + _MDAT2_SIZE]
        if mdat2[:8] != struct.pack(">I4s", _MDAT2_SIZE, b"mdat"):
            raise VerifyError("mdat2 box has an invalid header")
        if mdat2[8:] != SILENCE_FRAME * APPENDED_SAMPLES:
            raise VerifyError("mdat2 silence frames are not intact")

    output_moov = target.moov
    video_traks = _video_traks(output_moov)
    audio_traks = _audio_traks(output_moov)
    if len(video_traks) != 1:
        raise VerifyError(
            f"expected one video track in output, found {len(video_traks)}"
        )
    if len(audio_traks) != 2:
        raise VerifyError(
            f"expected two audio tracks in output, found {len(audio_traks)}"
        )
    source_video = _video_traks(source_structure.moov)[0]
    if _serialized_stbl(video_traks[0]) != _serialized_stbl(source_video):
        raise VerifyError("video sample tables changed")
    found_tag = _tag_text_in_video(video_traks[0])
    if found_tag != tag:
        raise VerifyError(
            f"video tag mismatch: expected {tag!r}, found {found_tag!r}"
        )

    stsd_primary = audio_traks[0].require(b"mdia").require(b"minf").require(
        b"stbl"
    ).require(b"stsd")
    stsd_clone = audio_traks[1].require(b"mdia").require(b"minf").require(
        b"stbl"
    ).require(b"stsd")
    if _u32(stsd_primary.data, 4) != 2:
        raise VerifyError("primary audio track lost its alternate sample entry")
    if _u32(stsd_clone.data, 4) != 1:
        raise VerifyError("duplicate audio track must use one sample entry")

    expected_samples = source_info.audio_samples + APPENDED_SAMPLES
    expected_chunks = source_info.audio_chunks + 2
    for index, trak in enumerate(audio_traks):
        stbl = trak.require(b"mdia").require(b"minf").require(b"stbl")
        stsz = stbl.require(b"stsz")
        _, count = struct.unpack_from(">II", stsz.data, 4)
        if count != expected_samples:
            raise VerifyError(
                f"audio track {index + 1} sample count {count} != {expected_samples}"
            )
        tail = stsz.data[-APPENDED_SAMPLES * 4 :]
        if tail != struct.pack(">I", len(SILENCE_FRAME)) * APPENDED_SAMPLES:
            raise VerifyError(
                f"audio track {index + 1} appended sample sizes are not 6 bytes"
            )
        stco = stbl.require(b"stco")
        chunk_count = _u32(stco.data, 4)
        if chunk_count != expected_chunks:
            raise VerifyError(
                f"audio track {index + 1} chunk count {chunk_count} "
                f"!= {expected_chunks}"
            )
        last_two = struct.unpack_from(">II", stco.data, len(stco.data) - 8)
        expected_offsets = (
            source_structure.size + 8,
            source_structure.size + 8 + APPENDED_CHUNK_SIZES[0] * len(SILENCE_FRAME),
        )
        if last_two != expected_offsets:
            raise VerifyError(
                f"audio track {index + 1} new chunk offsets {last_two} "
                f"!= {expected_offsets}"
            )

    expected_media_duration = (
        _mdhd_timing(
            _audio_traks(source_structure.moov)[0]
            .require(b"mdia")
            .require(b"mdhd")
        )[1]
        + APPENDED_SAMPLES * AUDIO_FRAME_SAMPLES
    )
    for trak in audio_traks:
        actual = _mdhd_timing(trak.require(b"mdia").require(b"mdhd"))[1]
        if actual != expected_media_duration:
            raise VerifyError(
                f"audio mdhd duration {actual} != {expected_media_duration}"
            )

    output_mvhd = output_moov.require(b"mvhd")
    movie_timescale, movie_duration, _ = _mvhd_info(output_mvhd)
    if movie_timescale != source_info.movie_timescale:
        raise VerifyError("movie timescale changed")

    source_mvhd = source_structure.moov.require(b"mvhd")
    _, source_movie_duration, _ = _mvhd_info(source_mvhd)
    if _is_indeterminate_movie_duration(source_mvhd, source_movie_duration):
        source_movie_duration = 0
    expected_movie_duration = max(
        [
            source_movie_duration,
            *[_tkhd_duration(trak) for trak in [*video_traks, *audio_traks]],
        ]
    )
    if movie_duration != expected_movie_duration:
        raise VerifyError(
            f"movie duration {movie_duration} != {expected_movie_duration}"
        )
    if _is_indeterminate_movie_duration(output_mvhd, movie_duration):
        raise VerifyError("output movie duration is indeterminate")
