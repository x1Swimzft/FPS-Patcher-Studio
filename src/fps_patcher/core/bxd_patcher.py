"""Method BXD Engine: Supports PC-oriented non-standard BXD, Mobile-safe ISO-BMFF presets,
Isolation Hypothesis Generators (Phase 0: H1-H4), and Lossless Mobile Repair.
"""

from __future__ import annotations

import hashlib
import shutil
import struct
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from .atom_patcher import _compress_values, _scale_deltas, _scale_int
from .errors import PatchCancelledError, PatchError, VerifyError
from .forensic_analyzer import MP4ForensicAnalyzer
from .verifier import (
    _iter_boxes_raw,
    verify_atom_structure,
    verify_mobile_compatibility,
    verify_offsets,
    verify_sample_tables,
)

# 8-byte filler NALU used by BXD & TikTok Enhancer
PADDING_NAL: bytes = b"\x00\x00\x00\x04\x00\x00\x00\x00"
PADDING_SIZE: int = 8
MAX_PADDING_BYTES: int = 512 * 1024 * 1024  # 512 MB safety ceiling
DISK_HEADROOM_BYTES: int = 64 * 1024 * 1024  # 64 MB free disk headroom
_SAFE_POST_MDAT_BOXES: frozenset[bytes] = frozenset({b"free", b"skip", b"udta", b"meta", b"uuid"})


@dataclass
class _AudioTableInfo:
    sample_count: int = 0
    sizes: list[int] = field(default_factory=list)
    stts: list[tuple[int, int]] = field(default_factory=list)
    stsc: list[tuple[int, int, int]] = field(default_factory=list)
    offsets: list[int] = field(default_factory=list)


def _build_box(typ: bytes, payload: bytes, force_largesize: bool = False) -> bytes:
    """Build standard 32-bit or 64-bit largesize ISO-BMFF box."""
    total_32 = len(payload) + 8
    if force_largesize or total_32 > 0xFFFFFFFF:
        total_64 = len(payload) + 16
        return struct.pack(">I4sQ", 1, typ, total_64) + payload
    return struct.pack(">I4s", total_32, typ) + payload


def _build_full_box(
    typ: bytes, version: int, flags: int, payload: bytes, force_largesize: bool = False
) -> bytes:
    v_flg = ((version & 0xFF) << 24) | (flags & 0x00FFFFFF)
    inner = struct.pack(">I", v_flg) + payload
    return _build_box(typ, inner, force_largesize=force_largesize)


def _build_free_box(padding_len: int) -> bytes:
    """Build a valid ISO-BMFF `free` box of total payload `padding_len` bytes."""
    if padding_len <= 0:
        return b""
    capped = min(padding_len, MAX_PADDING_BYTES)
    return _build_box(b"free", b"\x00" * capped)


def _build_stts(runs: list[tuple[int, int]]) -> bytes:
    payload = struct.pack(">I", len(runs)) + b"".join(
        struct.pack(">II", count, delta) for count, delta in runs
    )
    return _build_full_box(b"stts", 0, 0, payload)


def _build_stsz(sizes: list[int]) -> bytes:
    payload = struct.pack(">II", 0, len(sizes)) + b"".join(
        struct.pack(">I", s) for s in sizes
    )
    return _build_full_box(b"stsz", 0, 0, payload)


def _build_stsc(entries: list[tuple[int, int, int]]) -> bytes:
    payload = struct.pack(">I", len(entries)) + b"".join(
        struct.pack(">III", first, samples, desc_idx) for first, samples, desc_idx in entries
    )
    return _build_full_box(b"stsc", 0, 0, payload)


def _build_stco(offsets: list[int], force_co64: bool = False) -> bytes:
    if not force_co64 and (not offsets or max(offsets) <= 0xFFFFFFFF):
        payload = struct.pack(">I", len(offsets)) + b"".join(
            struct.pack(">I", off) for off in offsets
        )
        return _build_full_box(b"stco", 0, 0, payload)
    payload = struct.pack(">I", len(offsets)) + b"".join(
        struct.pack(">Q", off) for off in offsets
    )
    return _build_full_box(b"co64", 0, 0, payload)


def _build_elst_single(segment_duration: int, media_time: int) -> bytes:
    """Build an edts->elst box with a single edit entry."""
    if segment_duration > 0x7FFFFFFF or media_time > 0x7FFFFFFF:
        # version 1 (64-bit)
        payload = struct.pack(">Iqqhh", 1, segment_duration, media_time, 1, 0)
        elst = _build_full_box(b"elst", 1, 0, payload)
    else:
        # version 0 (32-bit)
        payload = struct.pack(">Iiihh", 1, segment_duration, media_time, 1, 0)
        elst = _build_full_box(b"elst", 0, 0, payload)
    return _build_box(b"edts", elst)


@dataclass
class _RawAtom:
    typ: bytes
    start: int
    size: int
    header_size: int
    data: bytes

    @property
    def payload(self) -> bytes:
        return self.data[self.header_size :]


def _parse_atoms(data: bytes, start: int = 0, limit: int | None = None) -> list[_RawAtom]:
    if limit is None:
        limit = len(data)
    pos = start
    atoms: list[_RawAtom] = []
    while pos < limit:
        if pos + 8 > limit:
            break
        s32, typ = struct.unpack_from(">I4s", data, pos)
        if not all(32 <= b <= 126 for b in typ):
            break
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
        atoms.append(
            _RawAtom(
                typ=typ,
                start=pos,
                size=size,
                header_size=hdr,
                data=data[pos : pos + size],
            )
        )
        pos += size
        if s32 == 0:
            break
    return atoms


def _read_mvhd_ts_and_dur(mvhd: _RawAtom) -> tuple[int, int, int]:
    """Return (version, timescale, duration) from mvhd atom."""
    p = mvhd.payload
    ver = p[0]
    if ver == 0:
        ts, dur = struct.unpack_from(">II", p, 12)
        return 0, int(ts), int(dur)
    ts, dur = struct.unpack_from(">IQ", p, 20)
    return 1, int(ts), int(dur)


def _patch_mvhd_duration(mvhd: _RawAtom, new_duration: int) -> bytes:
    """Update mvhd.duration preserving version 0 or upgrading to version 1 if > 32-bit."""
    p = bytearray(mvhd.payload)
    ver = p[0]
    if ver == 0 and new_duration <= 0xFFFFFFFF:
        struct.pack_into(">I", p, 16, new_duration)
        return _build_box(b"mvhd", bytes(p))
    elif ver == 1:
        struct.pack_into(">Q", p, 24, new_duration)
        return _build_box(b"mvhd", bytes(p))
    else:
        # Upgrade v0 -> v1
        c_time, m_time, ts, _ = struct.unpack_from(">IIII", p, 4)
        tail = bytes(p[20:])
        v_flg = (1 << 24) | (struct.unpack_from(">I", p, 0)[0] & 0x00FFFFFF)
        new_p = struct.pack(">IQQIQ", v_flg, c_time, m_time, ts, new_duration) + tail
        return _build_box(b"mvhd", new_p)


def _read_tkhd_duration(tkhd: _RawAtom) -> int:
    p = tkhd.payload
    ver = p[0]
    if ver == 0:
        return int(struct.unpack_from(">I", p, 20)[0])
    return int(struct.unpack_from(">Q", p, 28)[0])


def _patch_tkhd_duration(tkhd: _RawAtom, new_duration: int) -> bytes:
    p = bytearray(tkhd.payload)
    ver = p[0]
    if ver == 0:
        struct.pack_into(">I", p, 20, min(0xFFFFFFFF, max(0, new_duration)))
    else:
        struct.pack_into(">Q", p, 28, max(0, new_duration))
    return _build_box(b"tkhd", bytes(p))


def _read_mdhd_ts_and_dur(mdhd: _RawAtom) -> tuple[int, int]:
    p = mdhd.payload
    ver = p[0]
    if ver == 0:
        ts, dur = struct.unpack_from(">II", p, 12)
        return int(ts), int(dur)
    ts, dur = struct.unpack_from(">IQ", p, 20)
    return int(ts), int(dur)


def _patch_mdhd_values(mdhd: _RawAtom, new_ts: int, new_dur: int) -> bytes:
    p = bytearray(mdhd.payload)
    ver = p[0]
    if ver == 0 and new_dur <= 0xFFFFFFFF:
        struct.pack_into(">II", p, 12, new_ts, new_dur)
        return _build_box(b"mdhd", bytes(p))
    elif ver == 1:
        struct.pack_into(">IQ", p, 20, new_ts, new_dur)
        return _build_box(b"mdhd", bytes(p))
    else:
        c_time, m_time, _, _ = struct.unpack_from(">IIII", p, 4)
        tail = bytes(p[20:])
        v_flg = (1 << 24) | (struct.unpack_from(">I", p, 0)[0] & 0x00FFFFFF)
        new_p = struct.pack(">IQQIQ", v_flg, c_time, m_time, new_ts, new_dur) + tail
        return _build_box(b"mdhd", new_p)


def _sum_elst_segment_durations(edts: _RawAtom) -> int | None:
    children = _parse_atoms(edts.payload)
    elst = next((a for a in children if a.typ == b"elst"), None)
    if not elst or len(elst.payload) < 8:
        return None
    p = elst.payload
    ver = p[0]
    cnt = struct.unpack_from(">I", p, 4)[0]
    q = 8
    total = 0
    for _ in range(cnt):
        if ver == 1 and q + 20 <= len(p):
            seg_d = struct.unpack_from(">q", p, q)[0]
            if seg_d > 0:
                total += int(seg_d)
            q += 20
        elif ver == 0 and q + 12 <= len(p):
            seg_d = struct.unpack_from(">i", p, q)[0]
            if seg_d > 0:
                total += int(seg_d)
            q += 12
    return total


def _patch_edts_elst(
    edts: _RawAtom,
    media_scale: Fraction | None = None,
    add_last_segment_mvhd: int = 0,
) -> bytes:
    """Scale elst.media_time by media_scale while keeping segment_duration in mvhd timescale."""
    children = _parse_atoms(edts.payload)
    parts: list[bytes] = []
    for ch in children:
        if ch.typ == b"elst" and len(ch.payload) >= 8:
            p = bytearray(ch.payload)
            ver = p[0]
            cnt = struct.unpack_from(">I", p, 4)[0]
            q = 8
            step = 20 if ver == 1 else 12
            for idx in range(cnt):
                is_last = idx == cnt - 1
                if ver == 1 and q + 20 <= len(p):
                    seg_dur, media_time = struct.unpack_from(">qq", p, q)
                    if is_last and add_last_segment_mvhd != 0 and seg_dur > 0:
                        seg_dur += add_last_segment_mvhd
                        struct.pack_into(">q", p, q, seg_dur)
                    if media_scale is not None and media_time >= 0:
                        new_mt = _scale_int(media_time, media_scale, signed=True, bits=64)
                        struct.pack_into(">q", p, q + 8, new_mt)
                elif ver == 0 and q + 12 <= len(p):
                    seg_dur, media_time = struct.unpack_from(">ii", p, q)
                    if is_last and add_last_segment_mvhd != 0 and seg_dur > 0:
                        seg_dur += add_last_segment_mvhd
                        struct.pack_into(">i", p, q, seg_dur)
                    if media_scale is not None and media_time >= 0:
                        new_mt = _scale_int(media_time, media_scale, signed=True, bits=32)
                        struct.pack_into(">i", p, q + 4, new_mt)
                q += step
            parts.append(_build_box(b"elst", bytes(p)))
        else:
            parts.append(ch.data)
    return _build_box(b"edts", b"".join(parts))


def _check_disk_space(target_path: Path, required_bytes: int) -> None:
    """Verify target drive has sufficient free space before writing container."""
    try:
        parent = target_path.parent if target_path.parent.exists() else Path.cwd()
        free_bytes = shutil.disk_usage(parent).free
        if free_bytes < required_bytes + DISK_HEADROOM_BYTES:
            raise PatchError(
                f"Insufficient disk space on '{parent}': requires "
                f"{(required_bytes + DISK_HEADROOM_BYTES) // (1024 * 1024)} MB, "
                f"available {free_bytes // (1024 * 1024)} MB."
            )
    except PatchError:
        raise
    except Exception:
        pass


class MethodBXDDirectPatch:
    """BXD Container Engine supporting PC-oriented BXD and Mobile-safe ISO-BMFF presets."""

    def __init__(
        self,
        src: Path,
        out: Path,
        target_timescale: int | None = None,
        multiplier: int = 10,
        indeterminate_mvhd: bool = True,
        strip_edts: bool = True,
        preset_mode: str = "bxd-pc",
        padding_bytes: int = 0,
        max_tail_ms: int = 50,
        emit: Callable[[str], None] = lambda _: None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.src = src
        self.out = out
        self.target_timescale = target_timescale
        self.multiplier = max(2, multiplier)
        self.preset_mode = preset_mode
        self.padding_bytes = max(0, min(MAX_PADDING_BYTES, int(padding_bytes)))
        self.max_tail_ms = max(0, min(5000, int(max_tail_ms)))
        self.emit = emit
        self.cancel_event = cancel_event

        # Configure flags based on preset_mode when using standard preset names
        # All X1T presets apply indeterminate mvhd for TikTok bypass
        self.indeterminate_mvhd = True
        normalized_mode = preset_mode.lower().replace("x1t-", "bxd-")
        if normalized_mode in ("bxd-mobile", "bxd-hybrid", "bxd-clean"):
            self.strip_edts = False
            self.inflate_audio_table = False
        else:
            self.strip_edts = strip_edts
            self.inflate_audio_table = True

    def execute(self) -> None:
        mode_title = {
            "bxd-pc": "X1T For PC (TikTok Transcoder Bypass)",
            "x1t-pc": "X1T For PC (TikTok Transcoder Bypass)",
            "bxd-experimental": "X1T For PC (TikTok Transcoder Bypass)",
            "x1t-experimental": "X1T For PC (TikTok Transcoder Bypass)",
            "bxd-mobile": "X1T For Mobile (TikTok Bypass + Mobile Compatible)",
            "x1t-mobile": "X1T For Mobile (TikTok Bypass + Mobile Compatible)",
            "bxd-hybrid": "X1T Hybrid (TikTok Bypass + Tail Delta Shaping)",
            "x1t-hybrid": "X1T Hybrid (TikTok Bypass + Tail Delta Shaping)",
            "bxd-clean": "X1T Clean (TikTok Bypass + Pure Timing)",
            "x1t-clean": "X1T Clean (TikTok Bypass + Pure Timing)",
        }.get(self.preset_mode, f"X1T ({self.preset_mode})")

        self.emit(f"[INIT] {mode_title}")
        self.emit(f"[READ] {self.src.name}")

        raw_bytes = self.src.read_bytes()
        top_atoms = _parse_atoms(raw_bytes)

        if any(a.typ == b"moof" for a in top_atoms):
            raise PatchError("Fragmented MP4 (moof) not supported by X1T method.")

        ftyp = next((a for a in top_atoms if a.typ == b"ftyp"), None)
        moov = next((a for a in top_atoms if a.typ == b"moov"), None)
        mdat = next((a for a in top_atoms if a.typ == b"mdat"), None)

        if not moov or not mdat:
            raise PatchError("Missing moov or mdat atom; not a standard MP4 container.")

        # Normalize .mov (QuickTime qt) containers to standard MP4 (mp42 / isom)
        is_mov = self.src.suffix.lower() == ".mov" or (
            ftyp is not None and len(ftyp.payload) >= 4 and ftyp.payload[:4] == b"qt  "
        )
        if is_mov or ftyp is None:
            self.emit("[NORMALIZE] Container branding: QuickTime (.mov) -> MP4 (isom/mp42)")
            ftyp_bytes = _build_box(b"ftyp", b"mp42\x00\x00\x02\x00isomiso2mp41mp42")
        else:
            ftyp_bytes = ftyp.data
        orig_mdat_payload = raw_bytes[mdat.start + mdat.header_size : mdat.start + mdat.size]
        orig_mdat_sha256 = hashlib.sha256(orig_mdat_payload).hexdigest()

        if self.cancel_event and self.cancel_event.is_set():
            raise PatchCancelledError("Patch cancelled by user.")

        self.emit("[PARSE] Parsing tracks and timing structures...")
        moov_children = _parse_atoms(moov.payload)

        mvhd_atom = next((a for a in moov_children if a.typ == b"mvhd"), None)
        if not mvhd_atom:
            raise PatchError("Missing mvhd atom in moov container.")
        _, mvhd_ts, orig_mvhd_dur = _read_mvhd_ts_and_dur(mvhd_atom)

        traks = [a for a in moov_children if a.typ == b"trak"]
        if not traks:
            raise PatchError("No tracks found in container.")

        # Classify tracks (supports primary video, primary audio, multi-audio, and tmcd/other)
        video_trak: _RawAtom | None = None
        audio_trak: _RawAtom | None = None
        other_traks: list[_RawAtom] = []

        for trak in traks:
            trak_children = _parse_atoms(trak.payload)
            mdia = next((a for a in trak_children if a.typ == b"mdia"), None)
            if not mdia:
                other_traks.append(trak)
                continue
            mdia_children = _parse_atoms(mdia.payload)
            hdlr = next((a for a in mdia_children if a.typ == b"hdlr"), None)
            if not hdlr or len(hdlr.payload) < 12:
                other_traks.append(trak)
                continue
            h_type = hdlr.payload[8:12]
            if h_type == b"vide" and video_trak is None:
                video_trak = trak
            elif h_type == b"soun" and audio_trak is None:
                audio_trak = trak
            else:
                other_traks.append(trak)

        if not video_trak:
            raise PatchError("No video track found in source file.")

        v_orig_ts = self._extract_video_timescale(video_trak)
        eff_v_ts = (
            self.target_timescale
            if (self.target_timescale and self.target_timescale > 0)
            else v_orig_ts
        )
        video_scale: Fraction | None = None
        if v_orig_ts > 0 and eff_v_ts > 0 and v_orig_ts != eff_v_ts:
            video_scale = Fraction(eff_v_ts, v_orig_ts)
            self.emit(f"[PATCH] video timescale: {v_orig_ts} -> {eff_v_ts}")

        # Calculate Hybrid tail delta extension if preset_mode == "bxd-hybrid" or "x1t-hybrid"
        tail_add_mdhd = 0
        tail_add_mvhd = 0
        normalized_mode = self.preset_mode.lower().replace("x1t-", "bxd-")
        if normalized_mode == "bxd-hybrid" and self.max_tail_ms > 0 and eff_v_ts > 0:
            tail_add_mdhd = max(1, round((self.max_tail_ms / 1000.0) * eff_v_ts))
            if mvhd_ts > 0:
                tail_add_mvhd = round(tail_add_mdhd * mvhd_ts / eff_v_ts)
            self.emit(
                f"[PATCH] Hybrid tail delta shaping: +{tail_add_mdhd} ticks "
                f"({self.max_tail_ms} ms ceiling)"
            )

        # Parse audio track sample count for padding calculation
        has_audio = audio_trak is not None
        audio_info = (
            self._parse_audio_table(audio_trak) if (has_audio and audio_trak) else _AudioTableInfo()
        )
        base_pad_samples = (
            audio_info.sample_count if has_audio else self._extract_video_sample_count(video_trak)
        )
        default_pad_count = max(10, base_pad_samples * (self.multiplier - 1))

        # Determine trailing bytes vs standard ISO-BMFF free box
        ghost_nal_block = b""
        free_box_bytes = b""
        audio_pad_count = 0

        if self.inflate_audio_table:
            if has_audio and audio_trak:
                self.emit(
                    f"[INFLATE] Audio track {self.multiplier}x ghost sample inflation (PC mode)"
                )
                audio_pad_count = audio_info.sample_count * (self.multiplier - 1)
                ghost_nal_block = PADDING_NAL * audio_pad_count if audio_pad_count > 0 else b""
            else:
                self.emit("[INFLATE] Video-only container (no audio ghost table inflation)")
        elif normalized_mode in ("bxd-mobile", "bxd-hybrid"):
            pad_len = (
                self.padding_bytes
                if self.padding_bytes > 0
                else (default_pad_count * PADDING_SIZE)
            )
            pad_len = min(pad_len, MAX_PADDING_BYTES)
            free_box_bytes = _build_free_box(pad_len)
            self.emit(
                f"[INFLATE] ISO-BMFF compliant 'free' box padding ({len(free_box_bytes):,} bytes)"
            )

        # Reconstruct mvhd
        if self.indeterminate_mvhd:
            self.emit("[PATCH] mvhd.duration = indeterminate (-1)")
            new_mvhd = self._build_indeterminate_mvhd(mvhd_atom)
        elif tail_add_mvhd > 0:
            new_mvhd = _patch_mvhd_duration(mvhd_atom, orig_mvhd_dur + tail_add_mvhd)
        else:
            new_mvhd = mvhd_atom.data

        # Pre-build moov with dummy offsets to calculate exact final moov size
        dummy_moov = self._assemble_moov(
            new_mvhd=new_mvhd,
            video_trak=video_trak,
            audio_trak=audio_trak,
            other_traks=other_traks,
            shift=0,
            has_audio=has_audio,
            audio_info=audio_info,
            audio_pad_count=audio_pad_count,
            ghost_offset=0,
            video_scale=video_scale,
            eff_v_ts=eff_v_ts,
            mvhd_ts=mvhd_ts,
            tail_add_mdhd=tail_add_mdhd,
            tail_add_mvhd=tail_add_mvhd,
            moov_children=moov_children,
        )
        final_moov_size = len(dummy_moov)

        # Calculate exact shift for faststart (ftyp -> moov -> mdat)
        new_mdat_offset = len(ftyp_bytes) + final_moov_size
        old_mdat_offset = mdat.start
        shift = new_mdat_offset - old_mdat_offset
        ghost_offset = new_mdat_offset + mdat.size

        # Assemble final moov with real shifted offsets
        final_moov = self._assemble_moov(
            new_mvhd=new_mvhd,
            video_trak=video_trak,
            audio_trak=audio_trak,
            other_traks=other_traks,
            shift=shift,
            has_audio=has_audio,
            audio_info=audio_info,
            audio_pad_count=audio_pad_count,
            ghost_offset=ghost_offset,
            video_scale=video_scale,
            eff_v_ts=eff_v_ts,
            mvhd_ts=mvhd_ts,
            tail_add_mdhd=tail_add_mdhd,
            tail_add_mvhd=tail_add_mvhd,
            moov_children=moov_children,
        )
        if len(final_moov) != final_moov_size:
            final_moov_size = len(final_moov)
            new_mdat_offset = len(ftyp_bytes) + final_moov_size
            shift = new_mdat_offset - old_mdat_offset
            ghost_offset = new_mdat_offset + mdat.size
            final_moov = self._assemble_moov(
                new_mvhd=new_mvhd,
                video_trak=video_trak,
                audio_trak=audio_trak,
                other_traks=other_traks,
                shift=shift,
                has_audio=has_audio,
                audio_info=audio_info,
                audio_pad_count=audio_pad_count,
                ghost_offset=ghost_offset,
                video_scale=video_scale,
                eff_v_ts=eff_v_ts,
                mvhd_ts=mvhd_ts,
                tail_add_mdhd=tail_add_mdhd,
                tail_add_mvhd=tail_add_mvhd,
                moov_children=moov_children,
            )

        if self.cancel_event and self.cancel_event.is_set():
            raise PatchCancelledError("Patch cancelled by user.")

        expected_size = (
            len(ftyp_bytes)
            + len(final_moov)
            + len(mdat.data)
            + len(free_box_bytes)
            + len(ghost_nal_block)
        )
        _check_disk_space(self.out, expected_size)

        self.emit(f"[WRITE] Writing {mode_title} container...")
        final_output = ftyp_bytes + final_moov + mdat.data + free_box_bytes + ghost_nal_block
        self.out.write_bytes(final_output)

        # Explicit Structural and Payload Validation
        self.emit("[VERIFY] atom structure")
        struct_res = verify_atom_structure(final_output)
        if struct_res.malformed_atoms:
            self.out.unlink(missing_ok=True)
            details_str = "; ".join(struct_res.details)
            raise VerifyError(f"CRITICAL: Output atom structure corrupted: {details_str}")

        if struct_res.has_trailing_data:
            tb = struct_res.trailing_bytes_count
            self.emit(f"[REPORT] Structure status: {struct_res.status} ({tb} ghost bytes)")
        else:
            self.emit(f"[REPORT] Structure status: {struct_res.status}")

        self.emit("[VERIFY] chunk offsets")
        valid_offsets, offset_issues = verify_offsets(final_output)
        if not valid_offsets:
            msg = f"[REPORT] Chunk offsets status: EXPERIMENTAL ({len(offset_issues)} offsets)"
            self.emit(msg)

        self.emit("[VERIFY] sample tables")
        valid_tables, table_issues = verify_sample_tables(final_output)
        if not valid_tables:
            self.out.unlink(missing_ok=True)
            issues_str = "; ".join(table_issues)
            raise VerifyError(f"CRITICAL: Sample table validation failed: {issues_str}")

        self.emit("[VERIFY] mdat payload")
        verify_top = _parse_atoms(final_output)
        verify_mdat = next((a for a in verify_top if a.typ == b"mdat"), None)
        if not verify_mdat:
            self.out.unlink(missing_ok=True)
            raise VerifyError("Verification failed: output missing mdat atom.")

        verify_payload = final_output[
            verify_mdat.start + verify_mdat.header_size : verify_mdat.start + verify_mdat.size
        ]
        if hashlib.sha256(verify_payload).hexdigest() != orig_mdat_sha256:
            self.out.unlink(missing_ok=True)
            raise VerifyError("CRITICAL: mdat payload modified during patch.")

        mob_rep = verify_mobile_compatibility(final_output)
        self.emit(f"[VERIFY] mobile compatibility: {mob_rep.status}")
        if not mob_rep.compatible:
            for iss in mob_rep.issues[:3]:
                self.emit(f"[WARN] Mobile check: {iss}")

        self.emit(f"[SUCCESS] {mode_title} complete")

    def _extract_video_timescale(self, trak: _RawAtom) -> int:
        children = _parse_atoms(trak.payload)
        mdia = next((a for a in children if a.typ == b"mdia"), None)
        if not mdia:
            return 0
        mdia_children = _parse_atoms(mdia.payload)
        mdhd = next((a for a in mdia_children if a.typ == b"mdhd"), None)
        if not mdhd:
            return 0
        ts, _ = _read_mdhd_ts_and_dur(mdhd)
        return ts

    def _extract_video_sample_count(self, trak: _RawAtom) -> int:
        pos = trak.data.find(b"stsz")
        if pos >= 4 and pos + 16 <= len(trak.data):
            return int(struct.unpack_from(">I", trak.data, pos + 12)[0])
        return 30

    def _build_indeterminate_mvhd(self, mvhd_atom: _RawAtom) -> bytes:
        data = mvhd_atom.data
        ver = data[8]
        if ver == 0:
            c_time, m_time, ts = struct.unpack_from(">III", data, 12)
            tail = data[28:]
        else:
            c_time, m_time, ts = struct.unpack_from(">QQI", data, 12)
            tail = data[36:]
        v_flg = 1 << 24
        payload = struct.pack(">IQQIQ", v_flg, c_time, m_time, ts, 0xFFFFFFFFFFFFFFFF) + tail
        return _build_box(b"mvhd", payload)

    def _parse_audio_table(self, trak: _RawAtom) -> _AudioTableInfo:
        data = trak.data
        pos = data.find(b"soun")
        if pos < 0:
            return _AudioTableInfo()
        stbl_pos = data.find(b"stbl", pos) - 4
        s = struct.unpack_from(">I", data, stbl_pos)[0]
        stbl_bytes = data[stbl_pos : stbl_pos + s]

        # stsz
        stsz_pos = stbl_bytes.find(b"stsz") - 4
        def_sz, count = struct.unpack_from(">II", stbl_bytes, stsz_pos + 12)
        sizes: list[int] = []
        if def_sz > 0:
            sizes = [def_sz] * count
        else:
            p = stsz_pos + 20
            for _ in range(count):
                sizes.append(struct.unpack_from(">I", stbl_bytes, p)[0])
                p += 4

        # stts
        stts_pos = stbl_bytes.find(b"stts") - 4
        stts_cnt = struct.unpack_from(">I", stbl_bytes, stts_pos + 12)[0]
        stts: list[tuple[int, int]] = []
        p = stts_pos + 16
        for _ in range(stts_cnt):
            sc, sd = struct.unpack_from(">II", stbl_bytes, p)
            stts.append((sc, sd))
            p += 8

        # stsc
        stsc_pos = stbl_bytes.find(b"stsc") - 4
        stsc_cnt = struct.unpack_from(">I", stbl_bytes, stsc_pos + 12)[0]
        stsc: list[tuple[int, int, int]] = []
        p = stsc_pos + 16
        for _ in range(stsc_cnt):
            first, spc, didx = struct.unpack_from(">III", stbl_bytes, p)
            stsc.append((first, spc, didx))
            p += 12

        # stco / co64
        stco_pos = stbl_bytes.find(b"stco")
        offsets: list[int] = []
        if stco_pos >= 0:
            stco_p = stco_pos - 4
            stco_cnt = struct.unpack_from(">I", stbl_bytes, stco_p + 12)[0]
            p = stco_p + 16
            for _ in range(stco_cnt):
                offsets.append(struct.unpack_from(">I", stbl_bytes, p)[0])
                p += 4
        else:
            co64_pos = stbl_bytes.find(b"co64")
            if co64_pos >= 0:
                co64_p = co64_pos - 4
                co64_cnt = struct.unpack_from(">I", stbl_bytes, co64_p + 12)[0]
                p = co64_p + 16
                for _ in range(co64_cnt):
                    offsets.append(struct.unpack_from(">Q", stbl_bytes, p)[0])
                    p += 8

        return _AudioTableInfo(
            sample_count=count,
            sizes=sizes,
            stts=stts,
            stsc=stsc,
            offsets=offsets,
        )

    def _assemble_moov(
        self,
        new_mvhd: bytes,
        video_trak: _RawAtom,
        audio_trak: _RawAtom | None,
        other_traks: list[_RawAtom],
        shift: int,
        has_audio: bool,
        audio_info: _AudioTableInfo,
        audio_pad_count: int,
        ghost_offset: int,
        video_scale: Fraction | None,
        eff_v_ts: int,
        mvhd_ts: int,
        tail_add_mdhd: int,
        tail_add_mvhd: int,
        moov_children: list[_RawAtom],
    ) -> bytes:
        parts: list[bytes] = [new_mvhd]

        new_v_trak = self._rebuild_video_trak(
            video_trak, shift, video_scale, eff_v_ts, mvhd_ts, tail_add_mdhd, tail_add_mvhd
        )
        parts.append(new_v_trak)

        if has_audio and audio_trak:
            if self.inflate_audio_table and audio_pad_count > 0:
                new_a_trak = self._rebuild_audio_trak(
                    audio_trak, shift, audio_info, audio_pad_count, ghost_offset
                )
            else:
                new_a_trak = self._rebuild_generic_trak(audio_trak, shift)
            parts.append(new_a_trak)

        for ot in other_traks:
            new_ot = self._rebuild_generic_trak(ot, shift)
            parts.append(new_ot)

        for extra in moov_children:
            if extra.typ not in (b"mvhd", b"trak"):
                parts.append(extra.data)

        return _build_box(b"moov", b"".join(parts))

    def _rebuild_video_trak(
        self,
        trak: _RawAtom,
        shift: int,
        scale: Fraction | None,
        eff_v_ts: int,
        mvhd_ts: int,
        tail_add_mdhd: int,
        tail_add_mvhd: int,
    ) -> bytes:
        children = _parse_atoms(trak.payload)
        new_mdia_bytes, new_mdhd_dur = self._rebuild_video_mdia(
            next(c for c in children if c.typ == b"mdia"),
            shift,
            scale,
            eff_v_ts,
            tail_add_mdhd,
        )

        # Update edts first if present and not stripped
        new_edts_bytes: bytes | None = None
        elst_sum: int | None = None
        edts_atom = next((c for c in children if c.typ == b"edts"), None)
        if edts_atom is not None and not self.strip_edts:
            new_edts_bytes = _patch_edts_elst(
                edts_atom, media_scale=scale, add_last_segment_mvhd=tail_add_mvhd
            )
            parsed_edts = _parse_atoms(new_edts_bytes)[0]
            elst_sum = _sum_elst_segment_durations(parsed_edts)

        parts: list[bytes] = []
        for ch in children:
            if ch.typ == b"edts":
                if new_edts_bytes is not None:
                    parts.append(new_edts_bytes)
            elif ch.typ == b"tkhd":
                if not self.strip_edts and mvhd_ts > 0 and eff_v_ts > 0:
                    if elst_sum is not None and elst_sum > 0:
                        parts.append(_patch_tkhd_duration(ch, elst_sum))
                    elif new_mdhd_dur > 0:
                        expected_tk = round(new_mdhd_dur * mvhd_ts / eff_v_ts)
                        parts.append(_patch_tkhd_duration(ch, expected_tk))
                    elif tail_add_mvhd > 0:
                        orig_tk_dur = _read_tkhd_duration(ch)
                        parts.append(_patch_tkhd_duration(ch, orig_tk_dur + tail_add_mvhd))
                    else:
                        parts.append(ch.data)
                else:
                    parts.append(ch.data)
            elif ch.typ == b"mdia":
                parts.append(new_mdia_bytes)
            else:
                parts.append(ch.data)
        return _build_box(b"trak", b"".join(parts))

    def _rebuild_video_mdia(
        self,
        mdia: _RawAtom,
        shift: int,
        scale: Fraction | None,
        eff_v_ts: int,
        tail_add_mdhd: int,
    ) -> tuple[bytes, int]:
        children = _parse_atoms(mdia.payload)
        minf_atom = next(c for c in children if c.typ == b"minf")
        new_minf_bytes, stts_sum = self._rebuild_video_minf(minf_atom, shift, scale, tail_add_mdhd)

        parts: list[bytes] = []
        final_mdhd_dur = stts_sum
        for ch in children:
            if ch.typ == b"mdhd":
                orig_ts, orig_dur = _read_mdhd_ts_and_dur(ch)
                use_ts = eff_v_ts if eff_v_ts > 0 else orig_ts
                use_dur = stts_sum if stts_sum > 0 else orig_dur
                final_mdhd_dur = use_dur
                if scale is not None or tail_add_mdhd > 0:
                    parts.append(_patch_mdhd_values(ch, use_ts, use_dur))
                else:
                    parts.append(ch.data)
            elif ch.typ == b"minf":
                parts.append(new_minf_bytes)
            else:
                parts.append(ch.data)
        return _build_box(b"mdia", b"".join(parts)), final_mdhd_dur

    def _rebuild_video_minf(
        self, minf: _RawAtom, shift: int, scale: Fraction | None, tail_add_mdhd: int
    ) -> tuple[bytes, int]:
        children = _parse_atoms(minf.payload)
        parts: list[bytes] = []
        stts_sum = 0
        for ch in children:
            if ch.typ == b"stbl":
                stbl_b, stts_sum = self._rebuild_video_stbl(ch, shift, scale, tail_add_mdhd)
                parts.append(stbl_b)
            else:
                parts.append(ch.data)
        return _build_box(b"minf", b"".join(parts)), stts_sum

    def _rebuild_video_stbl(
        self, stbl: _RawAtom, shift: int, scale: Fraction | None, tail_add_mdhd: int
    ) -> tuple[bytes, int]:
        children = _parse_atoms(stbl.payload)
        parts: list[bytes] = []
        stts_sum = 0
        for ch in children:
            if ch.typ == b"stco":
                cnt = struct.unpack_from(">I", ch.data, 12)[0]
                offsets = [
                    struct.unpack_from(">I", ch.data, 16 + i * 4)[0] + shift
                    for i in range(cnt)
                ]
                parts.append(_build_stco(offsets))
            elif ch.typ == b"co64":
                cnt = struct.unpack_from(">I", ch.data, 12)[0]
                offsets = [
                    struct.unpack_from(">Q", ch.data, 16 + i * 8)[0] + shift
                    for i in range(cnt)
                ]
                parts.append(_build_stco(offsets, force_co64=True))
            elif ch.typ == b"stts":
                new_stts_b, stts_sum = self._scale_and_shape_stts(ch, scale, tail_add_mdhd)
                parts.append(new_stts_b)
            elif ch.typ == b"ctts" and scale is not None:
                parts.append(self._scale_ctts(ch, scale))
            else:
                parts.append(ch.data)
        return _build_box(b"stbl", b"".join(parts)), stts_sum

    def _scale_and_shape_stts(
        self, stts: _RawAtom, scale: Fraction | None, tail_add_mdhd: int
    ) -> tuple[bytes, int]:
        data = stts.data
        count = struct.unpack_from(">I", data, 12)[0]
        deltas: list[int] = []
        p = 16
        for _ in range(count):
            sc, d = struct.unpack_from(">II", data, p)
            deltas.extend([d] * sc)
            p += 8
        if scale is not None:
            deltas = _scale_deltas(deltas, scale)
        if tail_add_mdhd > 0 and deltas:
            deltas[-1] += tail_add_mdhd
        total_dur = sum(deltas)
        if scale is None and tail_add_mdhd == 0:
            return data, total_dur
        runs = _compress_values(deltas)
        v_flg = struct.unpack_from(">I", data, 8)[0]
        payload = struct.pack(">I", len(runs)) + b"".join(
            struct.pack(">II", c, d) for c, d in runs
        )
        return struct.pack(">I4sI", len(payload) + 12, b"stts", v_flg) + payload, total_dur

    def _scale_ctts(self, ctts: _RawAtom, scale: Fraction) -> bytes:
        data = ctts.data
        count = struct.unpack_from(">I", data, 12)[0]
        out_entries: list[tuple[int, int]] = []
        p = 16
        for _ in range(count):
            sc, off = struct.unpack_from(">Ii", data, p)
            new_off = _scale_int(off, scale, signed=True, bits=32)
            out_entries.append((sc, new_off))
            p += 8
        v_flg = struct.unpack_from(">I", data, 8)[0]
        payload = struct.pack(">I", len(out_entries)) + b"".join(
            struct.pack(">Ii", sc, off) for sc, off in out_entries
        )
        return struct.pack(">I4sI", len(payload) + 12, b"ctts", v_flg) + payload

    def _rebuild_audio_trak(
        self,
        trak: _RawAtom,
        shift: int,
        info: _AudioTableInfo,
        pad_count: int,
        ghost_offset: int,
    ) -> bytes:
        children = _parse_atoms(trak.payload)
        parts: list[bytes] = []
        for ch in children:
            if self.strip_edts and ch.typ == b"edts":
                continue
            if ch.typ == b"mdia":
                parts.append(
                    self._rebuild_audio_mdia(ch, shift, info, pad_count, ghost_offset)
                )
            else:
                parts.append(ch.data)
        return _build_box(b"trak", b"".join(parts))

    def _rebuild_generic_trak(self, trak: _RawAtom, shift: int) -> bytes:
        children = _parse_atoms(trak.payload)
        parts: list[bytes] = []
        for ch in children:
            if self.strip_edts and ch.typ == b"edts":
                continue
            if ch.typ == b"mdia":
                parts.append(self._rebuild_mdia(ch, shift))
            else:
                parts.append(ch.data)
        return _build_box(b"trak", b"".join(parts))

    def _rebuild_mdia(self, mdia: _RawAtom, shift: int) -> bytes:
        children = _parse_atoms(mdia.payload)
        parts: list[bytes] = []
        for ch in children:
            if ch.typ == b"minf":
                parts.append(self._rebuild_minf(ch, shift))
            else:
                parts.append(ch.data)
        return _build_box(b"mdia", b"".join(parts))

    def _rebuild_audio_mdia(
        self,
        mdia: _RawAtom,
        shift: int,
        info: _AudioTableInfo,
        pad_count: int,
        ghost_offset: int,
    ) -> bytes:
        children = _parse_atoms(mdia.payload)
        parts: list[bytes] = []
        for ch in children:
            if ch.typ == b"minf":
                parts.append(
                    self._rebuild_audio_minf(ch, shift, info, pad_count, ghost_offset)
                )
            else:
                parts.append(ch.data)
        return _build_box(b"mdia", b"".join(parts))

    def _rebuild_minf(self, minf: _RawAtom, shift: int) -> bytes:
        children = _parse_atoms(minf.payload)
        parts: list[bytes] = []
        for ch in children:
            if ch.typ == b"stbl":
                parts.append(self._shift_stbl_stco(ch, shift))
            else:
                parts.append(ch.data)
        return _build_box(b"minf", b"".join(parts))

    def _rebuild_audio_minf(
        self,
        minf: _RawAtom,
        shift: int,
        info: _AudioTableInfo,
        pad_count: int,
        ghost_offset: int,
    ) -> bytes:
        children = _parse_atoms(minf.payload)
        parts: list[bytes] = []
        for ch in children:
            if ch.typ == b"stbl":
                parts.append(
                    self._build_inflated_audio_stbl(ch, shift, info, pad_count, ghost_offset)
                )
            else:
                parts.append(ch.data)
        return _build_box(b"minf", b"".join(parts))

    def _shift_stbl_stco(self, stbl: _RawAtom, shift: int) -> bytes:
        children = _parse_atoms(stbl.payload)
        parts: list[bytes] = []
        for ch in children:
            if ch.typ == b"stco":
                cnt = struct.unpack_from(">I", ch.data, 12)[0]
                offsets = [
                    struct.unpack_from(">I", ch.data, 16 + i * 4)[0] + shift
                    for i in range(cnt)
                ]
                parts.append(_build_stco(offsets))
            elif ch.typ == b"co64":
                cnt = struct.unpack_from(">I", ch.data, 12)[0]
                offsets = [
                    struct.unpack_from(">Q", ch.data, 16 + i * 8)[0] + shift
                    for i in range(cnt)
                ]
                parts.append(_build_stco(offsets, force_co64=True))
            else:
                parts.append(ch.data)
        return _build_box(b"stbl", b"".join(parts))

    def _build_inflated_audio_stbl(
        self,
        stbl: _RawAtom,
        shift: int,
        info: _AudioTableInfo,
        pad_count: int,
        ghost_offset: int,
    ) -> bytes:
        orig_sizes = list(info.sizes)
        orig_stts = list(info.stts)
        orig_stsc = list(info.stsc)
        orig_offsets = list(info.offsets)

        new_sizes = orig_sizes + [PADDING_SIZE] * pad_count
        new_stts = orig_stts + [(pad_count, 1)]
        new_stsc = orig_stsc + [(len(orig_offsets) + 1, pad_count, 1)]
        new_offsets = [off + shift for off in orig_offsets] + [ghost_offset]

        children = _parse_atoms(stbl.payload)
        parts: list[bytes] = []
        for ch in children:
            if ch.typ == b"stts":
                parts.append(_build_stts(new_stts))
            elif ch.typ == b"stsz":
                parts.append(_build_stsz(new_sizes))
            elif ch.typ == b"stsc":
                parts.append(_build_stsc(new_stsc))
            elif ch.typ in (b"stco", b"co64"):
                parts.append(_build_stco(new_offsets))
            else:
                parts.append(ch.data)
        return _build_box(b"stbl", b"".join(parts))


# ==============================================================================
# PHASE 0: ISOLATION HYPOTHESIS VARIANT GENERATOR (H1 - H4)
# ==============================================================================


def generate_isolation_variants(
    src: Path, out_dir: Path, target_timescale: int | None = None
) -> dict[str, Path]:
    """Generate 4 single-variable isolation MP4s from `src` to test hypotheses H1-H4 independently.

    H1: Only indeterminate mvhd.duration (-1)
    H2: Only audio 8-byte ghost sample inflation placed INSIDE mdat bounds
    H3: Only unboxed trailing bytes + stco pointing outside mdat
    H4: Only stripped edts/elst boxes
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    variants: dict[str, Path] = {}

    # H1: Only indeterminate mvhd.duration (-1), valid audio, valid edts, no trailing data
    h1_path = out_dir / f"{src.stem}_H1_only_indeterminate_mvhd{src.suffix}"
    p_h1 = MethodBXDDirectPatch(
        src=src,
        out=h1_path,
        target_timescale=target_timescale,
        indeterminate_mvhd=True,
        strip_edts=False,
        preset_mode="bxd-pc",
    )
    p_h1.inflate_audio_table = False
    p_h1.execute()
    variants["H1"] = h1_path

    # H3: Only unboxed trailing ghost bytes + stco outside mdat (valid mvhd, valid edts)
    h3_path = out_dir / f"{src.stem}_H3_only_unboxed_trailing_stco{src.suffix}"
    p_h3 = MethodBXDDirectPatch(
        src=src,
        out=h3_path,
        target_timescale=target_timescale,
        indeterminate_mvhd=False,
        strip_edts=False,
        preset_mode="bxd-pc",
    )
    p_h3.execute()

    # H2: Audio ghost sample table inflation where ghost bytes are encapsulated INSIDE mdat
    h2_path = out_dir / f"{src.stem}_H2_only_audio_ghost_in_mdat{src.suffix}"
    raw_h3 = h3_path.read_bytes()
    top_h3 = _parse_atoms(raw_h3)
    ftyp_h3 = next((a.data for a in top_h3 if a.typ == b"ftyp"), b"")
    moov_h3 = next((a.data for a in top_h3 if a.typ == b"moov"), b"")
    mdat_h3 = next((a for a in top_h3 if a.typ == b"mdat"), None)
    if mdat_h3 is not None:
        trailing_ghost = raw_h3[mdat_h3.start + mdat_h3.size :]
        expanded_mdat = _build_box(b"mdat", mdat_h3.payload + trailing_ghost)
        h2_path.write_bytes(ftyp_h3 + moov_h3 + expanded_mdat)
    variants["H2"] = h2_path
    variants["H3"] = h3_path

    # H4: Only stripped edts/elst (valid mvhd, valid audio, no trailing data)
    h4_path = out_dir / f"{src.stem}_H4_only_stripped_edts{src.suffix}"
    p_h4 = MethodBXDDirectPatch(
        src=src,
        out=h4_path,
        target_timescale=target_timescale,
        indeterminate_mvhd=False,
        strip_edts=True,
        preset_mode="bxd-pc",
    )
    p_h4.inflate_audio_table = False
    p_h4.execute()
    variants["H4"] = h4_path

    return variants


# ==============================================================================
# LOSSLESS MOBILE REPAIR ENGINE (`repair_for_mobile`)
# ==============================================================================


def _extract_first_ctts_offset(stbl: _RawAtom) -> int:
    """Return the composition offset of the first sample in ctts (or 0 if absent/<=0)."""
    children = _parse_atoms(stbl.payload)
    ctts = next((c for c in children if c.typ == b"ctts"), None)
    if not ctts or len(ctts.payload) < 16:
        return 0
    cnt = struct.unpack_from(">I", ctts.payload, 4)[0]
    if cnt == 0:
        return 0
    _, first_off = struct.unpack_from(">Ii", ctts.payload, 8)
    return max(0, int(first_off))


def _clean_stbl_ghosts(
    raw_file: bytes,
    stbl: _RawAtom,
    mdat_payload_start: int,
    mdat_end: int,
    handler_type: bytes,
) -> tuple[_RawAtom, int, int, list[int]]:
    """Strip confirmed BXD ghost chunks/samples from stbl.

    Primary criterion: chunk_offset outside [mdat_payload_start, mdat_end).
    Confirmation gate: every sample in that chunk must have size == 8 (PADDING_SIZE),
    belong to a delta == 1 stts tail, and match PADDING_NAL bytes in raw_file.
    Also strips confirmed in-mdat BXD audio ghost tail (H2).
    Raises PatchError if out-of-mdat chunks do not match BXD PADDING_NAL signature.

    Returns (cleaned_stbl_atom, removed_ghost_samples, real_stts_duration_sum, real_chunk_offsets).
    """
    children = _parse_atoms(stbl.payload)
    stsz_atom = next((c for c in children if c.typ == b"stsz"), None)
    stts_atom = next((c for c in children if c.typ == b"stts"), None)
    stsc_atom = next((c for c in children if c.typ == b"stsc"), None)
    co_atom = next((c for c in children if c.typ in (b"stco", b"co64")), None)

    if not stsz_atom or not stts_atom or not stsc_atom or not co_atom:
        return stbl, 0, 0, []

    # Parse sizes
    def_sz, s_count = struct.unpack_from(">II", stsz_atom.payload, 4)
    if def_sz > 0:
        sizes = [def_sz] * s_count
    else:
        sizes = [
            struct.unpack_from(">I", stsz_atom.payload, 12 + i * 4)[0]
            for i in range(s_count)
        ]

    # Parse stts runs & expand deltas per sample
    stts_cnt = struct.unpack_from(">I", stts_atom.payload, 4)[0]
    stts_runs: list[tuple[int, int]] = [
        struct.unpack_from(">II", stts_atom.payload, 8 + i * 8) for i in range(stts_cnt)
    ]
    sample_deltas: list[int] = []
    for sc, sd in stts_runs:
        sample_deltas.extend([sd] * sc)

    # Parse stsc
    stsc_cnt = struct.unpack_from(">I", stsc_atom.payload, 4)[0]
    stsc_entries: list[tuple[int, int, int]] = [
        struct.unpack_from(">III", stsc_atom.payload, 8 + i * 12) for i in range(stsc_cnt)
    ]

    # Parse chunk offsets
    co_cnt = struct.unpack_from(">I", co_atom.payload, 4)[0]
    if co_atom.typ == b"stco":
        offsets = [
            struct.unpack_from(">I", co_atom.payload, 8 + i * 4)[0] for i in range(co_cnt)
        ]
    else:
        offsets = [
            struct.unpack_from(">Q", co_atom.payload, 8 + i * 8)[0] for i in range(co_cnt)
        ]

    real_offsets: list[int] = []
    real_sizes: list[int] = []
    real_deltas: list[int] = []
    removed_samples = 0
    sample_idx = 0

    for c_idx, c_off in enumerate(offsets):
        chunk_num = c_idx + 1
        spc = 0
        for fc, s_per_c, _ in stsc_entries:
            if fc <= chunk_num:
                spc = s_per_c
            else:
                break

        c_sizes = sizes[sample_idx : sample_idx + spc]
        c_deltas = sample_deltas[sample_idx : sample_idx + spc]
        sample_idx += spc

        outside_mdat = not (mdat_payload_start <= c_off < mdat_end)
        # Also detect H2 (in-mdat BXD audio ghost chunk at end of audio track)
        is_h2_audio_ghost = (
            not outside_mdat
            and handler_type == b"soun"
            and c_idx == len(offsets) - 1
            and len(offsets) > 1
            and spc >= 5
            and all(s == PADDING_SIZE for s in c_sizes)
            and all(d == 1 for d in c_deltas)
            and c_off + spc * PADDING_SIZE <= len(raw_file)
            and raw_file[c_off : c_off + PADDING_SIZE] == PADDING_NAL
        )

        if outside_mdat or is_h2_audio_ghost:
            # Strict Confirmation Gate: must match BXD 8-byte PADDING_NAL across entire chunk
            all_size_8 = bool(c_sizes) and all(s == PADDING_SIZE for s in c_sizes)
            all_delta_1 = bool(c_deltas) and all(d == 1 for d in c_deltas)
            expected_chunk_bytes = PADDING_NAL * len(c_sizes)
            bytes_match = (
                c_off + len(expected_chunk_bytes) <= len(raw_file)
                and raw_file[c_off : c_off + len(expected_chunk_bytes)] == expected_chunk_bytes
            )
            if not (all_size_8 and all_delta_1 and bytes_match):
                raise PatchError(
                    f"Confirmation Gate failed in repair_for_mobile: chunk {chunk_num} at "
                    f"offset {c_off} is outside mdat ({mdat_payload_start}..{mdat_end}) "
                    f"but does not match BXD PADDING_NAL signature (size_8={all_size_8}, "
                    f"delta_1={all_delta_1}, nal_match={bytes_match})."
                )
            removed_samples += len(c_sizes)
        else:
            real_offsets.append(c_off)
            real_sizes.extend(c_sizes)
            real_deltas.extend(c_deltas)

    real_stts_runs = _compress_values(real_deltas)
    real_stts_sum = sum(real_deltas)
    max_chunk = len(real_offsets)
    real_stsc = [(fc, spc, didx) for fc, spc, didx in stsc_entries if fc <= max_chunk]

    new_parts: list[bytes] = []
    for ch in children:
        if ch.typ == b"stsz":
            new_parts.append(_build_stsz(real_sizes))
        elif ch.typ == b"stts":
            new_parts.append(_build_stts(real_stts_runs))
        elif ch.typ == b"stsc":
            new_parts.append(_build_stsc(real_stsc))
        elif ch.typ in (b"stco", b"co64"):
            new_parts.append(
                _build_stco(real_offsets, force_co64=(ch.typ == b"co64"))
            )
        else:
            new_parts.append(ch.data)

    new_stbl_bytes = _build_box(b"stbl", b"".join(new_parts))
    return _parse_atoms(new_stbl_bytes)[0], removed_samples, real_stts_sum, real_offsets


def repair_for_mobile(
    src: Path,
    out: Path,
    emit: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    """Repair a BXD PC-oriented MP4 into a clean ISO-BMFF mobile-compatible MP4 without re-encoding.

    Strict 6-step order:
    1. Record baseline SHA-256 of real samples inside mdat for every track.
    2. Strip confirmed BXD ghost samples/chunks from stbl (fail-safe if non-BXD corruption).
    3. Parse post-mdat region: keep valid ISO-BMFF boxes (free/skip/udta/meta/uuid), strip raw tail.
    4. Recompute mdhd.duration from sum of cleaned stts for every track.
    5. Reconstruct video edts/elst from ctts first offset BEFORE computing tkhd.duration.
    6. Compute tkhd.duration (from elst sum if present, else scaled mdhd) & mvhd.duration,
       shift chunk offsets, and verify 100% lossless real sample payload hashes.
    """
    if src.resolve() == out.resolve():
        raise PatchError("Refusing to repair in-place: output path must differ from source.")

    emit(f"[REPAIR] Inspecting {src.name} for mobile compatibility repair...")
    raw_bytes = src.read_bytes()

    # Step 1: Baseline SHA-256 of real in-mdat samples
    orig_analyzer = MP4ForensicAnalyzer(raw_bytes, str(src))
    orig_report = orig_analyzer.parse()
    baseline_hashes = orig_analyzer.hash_real_mdat_samples(orig_report.atom_tree)

    top_atoms = _parse_atoms(raw_bytes)
    ftyp = next((a for a in top_atoms if a.typ == b"ftyp"), None)
    moov = next((a for a in top_atoms if a.typ == b"moov"), None)
    mdat = next((a for a in top_atoms if a.typ == b"mdat"), None)
    if not moov or not mdat:
        raise PatchError("Missing moov or mdat atom; cannot repair container.")

    is_mov = src.suffix.lower() == ".mov" or (
        ftyp is not None and len(ftyp.payload) >= 4 and ftyp.payload[:4] == b"qt  "
    )
    if is_mov or ftyp is None:
        emit("[NORMALIZE] Container branding: QuickTime (.mov) -> MP4 (isom/mp42)")
        ftyp_bytes = _build_box(b"ftyp", b"mp42\x00\x00\x02\x00isomiso2mp41mp42")
    else:
        ftyp_bytes = ftyp.data
    mdat_payload_start = mdat.start + mdat.header_size
    mdat_end = mdat.start + mdat.size

    # Step 3 preparation: Parse boxes after mdat.end, keep valid boxes, strip unparseable tail
    post_mdat_boxes, _, _ = _iter_boxes_raw(raw_bytes, mdat_end, len(raw_bytes))
    kept_post_boxes = b"".join(
        raw_bytes[pos : pos + size]
        for typ, pos, size, _ in post_mdat_boxes
        if typ in _SAFE_POST_MDAT_BOXES
    )
    stripped_trailing_bytes = (len(raw_bytes) - mdat_end) - len(kept_post_boxes)
    if stripped_trailing_bytes > 0:
        emit(f"[REPAIR] Stripped {stripped_trailing_bytes:,} unboxed trailing bytes after mdat")

    moov_children = _parse_atoms(moov.payload)
    mvhd_atom = next((a for a in moov_children if a.typ == b"mvhd"), None)
    if not mvhd_atom:
        raise PatchError("Missing mvhd atom.")
    _, mvhd_ts, _ = _read_mvhd_ts_and_dur(mvhd_atom)
    if mvhd_ts <= 0:
        mvhd_ts = 1000

    total_ghost_removed = 0
    reconstructed_video_edts = False
    audio_edts_missing_note = False

    def build_repaired_moov(shift: int) -> tuple[bytes, int, bool, bool]:
        nonlocal total_ghost_removed, reconstructed_video_edts, audio_edts_missing_note
        ghost_cnt = 0
        made_v_edts = False
        a_edts_missing = False
        rebuilt_traks: list[bytes] = []
        max_tkhd_dur = 0

        for ch in moov_children:
            if ch.typ != b"trak":
                continue
            t_children = _parse_atoms(ch.payload)
            tkhd_a = next((c for c in t_children if c.typ == b"tkhd"), None)
            edts_a = next((c for c in t_children if c.typ == b"edts"), None)
            mdia_a = next((c for c in t_children if c.typ == b"mdia"), None)
            if not tkhd_a or not mdia_a:
                rebuilt_traks.append(ch.data)
                continue

            m_children = _parse_atoms(mdia_a.payload)
            mdhd_a = next((c for c in m_children if c.typ == b"mdhd"), None)
            hdlr_a = next((c for c in m_children if c.typ == b"hdlr"), None)
            minf_a = next((c for c in m_children if c.typ == b"minf"), None)
            if not mdhd_a or not minf_a:
                rebuilt_traks.append(ch.data)
                continue

            h_type = hdlr_a.payload[8:12] if (hdlr_a and len(hdlr_a.payload) >= 12) else b""
            track_ts, orig_mdhd_dur = _read_mdhd_ts_and_dur(mdhd_a)
            if track_ts <= 0:
                track_ts = 1000

            minf_children = _parse_atoms(minf_a.payload)
            stbl_a = next((c for c in minf_children if c.typ == b"stbl"), None)
            if not stbl_a:
                rebuilt_traks.append(ch.data)
                continue

            # Step 2: Clean ghost samples from stbl
            cleaned_stbl, removed_n, real_stts_sum, _ = _clean_stbl_ghosts(
                raw_bytes, stbl_a, mdat_payload_start, mdat_end, h_type
            )
            ghost_cnt += removed_n

            # Apply chunk offset shift for new moov size
            shifted_stbl = _shift_stbl_atom(cleaned_stbl, shift)

            # Step 4: Recompute mdhd.duration from sum of cleaned stts
            real_mdhd_dur = real_stts_sum if real_stts_sum > 0 else orig_mdhd_dur
            new_mdhd_bytes = _patch_mdhd_values(mdhd_a, track_ts, real_mdhd_dur)

            # Rebuild minf & mdia
            new_minf_parts = [
                shifted_stbl if mc.typ == b"stbl" else mc.data for mc in minf_children
            ]
            new_minf_bytes = _build_box(b"minf", b"".join(new_minf_parts))
            new_mdia_parts = []
            for mc in m_children:
                if mc.typ == b"mdhd":
                    new_mdia_parts.append(new_mdhd_bytes)
                elif mc.typ == b"minf":
                    new_mdia_parts.append(new_minf_bytes)
                else:
                    new_mdia_parts.append(mc.data)
            new_mdia_bytes = _build_box(b"mdia", b"".join(new_mdia_parts))

            # Step 5: Reconstruct video edts/elst from ctts first offset BEFORE tkhd.duration
            new_edts_bytes: bytes | None = None
            elst_seg_sum: int | None = None

            if edts_a is not None:
                elst_seg_sum = _sum_elst_segment_durations(edts_a)
                new_edts_bytes = edts_a.data
            elif h_type == b"vide":
                first_ctts = _extract_first_ctts_offset(cleaned_stbl)
                if first_ctts > 0:
                    playable_mdhd = max(0, real_mdhd_dur - first_ctts)
                    seg_dur = round(playable_mdhd * mvhd_ts / track_ts)
                    new_edts_bytes = _build_elst_single(seg_dur, first_ctts)
                    elst_seg_sum = seg_dur
                    made_v_edts = True
            elif h_type == b"soun":
                a_edts_missing = True

            # Step 6a: Compute tkhd.duration from elst sum (if present) or scaled mdhd
            if elst_seg_sum is not None and elst_seg_sum > 0:
                new_tkhd_dur = elst_seg_sum
            else:
                new_tkhd_dur = round(real_mdhd_dur * mvhd_ts / track_ts)
            max_tkhd_dur = max(max_tkhd_dur, new_tkhd_dur)
            new_tkhd_bytes = _patch_tkhd_duration(tkhd_a, new_tkhd_dur)

            # Assemble trak (tkhd -> edts -> mdia -> others)
            trak_parts: list[bytes] = [new_tkhd_bytes]
            if new_edts_bytes is not None:
                trak_parts.append(new_edts_bytes)
            trak_parts.append(new_mdia_bytes)
            for tc in t_children:
                if tc.typ not in (b"tkhd", b"edts", b"mdia"):
                    trak_parts.append(tc.data)
            rebuilt_traks.append(_build_box(b"trak", b"".join(trak_parts)))

        # Step 6b: Recompute mvhd.duration from max(tkhd.duration)
        new_mvhd_bytes = _patch_mvhd_duration(mvhd_atom, max_tkhd_dur)
        moov_parts: list[bytes] = [new_mvhd_bytes, *rebuilt_traks]
        for mc in moov_children:
            if mc.typ not in (b"mvhd", b"trak"):
                moov_parts.append(mc.data)
        return _build_box(b"moov", b"".join(moov_parts)), ghost_cnt, made_v_edts, a_edts_missing

    # Two-pass moov assembly to get exact faststart shift
    dummy_moov, _, _, _ = build_repaired_moov(0)
    moov_sz = len(dummy_moov)
    shift = (len(ftyp_bytes) + moov_sz) - mdat.start
    final_moov, total_ghost_removed, reconstructed_video_edts, audio_edts_missing_note = (
        build_repaired_moov(shift)
    )
    if len(final_moov) != moov_sz:
        moov_sz = len(final_moov)
        shift = (len(ftyp_bytes) + moov_sz) - mdat.start
        final_moov, total_ghost_removed, reconstructed_video_edts, audio_edts_missing_note = (
            build_repaired_moov(shift)
        )

    if total_ghost_removed > 0:
        emit(f"[REPAIR] Removed {total_ghost_removed:,} X1T ghost sample entries from stbl")
    if reconstructed_video_edts:
        emit("[REPAIR] Reconstructed video edts/elst from ctts start composition offset")
    if audio_edts_missing_note:
        emit(
            "[NOTE] Original audio edts/elst (AAC priming delay), "
            "if previously stripped, cannot be recovered."
        )

    repaired_bytes = ftyp_bytes + final_moov + mdat.data + kept_post_boxes
    _check_disk_space(out, len(repaired_bytes))
    tmp_out = out.with_name(out.name + ".repair_tmp")
    tmp_out.write_bytes(repaired_bytes)

    # Step 6c: Verify lossless real sample payload hashes & mobile compatibility
    rep_analyzer = MP4ForensicAnalyzer(repaired_bytes, str(out))
    rep_report = rep_analyzer.parse()
    repaired_hashes = rep_analyzer.hash_real_mdat_samples(rep_report.atom_tree)

    for t_id, (orig_cnt, orig_sha) in baseline_hashes.items():
        rep_cnt, rep_sha = repaired_hashes.get(t_id, (0, ""))
        if orig_cnt != rep_cnt or orig_sha != rep_sha:
            tmp_out.unlink(missing_ok=True)
            raise VerifyError(
                f"CRITICAL: Repair payload hash mismatch on track {t_id} "
                f"(samples {orig_cnt}->{rep_cnt}). Aborting to preserve lossless guarantee."
            )

    mob_check = verify_mobile_compatibility(repaired_bytes)
    if not mob_check.compatible:
        tmp_out.unlink(missing_ok=True)
        issues_str = "; ".join(mob_check.issues)
        raise VerifyError(f"Repaired container failed mobile check: {issues_str}")

    tmp_out.replace(out)
    emit(f"[SUCCESS] Repaired file saved to {out.name} ({mob_check.status})")
    return {
        "output": out,
        "ghost_samples_removed": total_ghost_removed,
        "stripped_trailing_bytes": stripped_trailing_bytes,
        "reconstructed_video_edts": reconstructed_video_edts,
        "mobile_status": mob_check.status,
    }


def _shift_stbl_atom(stbl: _RawAtom, shift: int) -> bytes:
    children = _parse_atoms(stbl.payload)
    parts: list[bytes] = []
    for ch in children:
        if ch.typ == b"stco":
            cnt = struct.unpack_from(">I", ch.data, 12)[0]
            offsets = [
                struct.unpack_from(">I", ch.data, 16 + i * 4)[0] + shift for i in range(cnt)
            ]
            parts.append(_build_stco(offsets))
        elif ch.typ == b"co64":
            cnt = struct.unpack_from(">I", ch.data, 12)[0]
            offsets = [
                struct.unpack_from(">Q", ch.data, 16 + i * 8)[0] + shift for i in range(cnt)
            ]
            parts.append(_build_stco(offsets, force_co64=True))
        else:
            parts.append(ch.data)
    return _build_box(b"stbl", b"".join(parts))
