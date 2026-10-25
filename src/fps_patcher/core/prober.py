"""Extract VideoInfo from a media file via ffprobe."""

from __future__ import annotations

import struct
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

from .errors import ProbeError
from .ffmpeg_locator import locate
from .ffmpeg_runner import run_json
from .models import VideoInfo


def parse_fraction(value: str | None) -> Fraction:
    """Parse '30000/1001' style strings; returns 0 for missing/invalid/'0/0'."""
    if not value:
        return Fraction(0)
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            if int(den) == 0:
                return Fraction(0)
            return Fraction(int(num), int(den))
        return Fraction(value)
    except (ValueError, ZeroDivisionError):
        return Fraction(0)


def _to_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_str(value: Any) -> str | None:
    """Return a meaningful ffprobe string; 'unknown' is treated as unavailable."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    return None if text.lower() in ("", "unknown", "none") else text


def _file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def parse_probe(path: Path, data: dict[str, Any]) -> VideoInfo:
    streams: list[dict[str, Any]] = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ProbeError("No video stream found.")
    fmt: dict[str, Any] = data.get("format", {})

    time_base = parse_fraction(video.get("time_base"))
    timescale = time_base.denominator if time_base > 0 and time_base.numerator == 1 else 0

    duration_raw = video.get("duration") or fmt.get("duration") or 0
    try:
        duration = float(duration_raw)
    except (TypeError, ValueError):
        duration = 0.0

    nb_raw = video.get("nb_frames")
    nb_frames = int(nb_raw) if nb_raw and str(nb_raw).isdigit() else None

    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    audio_codec = str(audio.get("codec_name")) if audio and audio.get("codec_name") else None

    audio_sample_rate = _to_int(audio.get("sample_rate")) if audio else None
    audio_channels = _to_int(audio.get("channels")) if audio else None

    raw_br = video.get("bit_rate") or fmt.get("bit_rate")
    bit_rate: int | None = None
    if raw_br and str(raw_br).isdigit():
        bit_rate = int(raw_br)
    elif duration > 0 and path.is_file():
        try:
            bit_rate = int((path.stat().st_size * 8) / duration)
        except OSError:
            bit_rate = None

    return VideoInfo(
        path=path,
        codec=str(video.get("codec_name", "unknown")),
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        avg_fps=parse_fraction(video.get("avg_frame_rate")),
        r_fps=parse_fraction(video.get("r_frame_rate")),
        duration_s=duration,
        timescale=timescale,
        nb_frames=nb_frames,
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        stream_count=len(streams),
        audio_codec=audio_codec,
        bit_rate=bit_rate,
        audio_sample_rate=audio_sample_rate,
        audio_channels=audio_channels,
        format_name=_to_str(fmt.get("format_name")),
        color_primaries=_to_str(video.get("color_primaries")),
        color_transfer=_to_str(video.get("color_transfer")),
        color_space=_to_str(video.get("color_space")),
        pix_fmt=_to_str(video.get("pix_fmt")),
        file_size_bytes=_file_size(path),
    )


def probe_direct(path: Path) -> VideoInfo:
    """Extract VideoInfo directly from MP4/MOV container atoms without external ffprobe."""
    if not path.is_file():
        raise ProbeError(f"File not found: {path}")

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ProbeError(f"Failed to read file: {exc}") from exc

    limit = len(data)
    pos = 0
    moov_pos: int | None = None
    moov_size: int | None = None

    while pos + 8 <= limit:
        s32, typ = struct.unpack_from(">I4s", data, pos)
        hdr = 8
        if s32 == 1:
            if pos + 16 > limit:
                break
            size = struct.unpack_from(">Q", data, pos + 8)[0]
            hdr = 16
        elif s32 == 0:
            size = limit - pos
        else:
            size = s32
        if size < hdr or pos + size > limit:
            break
        if typ == b"moov":
            moov_pos = pos + hdr
            moov_size = size - hdr
            break
        pos += size

    if moov_pos is None or moov_size is None:
        raise ProbeError("Invalid MP4: moov box not found.")

    def find_child(data_slice: bytes, target_type: bytes) -> tuple[int, int] | None:
        p = 0
        end = len(data_slice)
        while p + 8 <= end:
            s32, typ = struct.unpack_from(">I4s", data_slice, p)
            hdr = 8
            if s32 == 1:
                if p + 16 > end:
                    break
                s = struct.unpack_from(">Q", data_slice, p + 8)[0]
                hdr = 16
            elif s32 == 0:
                s = end - p
            else:
                s = s32
            if s < hdr or p + s > end:
                break
            if typ == target_type:
                return (p + hdr, s - hdr)
            p += s
        return None

    def find_all_children(data_slice: bytes, target_type: bytes) -> list[tuple[int, int]]:
        res: list[tuple[int, int]] = []
        p = 0
        end = len(data_slice)
        while p + 8 <= end:
            s32, typ = struct.unpack_from(">I4s", data_slice, p)
            hdr = 8
            if s32 == 1:
                if p + 16 > end:
                    break
                s = struct.unpack_from(">Q", data_slice, p + 8)[0]
                hdr = 16
            elif s32 == 0:
                s = end - p
            else:
                s = s32
            if s < hdr or p + s > end:
                break
            if typ == target_type:
                res.append((p + hdr, s - hdr))
            p += s
        return res

    moov_data = data[moov_pos : moov_pos + moov_size]
    traks = find_all_children(moov_data, b"trak")
    if not traks:
        raise ProbeError("No tracks found in moov atom.")

    video_info: dict[str, Any] = {}
    has_audio = False
    audio_codec: str | None = None
    stream_count = len(traks)

    for trak_start, trak_len in traks:
        trak_data = moov_data[trak_start : trak_start + trak_len]
        mdia = find_child(trak_data, b"mdia")
        if not mdia:
            continue
        mdia_data = trak_data[mdia[0] : mdia[0] + mdia[1]]
        hdlr = find_child(mdia_data, b"hdlr")
        if not hdlr or hdlr[1] < 12:
            continue
        handler_type = mdia_data[hdlr[0] + 8 : hdlr[0] + 12]

        if handler_type == b"soun":
            has_audio = True
            if audio_codec is None:
                minf_a = find_child(mdia_data, b"minf")
                if minf_a:
                    minf_data_a = mdia_data[minf_a[0] : minf_a[0] + minf_a[1]]
                    stbl_a = find_child(minf_data_a, b"stbl")
                    if stbl_a:
                        stbl_data_a = minf_data_a[stbl_a[0] : stbl_a[0] + stbl_a[1]]
                        stsd_a = find_child(stbl_data_a, b"stsd")
                        if stsd_a and stsd_a[1] >= 16:
                            stsd_data_a = stbl_data_a[stsd_a[0] : stsd_a[0] + stsd_a[1]]
                            raw_entry = stsd_data_a[12:16].decode("latin1", errors="replace")
                            raw_ac = raw_entry.strip().lower()
                            audio_codec = {
                                "mp4a": "aac",
                                "alac": "alac",
                                "sowt": "pcm",
                                "twos": "pcm",
                                "in24": "pcm",
                                "in32": "pcm",
                                "fl32": "pcm",
                                "ac-3": "ac3",
                                "ec-3": "eac3",
                                "opus": "opus",
                            }.get(raw_ac, raw_ac)
        elif handler_type == b"vide" and not video_info:
            mdhd = find_child(mdia_data, b"mdhd")
            tkhd = find_child(trak_data, b"tkhd")
            minf = find_child(mdia_data, b"minf")
            timescale = 0
            duration_ticks = 0
            codec = "unknown"
            width = 0
            height = 0
            nb_frames = None
            avg_fps = Fraction(0)

            if tkhd and tkhd[1] >= 80:
                tkhd_data = trak_data[tkhd[0] : tkhd[0] + tkhd[1]]
                w_fixed, h_fixed = struct.unpack_from(">II", tkhd_data, len(tkhd_data) - 8)
                width = int(w_fixed / 65536)
                height = int(h_fixed / 65536)

            if mdhd and mdhd[1] >= 16:
                mdhd_data = mdia_data[mdhd[0] : mdhd[0] + mdhd[1]]
                ver = mdhd_data[0]
                if ver == 0 and len(mdhd_data) >= 20:
                    timescale, duration_ticks = struct.unpack_from(">II", mdhd_data, 12)
                elif ver == 1 and len(mdhd_data) >= 28:
                    timescale = struct.unpack_from(">I", mdhd_data, 20)[0]
                    duration_ticks = struct.unpack_from(">Q", mdhd_data, 24)[0]

            duration_s = float(duration_ticks / timescale) if timescale > 0 else 0.0

            if minf:
                minf_data = mdia_data[minf[0] : minf[0] + minf[1]]
                stbl = find_child(minf_data, b"stbl")
                if stbl:
                    stbl_data = minf_data[stbl[0] : stbl[0] + stbl[1]]
                    stsd = find_child(stbl_data, b"stsd")
                    if stsd and stsd[1] >= 16:
                        stsd_data = stbl_data[stsd[0] : stsd[0] + stsd[1]]
                        entry_cnt = struct.unpack_from(">I", stsd_data, 4)[0]
                        if entry_cnt > 0 and len(stsd_data) >= 16:
                            raw_codec = stsd_data[12:16].decode("latin1", errors="replace").strip()
                            codec = {
                                "avc1": "h264",
                                "hvc1": "hevc",
                                "hev1": "hevc",
                                "vp09": "vp9",
                                "av01": "av1",
                                "mp4v": "mpeg4",
                            }.get(raw_codec, raw_codec)

                    stsz = find_child(stbl_data, b"stsz")
                    if stsz and stsz[1] >= 8:
                        stsz_data = stbl_data[stsz[0] : stsz[0] + stsz[1]]
                        _, sample_cnt = struct.unpack_from(">II", stsz_data, 4)
                        nb_frames = sample_cnt

                    stts = find_child(stbl_data, b"stts")
                    if stts and stts[1] >= 4 and timescale > 0:
                        stts_data = stbl_data[stts[0] : stts[0] + stts[1]]
                        cnt = struct.unpack_from(">I", stts_data, 4)[0]
                        total_samples = 0
                        total_delta = 0
                        sp = 8
                        for _ in range(cnt):
                            if sp + 8 > len(stts_data):
                                break
                            sc, sd = struct.unpack_from(">II", stts_data, sp)
                            total_samples += sc
                            total_delta += sc * sd
                            sp += 8
                        if total_delta > 0:
                            avg_fps = Fraction(total_samples * timescale, total_delta)

            video_info = {
                "codec": codec,
                "width": width,
                "height": height,
                "avg_fps": avg_fps,
                "r_fps": avg_fps,
                "duration_s": duration_s,
                "timescale": timescale,
                "nb_frames": nb_frames,
            }

    if not video_info:
        raise ProbeError("No video stream found in MP4/MOV container.")

    bit_rate: int | None = None
    if video_info["duration_s"] > 0:
        bit_rate = int((len(data) * 8) / video_info["duration_s"])

    return VideoInfo(
        path=path,
        codec=video_info["codec"],
        width=video_info["width"],
        height=video_info["height"],
        avg_fps=video_info["avg_fps"],
        r_fps=video_info["r_fps"],
        duration_s=video_info["duration_s"],
        timescale=video_info["timescale"],
        nb_frames=video_info["nb_frames"],
        has_audio=has_audio,
        stream_count=stream_count,
        audio_codec=audio_codec,
        bit_rate=bit_rate,
        file_size_bytes=len(data),
    )


def probe(path: Path, ffprobe: Path | None = None) -> VideoInfo:
    """Probe video metadata using ffprobe if available, otherwise direct MP4 parsing."""
    if not path.is_file():
        raise ProbeError(f"File not found: {path}")
    if ffprobe is not None and ffprobe.is_file():
        try:
            data = run_json(ffprobe, ["-show_streams", "-show_format", str(path)])
            return parse_probe(path, data)
        except Exception:
            # Fall back to direct container parsing if ffprobe fails or is unusable
            return probe_direct(path)
    return probe_direct(path)


def _main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m fps_patcher.core.prober <video>")
        return 2
    paths = locate()
    info = probe(Path(argv[1]), paths.ffprobe)
    print(info)
    print(f"fps={info.fps:.3f} timescale={info.timescale}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
