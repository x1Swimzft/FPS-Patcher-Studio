"""Tests for the ffprobe-free prober: header-only scanning and metadata tags."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, BinaryIO, NoReturn

import pytest

import fps_patcher.core.prober as prober
from fps_patcher.core.errors import ProbeError
from fps_patcher.core.models import VideoInfo
from fps_patcher.core.prober import probe_direct

TIMESCALE = 30000
FRAME_COUNT = 300
FRAME_DELTA = 1000
WIDTH = 1920
HEIGHT = 1080
SAMPLE_RATE = 48000
CHANNELS = 2


def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, typ) + payload


def _full_box(typ: bytes, version: int, flags: int, payload: bytes) -> bytes:
    v_flags = ((version & 0xFF) << 24) | (flags & 0x00FFFFFF)
    return struct.pack(">I4sI", len(payload) + 12, typ, v_flags) + payload


def _tkhd() -> bytes:
    fields = bytearray(80)
    struct.pack_into(">II", fields, 72, WIDTH << 16, HEIGHT << 16)
    return _full_box(b"tkhd", 0, 0, bytes(fields))


def _mdhd(version: int = 0) -> bytes:
    duration = FRAME_COUNT * FRAME_DELTA
    if version == 1:
        return _full_box(
            b"mdhd", 1, 0, struct.pack(">QQIQHH", 0, 0, TIMESCALE, duration, 0, 0)
        )
    return _full_box(
        b"mdhd", 0, 0, struct.pack(">IIIIHH", 0, 0, TIMESCALE, duration, 0, 0)
    )


def _hdlr(handler: bytes) -> bytes:
    return _full_box(b"hdlr", 0, 0, b"\x00" * 4 + handler + b"\x00" * 12)


def _video_entry(colr: bytes | None = None, extras: bytes = b"") -> bytes:
    # VisualSampleEntry fields end 78 bytes after the 8-byte entry header.
    fields = bytearray(78)
    struct.pack_into(">HH", fields, 24, WIDTH, HEIGHT)
    fields += extras
    if colr is not None:
        fields += colr
    return _box(b"avc1", bytes(fields))


def _audio_entry() -> bytes:
    fields = bytearray(28)
    struct.pack_into(">H", fields, 16, CHANNELS)
    struct.pack_into(">I", fields, 24, SAMPLE_RATE << 16)
    return _box(b"mp4a", bytes(fields))


def _video_trak(
    colr: bytes | None = None,
    *,
    extras: bytes = b"",
    mdhd_version: int = 0,
    stsz_box: bytes | None = None,
    stts_box: bytes | None = None,
) -> bytes:
    stsd = _full_box(b"stsd", 0, 0, struct.pack(">I", 1) + _video_entry(colr, extras))
    if stsz_box is None:
        stsz_box = _full_box(b"stsz", 0, 0, struct.pack(">II", 0, FRAME_COUNT))
    if stts_box is None:
        stts_box = _full_box(b"stts", 0, 0, struct.pack(">III", 1, FRAME_COUNT, FRAME_DELTA))
    stbl = _box(b"stbl", stsd + stsz_box + stts_box)
    mdia = _box(b"mdia", _mdhd(mdhd_version) + _hdlr(b"vide") + _box(b"minf", stbl))
    return _box(b"trak", _tkhd() + mdia)


def _audio_trak() -> bytes:
    stsd = _full_box(b"stsd", 0, 0, struct.pack(">I", 1) + _audio_entry())
    stbl = _box(b"stbl", stsd)
    mdia = _box(b"mdia", _mdhd() + _hdlr(b"soun") + _box(b"minf", stbl))
    return _box(b"trak", _tkhd() + mdia)


def _write_mp4(
    path: Path,
    *,
    moov_last: bool = True,
    size_mode: str = "normal",
    colr: bytes | None = None,
    audio: bool = True,
    extras: bytes = b"",
    mdhd_version: int = 0,
    stsz_box: bytes | None = None,
    stts_box: bytes | None = None,
) -> int:
    ftyp = _box(b"ftyp", b"isom\x00\x00\x02\x00isom")
    mdat = _box(b"mdat", b"\x00" * (2 * 1024 * 1024))
    payload = (
        _video_trak(
            colr,
            extras=extras,
            mdhd_version=mdhd_version,
            stsz_box=stsz_box,
            stts_box=stts_box,
        )
        + (_audio_trak() if audio else b"")
    )
    if size_mode == "moov64":
        moov = struct.pack(">I4sQ", 1, b"moov", len(payload) + 16) + payload
    elif size_mode == "to_eof":
        moov = struct.pack(">I4s", 0, b"moov") + payload
        moov_last = True
    else:
        moov = _box(b"moov", payload)
    data = ftyp + (mdat + moov if moov_last else moov + mdat)
    path.write_bytes(data)
    return len(data)


def _no_read_bytes(self: Path) -> bytes:
    raise AssertionError("probe_direct must not read the whole file")


def _fail_open(self: Path, *args: object, **kwargs: object) -> NoReturn:
    raise OSError("boom")


class _CountingReader:
    def __init__(self, fh: BinaryIO) -> None:
        self._fh = fh
        self.bytes_read = 0
        self.read_sizes: list[int] = []

    def __enter__(self) -> _CountingReader:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._fh.close()

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._fh.seek(offset, whence)

    def read(self, size: int = -1) -> bytes:
        data = self._fh.read(size)
        self.bytes_read += len(data)
        self.read_sizes.append(size)
        return data


def _assert_common(info: VideoInfo, path: Path, file_size: int) -> None:
    assert info.path == path
    assert info.codec == "h264"
    assert info.width == WIDTH
    assert info.height == HEIGHT
    assert info.fps == pytest.approx(30.0)
    assert info.timescale == TIMESCALE
    assert info.nb_frames == FRAME_COUNT
    assert info.duration_s == pytest.approx(10.0)
    assert info.file_size_bytes == file_size
    assert info.bit_rate == int(file_size * 8 / 10.0)


@pytest.mark.parametrize(
    ("moov_last", "size_mode"),
    [(True, "normal"), (False, "normal"), (False, "moov64"), (True, "to_eof")],
)
def test_probe_direct_scans_headers_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    moov_last: bool,
    size_mode: str,
) -> None:
    src = tmp_path / f"clip_{moov_last}_{size_mode}.mp4"
    file_size = _write_mp4(src, moov_last=moov_last, size_mode=size_mode)
    monkeypatch.setattr(Path, "read_bytes", _no_read_bytes)

    info = probe_direct(src)

    _assert_common(info, src, file_size)
    assert info.has_audio is True
    assert info.stream_count == 2
    assert info.audio_codec == "aac"


def test_probe_direct_respects_read_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "read_budget.mp4"
    _write_mp4(src)
    real_open = Path.open
    readers: list[_CountingReader] = []

    def _open(path_self: Path, *args: Any, **kwargs: Any) -> _CountingReader:
        reader = _CountingReader(real_open(path_self, *args, **kwargs))
        readers.append(reader)
        return reader

    monkeypatch.setattr(Path, "open", _open)

    info = probe_direct(src)

    assert info.nb_frames == FRAME_COUNT
    assert len(readers) == 1
    reader = readers[0]
    assert reader.bytes_read < 8 * 1024
    assert -1 not in reader.read_sizes
    assert max(reader.read_sizes) <= 8 * 1024


@pytest.mark.parametrize(
    ("colr", "extras", "expected"),
    [
        (
            _box(b"colr", b"nclx" + struct.pack(">HHHB", 9, 16, 9, 1)),
            b"",
            ("bt2020", "smpte2084", "bt2020nc"),
        ),
        (
            _box(b"colr", b"nclc" + struct.pack(">HHH", 1, 1, 1)),
            b"",
            ("bt709", "bt709", "bt709"),
        ),
        (
            _box(b"colr", b"nclx" + struct.pack(">HHHB", 9, 16, 9, 1)),
            _box(b"avcC", b"\x01\x64\x00\x1f") + _box(b"pasp", struct.pack(">II", 1, 1)),
            ("bt2020", "smpte2084", "bt2020nc"),
        ),
        (None, b"", (None, None, None)),
        (None, _box(b"avcC", b"\x01\x64\x00\x1f"), (None, None, None)),
    ],
)
def test_probe_direct_reads_color_tags(
    tmp_path: Path,
    colr: bytes | None,
    extras: bytes,
    expected: tuple[str | None, str | None, str | None],
) -> None:
    src = tmp_path / "color.mp4"
    _write_mp4(src, colr=colr, extras=extras)

    info = probe_direct(src)

    assert (info.color_primaries, info.color_transfer, info.color_space) == expected


def test_probe_direct_reads_mdhd_version_1(tmp_path: Path) -> None:
    src = tmp_path / "mdhd_v1.mp4"
    _write_mp4(src, audio=False, mdhd_version=1)

    info = probe_direct(src)

    assert info.timescale == TIMESCALE
    assert info.duration_s == pytest.approx(10.0)
    assert info.nb_frames == FRAME_COUNT
    assert info.fps == pytest.approx(30.0)


def test_probe_direct_ignores_truncated_sample_tables(tmp_path: Path) -> None:
    src = tmp_path / "truncated_stsz.mp4"
    _write_mp4(src, audio=False, stsz_box=_full_box(b"stsz", 0, 0, struct.pack(">I", 0)))

    info = probe_direct(src)

    assert info.nb_frames is None
    assert info.fps == pytest.approx(30.0)

    src = tmp_path / "truncated_stts.mp4"
    _write_mp4(src, audio=False, stts_box=_full_box(b"stts", 0, 0, b""))

    info = probe_direct(src)

    assert info.nb_frames == FRAME_COUNT
    assert info.fps == 0.0


def test_probe_direct_reads_audio_fields(tmp_path: Path) -> None:
    src = tmp_path / "audio.mp4"
    _write_mp4(src)

    info = probe_direct(src)

    assert info.audio_sample_rate == SAMPLE_RATE
    assert info.audio_channels == CHANNELS


def test_probe_direct_without_audio_keeps_fields_none(tmp_path: Path) -> None:
    src = tmp_path / "silent.mp4"
    _write_mp4(src, audio=False)

    info = probe_direct(src)

    assert info.has_audio is False
    assert info.stream_count == 1
    assert info.audio_codec is None
    assert info.audio_sample_rate is None
    assert info.audio_channels is None


def test_probe_direct_rejects_empty_file(tmp_path: Path) -> None:
    src = tmp_path / "empty.mp4"
    src.write_bytes(b"")

    with pytest.raises(ProbeError):
        probe_direct(src)


def test_probe_direct_rejects_out_of_range_box(tmp_path: Path) -> None:
    src = tmp_path / "truncated.mp4"
    src.write_bytes(_box(b"ftyp", b"isom" + b"\x00" * 8) + struct.pack(">I4s", 4096, b"moov"))

    with pytest.raises(ProbeError, match="moov box not found"):
        probe_direct(src)


def test_probe_direct_rejects_oversized_moov(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "big_moov.mp4"
    _write_mp4(src)
    monkeypatch.setattr(prober, "_MAX_MOOV_BYTES", 64)

    with pytest.raises(ProbeError, match="moov atom"):
        probe_direct(src)


def test_probe_direct_wraps_os_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "clip.mp4"
    _write_mp4(src)
    monkeypatch.setattr(Path, "open", _fail_open)

    with pytest.raises(ProbeError, match="Failed to read file: boom"):
        probe_direct(src)
