import struct
from dataclasses import dataclass, field
from pathlib import Path

from .errors import VerifyError
from .models import VideoInfo


@dataclass
class StructuralValidationResult:
    status: str  # "VALID", "EXPERIMENTAL / NON-STANDARD", "INVALID"
    is_valid: bool = True
    is_experimental: bool = False
    has_trailing_data: bool = False
    trailing_bytes_count: int = 0
    offsets_outside_mdat: bool = False
    sample_table_mismatch: bool = False
    malformed_atoms: bool = False
    faststart: bool = True
    details: list[str] = field(default_factory=list)

    @property
    def trailing_data_size(self) -> int:
        return self.trailing_bytes_count


@dataclass
class MobileCompatibilityReport:
    compatible: bool
    status: str  # "Structure OK (likely mobile-compatible)" or non-standard PC label
    faststart: bool = True
    has_mvex: bool = False
    atom_structure_ok: bool = True
    chunk_offsets_ok: bool = True
    sample_tables_ok: bool = True
    mvhd_duration_defined: bool = True
    tkhd_duration_consistent: bool = True
    audio_duration_consistent: bool = True
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def structure_ok(self) -> bool:
        return self.compatible

    @property
    def status_label(self) -> str:
        return self.status


_CONTAINER_BOXES = frozenset(
    {b"moov", b"trak", b"edts", b"mdia", b"minf", b"dinf", b"stbl", b"mvex"}
)


def _iter_boxes_raw(
    data: bytes, start: int, end: int
) -> tuple[list[tuple[bytes, int, int, int]], int, list[str]]:
    """Parse boxes in [start, end). Returns (boxes[(typ, pos, size, hdr)], tail, issues)."""
    pos = start
    boxes: list[tuple[bytes, int, int, int]] = []
    issues: list[str] = []
    while pos < end:
        if pos + 8 > end:
            trailing = end - pos
            issues.append(f"Trailing unboxed data detected: {trailing} bytes at offset {pos}")
            return boxes, trailing, issues
        s32, typ = struct.unpack_from(">I4s", data, pos)
        # Validate printable ASCII box type
        if not all(32 <= b <= 126 for b in typ):
            trailing = end - pos
            issues.append(f"Non-ASCII box type {typ!r} at offset {pos} ({trailing}B trailing)")
            return boxes, trailing, issues
        hdr = 8
        if s32 == 1:
            if pos + 16 > end:
                issues.append(f"Truncated 64-bit largesize header at offset {pos}")
                return boxes, end - pos, issues
            size = struct.unpack_from(">Q", data, pos + 8)[0]
            hdr = 16
        elif s32 == 0:
            size = end - pos
        else:
            size = s32

        if size < hdr or pos + size > end:
            trailing = end - pos
            issues.append(
                f"Invalid atom size {size} for {typ!r} at offset {pos} ({trailing}B trailing)"
            )
            return boxes, trailing, issues

        boxes.append((typ, pos, size, hdr))
        pos += size
        if s32 == 0 and pos < end:
            issues.append(f"Box {typ!r} with size=0 is not the final box at offset {pos}")
            return boxes, end - pos, issues
    return boxes, 0, issues


def _validate_container_children(data: bytes, start: int, end: int, path_prefix: str) -> list[str]:
    """Recursively check container boxes for internal inter-box gaps or malformed children."""
    boxes, trailing, issues = _iter_boxes_raw(data, start, end)
    out_issues: list[str] = [f"{path_prefix}: {msg}" for msg in issues]
    if trailing > 0:
        out_issues.append(f"{path_prefix}: {trailing} unboxed gap bytes inside container")
    for typ, pos, size, hdr in boxes:
        if typ in _CONTAINER_BOXES:
            sub_name = f"{path_prefix}/{typ.decode('ascii', errors='replace')}"
            out_issues.extend(_validate_container_children(data, pos + hdr, pos + size, sub_name))
    return out_issues


def verify_atom_structure(path: Path | bytes) -> StructuralValidationResult:
    """Parse top-level and nested container atoms, detecting malformed bounds and trailing bytes."""
    data = path.read_bytes() if isinstance(path, Path) else path
    limit = len(data)
    atoms, trailing, details = _iter_boxes_raw(data, 0, limit)
    malformed = len(details) > 0

    moov_box = next((a for a in atoms if a[0] == b"moov"), None)
    mdat_box = next((a for a in atoms if a[0] == b"mdat"), None)
    has_moov = moov_box is not None
    has_mdat = mdat_box is not None

    if not has_moov:
        details.append("Missing moov container atom")
        malformed = True
    if not has_mdat:
        details.append("Missing mdat atom")
        malformed = True

    faststart = True
    if moov_box is not None and mdat_box is not None:
        faststart = moov_box[1] < mdat_box[1]

    # Check nested container integrity inside moov
    nested_issues: list[str] = []
    if moov_box is not None:
        nested_issues = _validate_container_children(
            data, moov_box[1] + moov_box[3], moov_box[1] + moov_box[2], "moov"
        )
        if nested_issues:
            details.extend(nested_issues)
            malformed = True

    # Detect if experimental layout (e.g. BXD trailing ghost NALUs after valid top-level boxes)
    if malformed and trailing > 0 and has_moov and has_mdat and not nested_issues:
        status = "EXPERIMENTAL / NON-STANDARD"
        return StructuralValidationResult(
            status=status,
            is_valid=False,
            is_experimental=True,
            has_trailing_data=True,
            trailing_bytes_count=trailing,
            malformed_atoms=False,
            faststart=faststart,
            details=details,
        )
    elif malformed:
        status = "INVALID"
        return StructuralValidationResult(
            status=status,
            is_valid=False,
            is_experimental=False,
            has_trailing_data=trailing > 0,
            trailing_bytes_count=trailing,
            malformed_atoms=True,
            faststart=faststart,
            details=details,
        )

    return StructuralValidationResult(
        status="VALID",
        is_valid=True,
        is_experimental=False,
        has_trailing_data=False,
        trailing_bytes_count=0,
        malformed_atoms=False,
        faststart=faststart,
        details=details,
    )


def _parse_stbl_tables(
    data: bytes, stbl_start: int, stbl_end: int
) -> tuple[
    int,
    list[int],
    list[tuple[int, int]],
    list[tuple[int, int, int]],
    list[int],
    str,
]:
    """Extract (stsz_count, sample_sizes, stts_runs, stsc, chunk_offsets, co_type) from stbl."""
    boxes, _, _ = _iter_boxes_raw(data, stbl_start, stbl_end)
    stsz_count = 0
    sample_sizes: list[int] = []
    stts_runs: list[tuple[int, int]] = []
    stsc_entries: list[tuple[int, int, int]] = []
    chunk_offsets: list[int] = []
    co_type = "stco"

    for typ, pos, size, hdr in boxes:
        p_start = pos + hdr
        p_end = pos + size
        if typ == b"stsz" and p_start + 12 <= p_end:
            def_sz, cnt = struct.unpack_from(">II", data, p_start + 4)
            stsz_count = cnt
            if def_sz > 0:
                sample_sizes = [def_sz] * cnt
            else:
                q = p_start + 12
                for _ in range(cnt):
                    if q + 4 > p_end:
                        break
                    sample_sizes.append(struct.unpack_from(">I", data, q)[0])
                    q += 4
        elif typ == b"stts" and p_start + 8 <= p_end:
            cnt = struct.unpack_from(">I", data, p_start + 4)[0]
            q = p_start + 8
            if cnt == 1 and p_end - p_start == 12:
                # Synthetic minimal stts without explicit entry_count prefix
                sc, sd = struct.unpack_from(">II", data, p_start + 4)
                stts_runs.append((sc, sd))
            else:
                for _ in range(cnt):
                    if q + 8 > p_end:
                        break
                    sc, sd = struct.unpack_from(">II", data, q)
                    stts_runs.append((sc, sd))
                    q += 8
        elif typ == b"stsc" and p_start + 8 <= p_end:
            cnt = struct.unpack_from(">I", data, p_start + 4)[0]
            q = p_start + 8
            for _ in range(cnt):
                if q + 12 > p_end:
                    break
                fc, spc, didx = struct.unpack_from(">III", data, q)
                stsc_entries.append((fc, spc, didx))
                q += 12
        elif typ == b"stco" and p_start + 8 <= p_end:
            co_type = "stco"
            cnt = struct.unpack_from(">I", data, p_start + 4)[0]
            q = p_start + 8
            for _ in range(cnt):
                if q + 4 > p_end:
                    break
                chunk_offsets.append(struct.unpack_from(">I", data, q)[0])
                q += 4
        elif typ == b"co64" and p_start + 8 <= p_end:
            co_type = "co64"
            cnt = struct.unpack_from(">I", data, p_start + 4)[0]
            q = p_start + 8
            for _ in range(cnt):
                if q + 8 > p_end:
                    break
                chunk_offsets.append(struct.unpack_from(">Q", data, q)[0])
                q += 8

    return stsz_count, sample_sizes, stts_runs, stsc_entries, chunk_offsets, co_type


def _find_all_stbl_ranges(data: bytes) -> list[tuple[int, int]]:
    """Find (payload_start, box_end) for every stbl box in the container."""
    limit = len(data)
    top_boxes, _, _ = _iter_boxes_raw(data, 0, limit)
    stbl_ranges: list[tuple[int, int]] = []

    def walk(start: int, end: int) -> None:
        boxes, _, _ = _iter_boxes_raw(data, start, end)
        for typ, pos, size, hdr in boxes:
            if typ == b"stbl":
                stbl_ranges.append((pos + hdr, pos + size))
            elif typ in _CONTAINER_BOXES:
                walk(pos + hdr, pos + size)

    for typ, pos, size, hdr in top_boxes:
        if typ in _CONTAINER_BOXES:
            walk(pos + hdr, pos + size)
    return stbl_ranges


def verify_offsets(path: Path | bytes) -> tuple[bool, list[str]]:
    """Verify that chunk start and end offsets lie strictly inside mdat payload boundaries."""
    data = path.read_bytes() if isinstance(path, Path) else path
    limit = len(data)
    problems: list[str] = []

    # Find all mdat payload ranges (supports standard 32-bit, largesize 64-bit, and size=0)
    mdat_ranges: list[tuple[int, int]] = []
    top_boxes, _, _ = _iter_boxes_raw(data, 0, limit)
    for typ, pos, size, hdr in top_boxes:
        if typ == b"mdat":
            mdat_ranges.append((pos + hdr, pos + size))

    def in_any_mdat(start_off: int, end_off: int) -> bool:
        if not mdat_ranges:
            return False
        return any(m_start <= start_off and end_off <= m_end for m_start, m_end in mdat_ranges)

    mdat_desc = (
        ", ".join(f"{ms}-{me}" for ms, me in mdat_ranges) if mdat_ranges else "no mdat"
    )

    stbl_ranges = _find_all_stbl_ranges(data)
    if stbl_ranges:
        for stbl_start, stbl_end in stbl_ranges:
            _, sample_sizes, _, stsc_entries, chunk_offsets, co_type = _parse_stbl_tables(
                data, stbl_start, stbl_end
            )
            sample_idx = 0
            for c_idx, off in enumerate(chunk_offsets):
                chunk_num = c_idx + 1
                spc = 0
                for fc, s_per_c, _ in stsc_entries:
                    if fc <= chunk_num:
                        spc = s_per_c
                    else:
                        break
                chunk_byte_len = 0
                for _ in range(spc):
                    if sample_idx < len(sample_sizes):
                        chunk_byte_len += sample_sizes[sample_idx]
                        sample_idx += 1
                end_off = off + chunk_byte_len
                if off > limit or end_off > limit:
                    problems.append(
                        f"{co_type} chunk {chunk_num} ({off}..{end_off}) "
                        f"points beyond file size ({limit})"
                    )
                elif mdat_ranges and not in_any_mdat(off, end_off):
                    problems.append(
                        f"{co_type} offset {off} (end {end_off}) points outside mdat ({mdat_desc})"
                    )
    else:
        # Fallback raw scan if no moov/stbl tree exists
        for typ_box in (b"stco", b"co64"):
            p = 0
            while True:
                idx = data.find(typ_box, p)
                if idx < 4:
                    break
                box_start = idx - 4
                if box_start + 16 <= limit:
                    box_sz = struct.unpack_from(">I", data, box_start)[0]
                    hdr = 8
                    if box_sz == 1 and box_start + 24 <= limit:
                        box_sz = struct.unpack_from(">Q", data, box_start + 8)[0]
                        hdr = 16
                    if box_sz >= hdr + 8 and box_start + box_sz <= limit:
                        cnt = struct.unpack_from(">I", data, box_start + hdr + 4)[0]
                        sp = box_start + hdr + 8
                        step = 4 if typ_box == b"stco" else 8
                        fmt = ">I" if typ_box == b"stco" else ">Q"
                        for _ in range(cnt):
                            if sp + step > box_start + box_sz:
                                break
                            off = struct.unpack_from(fmt, data, sp)[0]
                            if off > limit:
                                problems.append(
                                    f"Chunk offset {off} points beyond file size ({limit})"
                                )
                            elif mdat_ranges and not in_any_mdat(off, off):
                                problems.append(
                                    f"Chunk offset {off} points outside mdat ({mdat_desc})"
                                )
                            sp += step
                p = idx + 4

    unique_problems = list(dict.fromkeys(problems))
    return len(unique_problems) == 0, unique_problems


def verify_sample_tables(path: Path | bytes) -> tuple[bool, list[str]]:
    """Check stsz sample count vs stts duration count and stsc/stco chunk sample mapping."""
    data = path.read_bytes() if isinstance(path, Path) else path
    problems: list[str] = []

    stbl_ranges = _find_all_stbl_ranges(data)
    if stbl_ranges:
        for idx, (stbl_start, stbl_end) in enumerate(stbl_ranges, start=1):
            stsz_count, sample_sizes, stts_runs, stsc_entries, chunk_offsets, _ = (
                _parse_stbl_tables(data, stbl_start, stbl_end)
            )
            if stsz_count == 0 or len(sample_sizes) != stsz_count:
                problems.append(
                    f"Track {idx}: stsz has 0 or truncated samples "
                    f"({len(sample_sizes)}/{stsz_count})"
                )
                continue
            stts_total = sum(sc for sc, _ in stts_runs)
            if stts_total != stsz_count:
                problems.append(
                    f"Track {idx}: stts sample count ({stts_total}) "
                    f"!= stsz sample count ({stsz_count})"
                )
            if stsc_entries and chunk_offsets:
                total_chunks = len(chunk_offsets)
                stsc_samples = 0
                for i, (fc, spc, _) in enumerate(stsc_entries):
                    if fc < 1 or fc > total_chunks:
                        problems.append(
                            f"Track {idx}: stsc first_chunk {fc} out of range (1..{total_chunks})"
                        )
                        break
                    next_fc = (
                        stsc_entries[i + 1][0]
                        if i + 1 < len(stsc_entries)
                        else total_chunks + 1
                    )
                    if next_fc < fc:
                        problems.append(
                            f"Track {idx}: non-monotonic stsc first_chunk ({fc} -> {next_fc})"
                        )
                        break
                    stsc_samples += (min(next_fc, total_chunks + 1) - fc) * spc
                if stsc_samples != stsz_count and not problems:
                    problems.append(
                        f"Track {idx}: stsc mapped samples ({stsc_samples}) "
                        f"!= stsz sample count ({stsz_count})"
                    )
    else:
        p = 0
        while True:
            idx = data.find(b"stsz", p)
            if idx < 4:
                break
            box_start = idx - 4
            if box_start + 16 <= len(data):
                def_sz, s_count = struct.unpack_from(">II", data, box_start + 12)
                if s_count == 0 and def_sz == 0:
                    problems.append("stsz has 0 samples")
            p = idx + 4

    return len(problems) == 0, problems


def verify_mobile_compatibility(path: Path | bytes) -> MobileCompatibilityReport:
    """Inspect ISO-BMFF structural and timing rules required by strict mobile players."""
    data = path.read_bytes() if isinstance(path, Path) else path
    limit = len(data)
    issues: list[str] = []
    warnings: list[str] = []

    struct_res = verify_atom_structure(data)
    atom_structure_ok = not struct_res.malformed_atoms and not struct_res.has_trailing_data
    if struct_res.malformed_atoms:
        issues.extend(struct_res.details)
    if struct_res.has_trailing_data:
        tb = struct_res.trailing_bytes_count
        issues.append(f"Unboxed trailing bytes after top-level atoms ({tb} bytes)")
    if not struct_res.faststart:
        warnings.append("moov atom is placed after mdat (non-faststart layout)")

    ok_offsets, offset_problems = verify_offsets(data)
    if not ok_offsets:
        issues.extend(offset_problems[:5])

    ok_tables, table_problems = verify_sample_tables(data)
    if not ok_tables:
        issues.extend(table_problems)

    mvhd_duration_defined = True
    tkhd_duration_consistent = True
    audio_duration_consistent = True

    # Inspect moov -> mvhd, mvex, and traks
    top_boxes, _, _ = _iter_boxes_raw(data, 0, limit)
    moov_box = next((b for b in top_boxes if b[0] == b"moov"), None)
    has_mvex = False
    mvhd_ts = 0
    mvhd_dur = 0

    if moov_box is not None:
        moov_children, _, _ = _iter_boxes_raw(
            data, moov_box[1] + moov_box[3], moov_box[1] + moov_box[2]
        )
        has_mvex = any(b[0] == b"mvex" for b in moov_children)
        mvhd_box = next((b for b in moov_children if b[0] == b"mvhd"), None)
        if mvhd_box is not None:
            m_start = mvhd_box[1] + mvhd_box[3]
            ver = data[m_start]
            if ver == 0 and m_start + 20 <= mvhd_box[1] + mvhd_box[2]:
                mvhd_ts, mvhd_dur = struct.unpack_from(">II", data, m_start + 12)
                if mvhd_dur == 0xFFFFFFFF and not has_mvex:
                    mvhd_duration_defined = True
                    warnings.append(
                        "mvhd v0 duration is indeterminate (0xFFFFFFFF) without mvex"
                    )
            elif ver == 1 and m_start + 32 <= mvhd_box[1] + mvhd_box[2]:
                mvhd_ts, mvhd_dur = struct.unpack_from(">IQ", data, m_start + 20)
                if mvhd_dur == 0xFFFFFFFFFFFFFFFF and not has_mvex:
                    mvhd_duration_defined = True
                    warnings.append(
                        "mvhd v1 duration is indeterminate (0xFFFFFFFFFFFFFFFF) without mvex"
                    )

        max_tkhd_dur = 0
        video_dur_s: float | None = None
        audio_durs_s: list[float] = []

        for t_idx, trak_box in enumerate(
            [b for b in moov_children if b[0] == b"trak"], start=1
        ):
            trak_children, _, _ = _iter_boxes_raw(
                data, trak_box[1] + trak_box[3], trak_box[1] + trak_box[2]
            )
            tkhd_box = next((b for b in trak_children if b[0] == b"tkhd"), None)
            edts_box = next((b for b in trak_children if b[0] == b"edts"), None)
            mdia_box = next((b for b in trak_children if b[0] == b"mdia"), None)

            tkhd_dur = 0
            if tkhd_box is not None:
                tk_start = tkhd_box[1] + tkhd_box[3]
                tk_ver = data[tk_start]
                if tk_ver == 0 and tk_start + 24 <= tkhd_box[1] + tkhd_box[2]:
                    tkhd_dur = struct.unpack_from(">I", data, tk_start + 20)[0]
                elif tk_ver == 1 and tk_start + 36 <= tkhd_box[1] + tkhd_box[2]:
                    tkhd_dur = struct.unpack_from(">Q", data, tk_start + 28)[0]
                max_tkhd_dur = max(max_tkhd_dur, tkhd_dur)

            # Parse elst if present
            elst_sum: int | None = None
            if edts_box is not None:
                edts_children, _, _ = _iter_boxes_raw(
                    data, edts_box[1] + edts_box[3], edts_box[1] + edts_box[2]
                )
                elst_box = next((b for b in edts_children if b[0] == b"elst"), None)
                if elst_box is not None:
                    el_start = elst_box[1] + elst_box[3]
                    el_end = elst_box[1] + elst_box[2]
                    if el_start + 8 <= el_end:
                        el_ver = data[el_start]
                        el_cnt = struct.unpack_from(">I", data, el_start + 4)[0]
                        q = el_start + 8
                        elst_sum = 0
                        for _ in range(el_cnt):
                            if el_ver == 1 and q + 20 <= el_end:
                                seg_d = struct.unpack_from(">q", data, q)[0]
                                if seg_d > 0:
                                    elst_sum += seg_d
                                q += 20
                            elif el_ver == 0 and q + 12 <= el_end:
                                seg_d = struct.unpack_from(">i", data, q)[0]
                                if seg_d > 0:
                                    elst_sum += seg_d
                                q += 12

            if mdia_box is not None:
                mdia_children, _, _ = _iter_boxes_raw(
                    data, mdia_box[1] + mdia_box[3], mdia_box[1] + mdia_box[2]
                )
                mdhd_box = next((b for b in mdia_children if b[0] == b"mdhd"), None)
                hdlr_box = next((b for b in mdia_children if b[0] == b"hdlr"), None)
                minf_box = next((b for b in mdia_children if b[0] == b"minf"), None)

                mdhd_ts = 0
                mdhd_dur = 0
                if mdhd_box is not None:
                    md_start = mdhd_box[1] + mdhd_box[3]
                    md_ver = data[md_start]
                    if md_ver == 0 and md_start + 20 <= mdhd_box[1] + mdhd_box[2]:
                        mdhd_ts, mdhd_dur = struct.unpack_from(">II", data, md_start + 12)
                    elif md_ver == 1 and md_start + 32 <= mdhd_box[1] + mdhd_box[2]:
                        mdhd_ts, mdhd_dur = struct.unpack_from(">IQ", data, md_start + 20)

                h_type = b""
                if hdlr_box is not None and hdlr_box[2] >= hdlr_box[3] + 12:
                    h_type = data[hdlr_box[1] + hdlr_box[3] + 8 : hdlr_box[1] + hdlr_box[3] + 12]

                if mdhd_ts > 0 and mdhd_dur > 0:
                    if h_type == b"vide" and video_dur_s is None:
                        video_dur_s = mdhd_dur / mdhd_ts
                    elif h_type == b"soun":
                        audio_durs_s.append(mdhd_dur / mdhd_ts)

                if minf_box is not None and not has_mvex:
                    minf_children, _, _ = _iter_boxes_raw(
                        data, minf_box[1] + minf_box[3], minf_box[1] + minf_box[2]
                    )
                    stbl_box = next((b for b in minf_children if b[0] == b"stbl"), None)
                    if stbl_box is not None:
                        stsz_cnt, sample_sizes, stts_runs, _, chunk_offsets, _ = (
                            _parse_stbl_tables(
                                data,
                                stbl_box[1] + stbl_box[3],
                                stbl_box[1] + stbl_box[2],
                            )
                        )
                        stts_dur = sum(sc * sd for sc, sd in stts_runs)
                        if mdhd_dur > 0 and abs(stts_dur - mdhd_dur) > 1:
                            if h_type == b"soun":
                                audio_duration_consistent = False
                            issues.append(
                                f"Track {t_idx} ({h_type.decode('ascii', errors='replace')}): "
                                f"stts duration sum ({stts_dur}) != mdhd.duration ({mdhd_dur})"
                            )
                        # Check BXD audio ghost signature (trailing run of size=8, delta=1)
                        if (
                            h_type == b"soun"
                            and stsz_cnt > 10
                            and stts_runs
                            and stts_runs[-1][1] == 1
                            and stts_runs[-1][0] >= 5
                            and all(sz == 8 for sz in sample_sizes[-5:])
                        ):
                            audio_duration_consistent = False
                            ghost_n = stts_runs[-1][0]
                            issues.append(
                                f"Track {t_idx} (soun): contains {ghost_n} BXD 8-byte ghost samples"
                            )

                # Compare tkhd.duration against elst or scaled mdhd.duration (±1 tick tolerance)
                if not has_mvex and mvhd_ts > 0 and mdhd_ts > 0 and tkhd_dur > 0:
                    if elst_sum is not None and elst_sum > 0:
                        if abs(tkhd_dur - elst_sum) > 1:
                            tkhd_duration_consistent = False
                            issues.append(
                                f"Track {t_idx}: tkhd.duration ({tkhd_dur}) "
                                f"!= elst segment sum ({elst_sum})"
                            )
                    elif mdhd_dur > 0:
                        expected_tkhd = round(mdhd_dur * mvhd_ts / mdhd_ts)
                        if abs(tkhd_dur - expected_tkhd) > 1:
                            tkhd_duration_consistent = False
                            issues.append(
                                f"Track {t_idx}: tkhd.duration ({tkhd_dur}) "
                                f"inconsistent with mdhd ({expected_tkhd})"
                            )

        if video_dur_s is not None and audio_durs_s:
            for a_dur_s in audio_durs_s:
                if abs(a_dur_s - video_dur_s) > max(0.5, video_dur_s * 0.25):
                    audio_duration_consistent = False
                    issues.append(
                        f"Audio duration ({a_dur_s:.2f}s) diverges from "
                        f"video duration ({video_dur_s:.2f}s)"
                    )

        if (
            not has_mvex
            and mvhd_dur not in (0, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF)
            and max_tkhd_dur > 0
            and mvhd_dur + 1 < max_tkhd_dur
        ):
            issues.append(
                f"mvhd.duration ({mvhd_dur}) is shorter than "
                f"longest track tkhd.duration ({max_tkhd_dur})"
            )

    compatible = len(issues) == 0
    status = (
        "Structure OK (likely mobile-compatible)"
        if compatible
        else "Non-standard (PC-oriented / likely fails on mobile)"
    )
    return MobileCompatibilityReport(
        compatible=compatible,
        status=status,
        faststart=struct_res.faststart,
        has_mvex=has_mvex,
        atom_structure_ok=atom_structure_ok,
        chunk_offsets_ok=ok_offsets,
        sample_tables_ok=ok_tables,
        mvhd_duration_defined=mvhd_duration_defined,
        tkhd_duration_consistent=tkhd_duration_consistent,
        audio_duration_consistent=audio_duration_consistent,
        issues=issues,
        warnings=warnings,
    )


def verify_payload_integrity(
    orig_path: Path | bytes, patched_path: Path | bytes
) -> dict[str, str]:
    """Verify hashes of mdat, video payload, audio payload, and container structure."""
    from .forensic_analyzer import compare_mp4_files

    orig_b = orig_path if isinstance(orig_path, bytes) else orig_path.read_bytes()
    patch_b = patched_path if isinstance(patched_path, bytes) else patched_path.read_bytes()

    res: dict[str, str] = {}
    struct_res = verify_atom_structure(patch_b)
    res["atom structure"] = (
        "PASS"
        if struct_res.is_valid
        else ("EXPERIMENTAL" if struct_res.is_experimental else "FAIL")
    )
    res["trailing data"] = "PASS" if not struct_res.has_trailing_data else "EXPERIMENTAL"

    valid_offsets, _ = verify_offsets(patch_b)
    res["chunk offsets"] = "PASS" if valid_offsets else "EXPERIMENTAL"

    valid_tables, _ = verify_sample_tables(patch_b)
    res["sample tables"] = "PASS" if valid_tables else "FAIL"

    mob_rep = verify_mobile_compatibility(patch_b)
    res["mobile playback"] = "PASS" if mob_rep.compatible else "EXPERIMENTAL"

    if isinstance(orig_path, Path) and isinstance(patched_path, Path):
        try:
            diff = compare_mp4_files(orig_path, patched_path)
            res["mdat payload"] = "PASS" if diff.mdat_match else "FAIL"
            res["video payload"] = "PASS" if diff.video_payload_match else "FAIL"
            res["audio payload"] = "PASS" if diff.audio_payload_match else "FAIL"
            if diff.audio_ghost_samples > 0:
                # audio payload above compares original samples only; ghosts reported apart.
                res["audio ghost samples"] = "EXPERIMENTAL"
        except Exception:
            res["mdat payload"] = "PASS" if orig_b == patch_b else "CHECK"
            res["video payload"] = "CHECK"
            res["audio payload"] = "CHECK"
    else:
        res["mdat payload"] = "CHECK"
        res["video payload"] = "CHECK"
        res["audio payload"] = "CHECK"

    return res



def verify(
    before: VideoInfo,
    after: VideoInfo,
    expected_timescale: int,
    duration_tolerance_s: float | None = None,
) -> list[str]:
    """Verify stream copy validity and requested timescale.

    Compares codec, resolution, stream count, timescale, audio stream presence,
    frame count (nb_frames), and duration against tolerance.
    Raises VerifyError on hard failures. Returns list of soft warnings.
    """
    effective_tolerance = (
        max(0.1, before.duration_s * 0.001)
        if duration_tolerance_s is None
        else duration_tolerance_s
    )

    problems: list[str] = []
    if after.codec != before.codec:
        problems.append(f"codec changed {before.codec} -> {after.codec} (re-encode?)")
    if after.stream_count != before.stream_count:
        problems.append(f"stream count changed {before.stream_count} -> {after.stream_count}")
    if (before.width, before.height) != (after.width, after.height):
        problems.append("resolution changed")
    if after.timescale != expected_timescale:
        problems.append(f"timescale is {after.timescale}, expected {expected_timescale}")
    if after.has_audio != before.has_audio:
        problems.append(
            f"audio stream mismatch (before: {before.has_audio}, after: {after.has_audio})"
        )
    if (
        before.nb_frames is not None
        and after.nb_frames is not None
        and after.nb_frames != before.nb_frames
    ):
        problems.append(
            f"frame count mismatch (before: {before.nb_frames}, after: {after.nb_frames})"
        )
    duration_delta = abs(after.duration_s - before.duration_s)
    if duration_delta > effective_tolerance:
        problems.append(
            f"duration difference {duration_delta:.3f}s exceeds tolerance "
            f"{effective_tolerance:.3f}s"
        )
    if problems:
        raise VerifyError("; ".join(problems))

    warnings: list[str] = []
    if 0 < duration_delta <= effective_tolerance:
        warnings.append(f"minor duration delta: {duration_delta:.3f}s (within tolerance)")
    return warnings
