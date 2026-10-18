"""Method V4 Direct Forensic Patch Engine.

Applies direct in-place container atom timing patches without re-encoding, transcoding,
or altering media payload bytes in `mdat`.
"""

from __future__ import annotations

import struct
import threading
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

from .atom_patcher import (
    Box,
    _find_children,
    _handler_type,
    _patch_ctts,
    _patch_elst,
    _patch_mdhd,
    _patch_stts,
    _read_box,
    _scale_int,
    _single_child,
)
from .errors import PatchCancelledError, PatchError, VerifyError
from .forensic_analyzer import MP4ForensicAnalyzer

EmitLog = Callable[[str], None]


class MethodV4DirectPatch:
    def __init__(
        self,
        src: Path,
        out: Path,
        target_timescale: int,
        sync_mvhd: bool = False,
        strict_lossless: bool = True,
        preserve_video: bool = True,
        preserve_audio: bool = True,
        dry_run: bool = False,
        export_report: bool = False,
        emit: EmitLog | None = None,
        cancel_event: threading.Event | None = None,
        max_file_size: int | None = None,
    ) -> None:
        self.src = src
        self.out = out
        self.target_timescale = target_timescale
        self.sync_mvhd = sync_mvhd
        self.strict_lossless = strict_lossless
        self.preserve_video = preserve_video
        self.preserve_audio = preserve_audio
        self.dry_run = dry_run
        self.export_report = export_report
        self.emit = emit or (lambda _: None)
        self.cancel_event = cancel_event
        self.max_file_size = max_file_size

    def execute(self) -> None:
        self.emit("[INIT] Method V4 Direct Forensic Patch Engine")
        if self.target_timescale <= 0:
            raise PatchError("Target timescale must be a positive integer.")

        if self.src.resolve() == self.out.resolve():
            raise PatchError("Refusing to patch in-place: destination path identical to source.")

        # Memory / Size Guard
        file_sz = self.src.stat().st_size
        if self.max_file_size is not None and file_sz > self.max_file_size:
            raise PatchError(
                f"File size ({file_sz:,} bytes) exceeds memory safety limit "
                f"({self.max_file_size:,} bytes). Method V4 reads full file into memory."
            )

        # 1. READ
        self.emit(f"[READ] {self.src.name}")
        raw = self.src.read_bytes()
        data = bytearray(raw)

        # Pre-patch forensic baseline
        orig_analyzer = MP4ForensicAnalyzer(raw, str(self.src))
        orig_report = orig_analyzer.parse()
        if any(node.type_str == "moof" for node in orig_report.atom_tree):
            raise PatchError("Fragmented MP4 (moof) is not supported by Method V4 direct patch.")
        if not orig_report.mdat_found:
            raise PatchError("Source file has no mdat box.")

        v_tracks = [t for t in orig_report.tracks if t.handler_type == "vide"]
        if not v_tracks:
            raise PatchError("No video track found in source file.")
        primary_v_track = v_tracks[0]

        # 2. PARSE MP4 atoms
        self.emit("[PARSE] MP4 atoms")
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
            raise PatchError("Fragmented MP4 (moof) is not supported by Method V4 direct patch.")

        moov = next((b for b in top if b.typ == b"moov"), None)
        if not moov:
            raise PatchError("moov container box not found.")

        # 3. ANALYZE video track & timing metadata
        self.emit("[ANALYZE] video track")
        self.emit(
            f"[ANALYZE] timing metadata: codec={primary_v_track.codec}, "
            f"current_timescale={primary_v_track.timescale}, "
            f"target_timescale={self.target_timescale}"
        )

        old_timescale = primary_v_track.timescale
        if old_timescale <= 0:
            raise PatchError("Invalid source timescale.")
        scale = Fraction(self.target_timescale, old_timescale)

        # Locate video trak
        video_trak: Box | None = None
        mdia: Box | None = None
        for trak in _find_children(data, moov, b"trak"):
            try:
                trak_mdia = _single_child(data, trak, b"mdia")
                hdlr = _single_child(data, trak_mdia, b"hdlr")
                if _handler_type(data, hdlr) == b"vide":
                    video_trak = trak
                    mdia = trak_mdia
                    break
            except PatchError:
                continue

        if video_trak is None or mdia is None:
            raise PatchError("Failed to resolve primary video trak atom.")

        # Check cancellation
        if self.cancel_event and self.cancel_event.is_set():
            raise PatchCancelledError("Patch cancelled by user.")

        # 4. PATCH mdhd.timescale & duration
        self.emit("[PATCH] mdhd.timescale")
        mdhd = _single_child(data, mdia, b"mdhd")
        _patch_mdhd(data, mdhd, scale, self.target_timescale)

        # 5. PATCH mvhd.timescale (if enabled)
        mvhd_scale: Fraction | None = None
        if self.sync_mvhd:
            self.emit("[PATCH] mvhd.timescale")
            mvhd = _single_child(data, moov, b"mvhd")
            mvhd_scale = self._patch_mvhd(data, mvhd)
            for trak in _find_children(data, moov, b"trak"):
                tkhd = _single_child(data, trak, b"tkhd")
                self._patch_tkhd_duration(data, tkhd, mvhd_scale)
                if trak != video_trak:
                    for edts in _find_children(data, trak, b"edts"):
                        for elst in _find_children(data, edts, b"elst"):
                            _patch_elst(data, elst, Fraction(1, 1), movie_scale=mvhd_scale)

        # 6. PATCH timing tables (stts, ctts, elst)
        self.emit("[PATCH] timing tables")
        edts_list = _find_children(data, video_trak, b"edts")
        for edts in edts_list:
            for elst in _find_children(data, edts, b"elst"):
                _patch_elst(data, elst, scale, movie_scale=mvhd_scale)

        minf = _single_child(data, mdia, b"minf")
        stbl = _single_child(data, minf, b"stbl")
        for stts in _find_children(data, stbl, b"stts"):
            _patch_stts(data, stts, scale)
        for ctts in _find_children(data, stbl, b"ctts"):
            _patch_ctts(data, ctts, scale)

        if self.cancel_event and self.cancel_event.is_set():
            raise PatchCancelledError("Patch cancelled by user.")

        # 7. WRITE TO DESTINATION (or memory simulation in dry run)
        tmp_out = self.out.with_suffix(f"{self.out.suffix}.tmp_v4")
        if self.dry_run:
            self.emit("[DRY RUN] Simulation mode active; output file write skipped.")
            patched_bytes = bytes(data)
        else:
            tmp_out.write_bytes(data)
            patched_bytes = bytes(data)

        # 8. VERIFY post-patch integrity
        self.emit("[VERIFY] mdat hash")
        patched_analyzer = MP4ForensicAnalyzer(patched_bytes, str(self.out))
        patched_report = patched_analyzer.parse()

        if (
            self.strict_lossless
            and orig_report.mdat_payload_sha256 != patched_report.mdat_payload_sha256
        ):
            if not self.dry_run:
                tmp_out.unlink(missing_ok=True)
            raise VerifyError(
                "CRITICAL: mdat payload hash mismatch; video bytes were modified."
            )

        orig_v = next((t for t in orig_report.tracks if t.handler_type == "vide"), None)
        patch_v = next((t for t in patched_report.tracks if t.handler_type == "vide"), None)
        if self.preserve_video or self.strict_lossless:
            self.emit("[VERIFY] video payload")
            if (
                orig_v
                and patch_v
                and orig_v.sample_payload_sha256
                and patch_v.sample_payload_sha256
                and orig_v.sample_payload_sha256 != patch_v.sample_payload_sha256
            ):
                if not self.dry_run:
                    tmp_out.unlink(missing_ok=True)
                raise VerifyError("CRITICAL: Video sample payload hash mismatch.")

        orig_a = next((t for t in orig_report.tracks if t.handler_type == "soun"), None)
        patch_a = next((t for t in patched_report.tracks if t.handler_type == "soun"), None)
        if self.preserve_audio or self.strict_lossless:
            self.emit("[VERIFY] audio payload")
            if (
                orig_a
                and patch_a
                and orig_a.sample_payload_sha256
                and patch_a.sample_payload_sha256
                and orig_a.sample_payload_sha256 != patch_a.sample_payload_sha256
            ):
                if not self.dry_run:
                    tmp_out.unlink(missing_ok=True)
                raise VerifyError("CRITICAL: Audio sample payload hash mismatch.")

        self.emit("[VERIFY] MP4 structure")
        # Validate timescale applied
        if patch_v and patch_v.timescale != self.target_timescale:
            if not self.dry_run:
                tmp_out.unlink(missing_ok=True)
            raise VerifyError(
                f"Verification failed: expected timescale {self.target_timescale}, "
                f"got {patch_v.timescale}"
            )

        if not self.dry_run:
            tmp_out.replace(self.out)

        if self.export_report and not self.dry_run:
            from .forensic_analyzer import compare_mp4_files, export_diff_artifacts

            diff_res = compare_mp4_files(self.src, self.out)
            report_dir = self.out.parent / f"{self.out.stem}_forensic_report"
            export_diff_artifacts(diff_res, report_dir)
            self.emit(f"[REPORT] Forensic artifacts exported to {report_dir.name}")

        self.emit("[SUCCESS] lossless patch complete")

    def _patch_mvhd(self, data: bytearray, mvhd: Box) -> Fraction:
        off = mvhd.payload_start
        version = data[off]
        if version == 0:
            if mvhd.size < mvhd.header_size + 24:
                return Fraction(1, 1)
            ts_off = off + 12
            dur_off = off + 16
            old_ts = struct.unpack_from(">I", data, ts_off)[0]
            if old_ts <= 0:
                return Fraction(1, 1)
            mvhd_scale = Fraction(self.target_timescale, old_ts)
            old_dur = struct.unpack_from(">I", data, dur_off)[0]
            new_dur = _scale_int(old_dur, mvhd_scale, signed=False, bits=32)
            struct.pack_into(">I", data, ts_off, self.target_timescale)
            struct.pack_into(">I", data, dur_off, new_dur)
            return mvhd_scale
        elif version == 1:
            if mvhd.size < mvhd.header_size + 36:
                return Fraction(1, 1)
            ts_off = off + 20
            dur_off = off + 24
            old_ts = struct.unpack_from(">I", data, ts_off)[0]
            if old_ts <= 0:
                return Fraction(1, 1)
            mvhd_scale = Fraction(self.target_timescale, old_ts)
            old_dur = struct.unpack_from(">Q", data, dur_off)[0]
            new_dur = _scale_int(old_dur, mvhd_scale, signed=False, bits=64)
            struct.pack_into(">I", data, ts_off, self.target_timescale)
            struct.pack_into(">Q", data, dur_off, new_dur)
            return mvhd_scale
        return Fraction(1, 1)

    def _patch_tkhd_duration(self, data: bytearray, tkhd: Box, scale: Fraction) -> None:
        off = tkhd.payload_start
        version = data[off]
        if version == 0:
            if tkhd.size < tkhd.header_size + 24:
                return
            dur_off = off + 20
            old_dur = struct.unpack_from(">I", data, dur_off)[0]
            new_dur = _scale_int(old_dur, scale, signed=False, bits=32)
            struct.pack_into(">I", data, dur_off, new_dur)
        elif version == 1:
            if tkhd.size < tkhd.header_size + 36:
                return
            dur_off = off + 28
            old_dur = struct.unpack_from(">Q", data, dur_off)[0]
            new_dur = _scale_int(old_dur, scale, signed=False, bits=64)
            struct.pack_into(">Q", data, dur_off, new_dur)
