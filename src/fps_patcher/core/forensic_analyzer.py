"""MP4/MOV Forensic Analyzer & Binary/Semantic Differ.

Parses hierarchical atom structures (32-bit & 64-bit sizes, containers, FullBoxes,
uuid, leaf atoms), computes payload hashes (mdat, video/audio samples), and performs
byte-level and semantic field diffs.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import FPSPatcherError

CONTAINER_TYPES: frozenset[bytes] = frozenset(
    {
        b"moov",
        b"trak",
        b"edts",
        b"mdia",
        b"minf",
        b"dinf",
        b"stbl",
        b"mvex",
        b"moof",
        b"traf",
        b"mfra",
        b"udta",
        b"meta",
        b"sinf",
        b"schi",
    }
)

FULL_BOX_TYPES: frozenset[bytes] = frozenset(
    {
        b"mvhd",
        b"tkhd",
        b"mdhd",
        b"hdlr",
        b"elst",
        b"stts",
        b"ctts",
        b"cslg",
        b"stss",
        b"stsd",
        b"stsz",
        b"stz2",
        b"stsc",
        b"stco",
        b"co64",
        b"mehd",
        b"trex",
        b"mfhd",
        b"tfhd",
        b"trun",
        b"tfdt",
        b"meta",
        b"smhd",
        b"vmhd",
    }
)


class ForensicParseError(FPSPatcherError):
    """Raised when atom parsing encounters malformed box headers or layouts."""


@dataclass
class AtomNode:
    type_str: str
    start: int
    size: int
    header_size: int
    uuid_hex: str | None = None
    version: int | None = None
    flags: int | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    children: list[AtomNode] = field(default_factory=list)
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class TrackAnalysis:
    track_id: int
    handler_type: str  # "vide", "soun", etc.
    codec: str
    timescale: int
    duration_track: int
    duration_movie: int
    width: float
    height: float
    sample_count: int
    sample_payload_sha256: str
    stts_entries: list[tuple[int, int]]
    ctts_entries: list[tuple[int, int]]
    elst_entries: list[dict[str, Any]]

    @property
    def has_edts(self) -> bool:
        return len(self.elst_entries) > 0

    @property
    def duration_movie_ts(self) -> int:
        return self.duration_movie


@dataclass
class MP4ForensicReport:
    file_path: str
    file_size: int
    file_sha256: str
    atom_tree: list[AtomNode]
    mdat_found: bool
    mdat_offset: int
    mdat_size: int
    mdat_payload_sha256: str
    moov_sha256: str
    tracks: list[TrackAnalysis]
    summary_fields: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def trailing_data_size(self) -> int:
        for node in self.atom_tree:
            if node.type_str == "[trailing_data]":
                return node.size
        return 0


@dataclass
class ByteDiffSpan:
    offset: int
    length: int
    atom_path: str
    old_bytes_hex: str
    new_bytes_hex: str
    field_hint: str | None = None


@dataclass
class SemanticDiffEntry:
    target: str
    field: str
    old_value: Any
    new_value: Any
    interpretation: str


@dataclass
class ForensicDiffResult:
    original_path: str
    patched_path: str
    file_size_changed: bool
    size_difference: int
    mdat_changed: bool
    video_payload_changed: bool
    audio_payload_changed: bool
    moov_changed: bool
    changed_atoms: list[str]
    byte_diffs: list[ByteDiffSpan]
    semantic_diffs: list[SemanticDiffEntry]
    bxd_classification: dict[str, list[str]]
    hypothesis: list[str]
    before: MP4ForensicReport | None = None
    after: MP4ForensicReport | None = None
    # Extra audio samples appended by BXD (patched count - original count); 0 if none.
    audio_ghost_samples: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["mdatChanged"] = self.mdat_changed
        d["videoPayloadChanged"] = self.video_payload_changed
        d["audioPayloadChanged"] = self.audio_payload_changed
        d["changedAtoms"] = self.changed_atoms
        return d

    @property
    def mdat_match(self) -> bool:
        return not self.mdat_changed

    @property
    def video_payload_match(self) -> bool:
        return not self.video_payload_changed

    @property
    def audio_payload_match(self) -> bool:
        return not self.audio_payload_changed

    @property
    def structure_match(self) -> bool:
        if not self.before or not self.after:
            return False
        return [n.type_str for n in self.before.atom_tree] == [
            n.type_str for n in self.after.atom_tree
        ]


MP4DiffResult = ForensicDiffResult


class MP4ForensicAnalyzer:
    def __init__(self, data: bytes, file_path: str = "") -> None:
        self.data = data
        self.file_path = file_path
        self.limit = len(data)

    def parse(self) -> MP4ForensicReport:
        pos = 0
        tree: list[AtomNode] = []
        mdat_found = False
        mdat_offset = 0
        mdat_size = 0
        mdat_payload_sha256 = ""
        moov_sha256 = ""

        while pos < self.limit:
            if pos + 8 > self.limit:
                if mdat_found or any(n.type_str == "moov" for n in tree):
                    tree.append(
                        AtomNode(
                            type_str="[trailing_data]",
                            start=pos,
                            size=self.limit - pos,
                            header_size=0,
                            sha256=hashlib.sha256(self.data[pos:]).hexdigest(),
                            fields={"length": self.limit - pos},
                        )
                    )
                    break
                raise ForensicParseError(f"Truncated atom header at offset {pos}")

            try:
                node = self._parse_atom(pos, self.limit, path="")
            except ForensicParseError as exc:
                if mdat_found or any(n.type_str == "moov" for n in tree):
                    tree.append(
                        AtomNode(
                            type_str="[trailing_data]",
                            start=pos,
                            size=self.limit - pos,
                            header_size=0,
                            sha256=hashlib.sha256(self.data[pos:]).hexdigest(),
                            fields={"error": str(exc), "length": self.limit - pos},
                        )
                    )
                    break
                raise

            tree.append(node)
            if node.type_str == "mdat":
                mdat_found = True
                mdat_offset = node.start
                mdat_size = node.size
                payload = self.data[node.start + node.header_size : node.start + node.size]
                mdat_payload_sha256 = hashlib.sha256(payload).hexdigest()
            elif node.type_str == "moov":
                moov_bytes = self.data[node.start : node.start + node.size]
                moov_sha256 = hashlib.sha256(moov_bytes).hexdigest()
            pos += node.size

        tracks = self._extract_tracks(tree)
        summary = self._build_summary(tree, tracks)

        return MP4ForensicReport(
            file_path=self.file_path,
            file_size=self.limit,
            file_sha256=hashlib.sha256(self.data).hexdigest(),
            atom_tree=tree,
            mdat_found=mdat_found,
            mdat_offset=mdat_offset,
            mdat_size=mdat_size,
            mdat_payload_sha256=mdat_payload_sha256,
            moov_sha256=moov_sha256,
            tracks=tracks,
            summary_fields=summary,
        )

    def _parse_atom(self, pos: int, limit: int, path: str) -> AtomNode:
        if pos + 8 > limit:
            raise ForensicParseError(f"Truncated atom header at offset {pos}")
        size32, typ_raw = struct.unpack_from(">I4s", self.data, pos)
        typ_str = typ_raw.decode("latin1", errors="replace")
        header_size = 8
        current_path = f"{path}/{typ_str}" if path else typ_str

        if size32 == 1:
            if pos + 16 > limit:
                raise ForensicParseError(f"Truncated large atom header at offset {pos}")
            size = struct.unpack_from(">Q", self.data, pos + 8)[0]
            header_size = 16
        elif size32 == 0:
            size = limit - pos
        else:
            size = size32

        if size < header_size or pos + size > limit:
            raise ForensicParseError(f"Malformed atom size {size} for {typ_str} at offset {pos}")

        atom_bytes = self.data[pos : pos + size]
        atom_hash = hashlib.sha256(atom_bytes).hexdigest()

        uuid_hex = None
        payload_start = pos + header_size
        if typ_raw == b"uuid":
            if payload_start + 16 > pos + size:
                raise ForensicParseError(f"Truncated uuid atom at offset {pos}")
            uuid_bytes = self.data[payload_start : payload_start + 16]
            uuid_hex = uuid_bytes.hex()
            payload_start += 16

        version = None
        flags = None
        if typ_raw in FULL_BOX_TYPES and payload_start + 4 <= pos + size:
            v_flags = struct.unpack_from(">I", self.data, payload_start)[0]
            version = (v_flags >> 24) & 0xFF
            flags = v_flags & 0x00FFFFFF
            payload_start += 4

        fields: dict[str, Any] = {}
        children: list[AtomNode] = []

        if typ_raw in CONTAINER_TYPES:
            cpos = payload_start
            cend = pos + size
            while cpos < cend:
                child = self._parse_atom(cpos, cend, current_path)
                children.append(child)
                cpos += child.size
            if cpos != cend:
                raise ForensicParseError(f"Container child alignment mismatch in {typ_str}")
        else:
            fields = self._parse_leaf_fields(typ_raw, version, payload_start, pos + size)

        return AtomNode(
            type_str=typ_str,
            start=pos,
            size=size,
            header_size=header_size,
            uuid_hex=uuid_hex,
            version=version,
            flags=flags,
            fields=fields,
            children=children,
            sha256=atom_hash,
        )

    def _parse_leaf_fields(
        self, typ_raw: bytes, version: int | None, p_start: int, p_end: int
    ) -> dict[str, Any]:
        data = self.data
        length = p_end - p_start
        fields: dict[str, Any] = {}

        if typ_raw == b"mvhd":
            if version == 1 and length >= 28:
                c_time, m_time, ts, dur = struct.unpack_from(">QQIQ", data, p_start)
                fields.update(
                    {"timescale": ts, "duration": dur, "creation_time": c_time, "mod_time": m_time}
                )
            elif (version == 0 or version is None) and length >= 16:
                c_time, m_time, ts, dur = struct.unpack_from(">IIII", data, p_start)
                fields.update(
                    {"timescale": ts, "duration": dur, "creation_time": c_time, "mod_time": m_time}
                )
        elif typ_raw == b"tkhd":
            if version == 1 and length >= 32:
                _, _, t_id, _, dur = struct.unpack_from(">QQIIQ", data, p_start)
                fields.update({"track_id": t_id, "duration": dur})
            elif (version == 0 or version is None) and length >= 20:
                _, _, t_id, _, dur = struct.unpack_from(">IIIII", data, p_start)
                fields.update({"track_id": t_id, "duration": dur})
            if length >= 80:
                # Width and height at the end of tkhd (fixed point 16.16)
                w_fixed, h_fixed = struct.unpack_from(">II", data, p_end - 8)
                fields["width"] = w_fixed / 65536.0
                fields["height"] = h_fixed / 65536.0
        elif typ_raw == b"mdhd":
            if version == 1 and length >= 28:
                c_time, m_time, ts, dur = struct.unpack_from(">QQIQ", data, p_start)
                fields.update(
                    {"timescale": ts, "duration": dur, "creation_time": c_time, "mod_time": m_time}
                )
            elif (version == 0 or version is None) and length >= 16:
                c_time, m_time, ts, dur = struct.unpack_from(">IIII", data, p_start)
                fields.update(
                    {"timescale": ts, "duration": dur, "creation_time": c_time, "mod_time": m_time}
                )
        elif typ_raw == b"hdlr" and length >= 12:
            _, handler_raw = struct.unpack_from(">4s4s", data, p_start)
            fields["handler_type"] = handler_raw.decode("latin1", errors="replace")
        elif typ_raw == b"stts" and length >= 4:
            count = struct.unpack_from(">I", data, p_start)[0]
            entries: list[tuple[int, int]] = []
            pos = p_start + 4
            for _ in range(count):
                if pos + 8 > p_end:
                    break
                s_count, delta = struct.unpack_from(">II", data, pos)
                entries.append((s_count, delta))
                pos += 8
            fields["entry_count"] = count
            fields["entries"] = entries
            total_samples = sum(s[0] for s in entries)
            fields["total_samples"] = total_samples
        elif typ_raw == b"ctts" and length >= 4:
            count = struct.unpack_from(">I", data, p_start)[0]
            entries = []
            pos = p_start + 4
            for _ in range(count):
                if pos + 8 > p_end:
                    break
                s_count = struct.unpack_from(">I", data, pos)[0]
                offset = struct.unpack_from(">i", data, pos + 4)[0]
                entries.append((s_count, offset))
                pos += 8
            fields["entry_count"] = count
            fields["entries"] = entries
        elif typ_raw == b"elst" and length >= 4:
            count = struct.unpack_from(">I", data, p_start)[0]
            pos = p_start + 4
            elst_list: list[dict[str, Any]] = []
            for _ in range(count):
                if version == 1:
                    if pos + 20 > p_end:
                        break
                    seg_dur, med_time, rate_int, rate_frac = struct.unpack_from(">qqhh", data, pos)
                    pos += 20
                else:
                    if pos + 12 > p_end:
                        break
                    seg_dur, med_time, rate_int, rate_frac = struct.unpack_from(">iihh", data, pos)
                    pos += 12
                elst_list.append(
                    {
                        "segment_duration": seg_dur,
                        "media_time": med_time,
                        "media_rate": rate_int + rate_frac / 65536.0,
                    }
                )
            fields["entry_count"] = count
            fields["entries"] = elst_list
        elif typ_raw == b"stsz" and length >= 8:
            sample_size, sample_count = struct.unpack_from(">II", data, p_start)
            fields["sample_size"] = sample_size
            fields["sample_count"] = sample_count
            sizes: list[int] = []
            if sample_size == 0 and length >= 8 + sample_count * 4:
                pos = p_start + 8
                for _ in range(min(sample_count, 100000)):
                    sizes.append(struct.unpack_from(">I", data, pos)[0])
                    pos += 4
            fields["sample_sizes_head"] = sizes[:10]
        elif typ_raw == b"stco" and length >= 4:
            count = struct.unpack_from(">I", data, p_start)[0]
            fields["chunk_count"] = count
            offsets: list[int] = []
            pos = p_start + 4
            for _ in range(min(count, 5)):
                offsets.append(struct.unpack_from(">I", data, pos)[0])
                pos += 4
            fields["first_chunk_offsets"] = offsets
        elif typ_raw == b"co64" and length >= 4:
            count = struct.unpack_from(">I", data, p_start)[0]
            fields["chunk_count"] = count
            offsets = []
            pos = p_start + 4
            for _ in range(min(count, 5)):
                offsets.append(struct.unpack_from(">Q", data, pos)[0])
                pos += 8
            fields["first_chunk_offsets"] = offsets
        elif typ_raw == b"stsc" and length >= 4:
            count = struct.unpack_from(">I", data, p_start)[0]
            fields["entry_count"] = count

        return fields

    def _extract_tracks(self, tree: list[AtomNode]) -> list[TrackAnalysis]:
        moov = next((n for n in tree if n.type_str == "moov"), None)
        if not moov:
            return []

        tracks: list[TrackAnalysis] = []
        for trak in [n for n in moov.children if n.type_str == "trak"]:
            tkhd = next((n for n in trak.children if n.type_str == "tkhd"), None)
            track_id = int(tkhd.fields.get("track_id", 0)) if tkhd else 0
            dur_movie = int(tkhd.fields.get("duration", 0)) if tkhd else 0
            w = float(tkhd.fields.get("width", 0)) if tkhd else 0.0
            h = float(tkhd.fields.get("height", 0)) if tkhd else 0.0

            mdia = next((n for n in trak.children if n.type_str == "mdia"), None)
            hdlr_type = "unknown"
            ts = 0
            dur_track = 0
            codec = "unknown"
            sample_count = 0
            stts_entries: list[tuple[int, int]] = []
            ctts_entries: list[tuple[int, int]] = []
            elst_entries: list[dict[str, Any]] = []

            edts = next((n for n in trak.children if n.type_str == "edts"), None)
            if edts:
                elst = next((n for n in edts.children if n.type_str == "elst"), None)
                if elst:
                    elst_entries = elst.fields.get("entries", [])

            if mdia:
                hdlr = next((n for n in mdia.children if n.type_str == "hdlr"), None)
                if hdlr:
                    hdlr_type = str(hdlr.fields.get("handler_type", "unknown")).strip()
                mdhd = next((n for n in mdia.children if n.type_str == "mdhd"), None)
                if mdhd:
                    ts = int(mdhd.fields.get("timescale", 0))
                    dur_track = int(mdhd.fields.get("duration", 0))

                minf = next((n for n in mdia.children if n.type_str == "minf"), None)
                if minf:
                    stbl = next((n for n in minf.children if n.type_str == "stbl"), None)
                    if stbl:
                        stsd = next((n for n in stbl.children if n.type_str == "stsd"), None)
                        if stsd and stsd.children:
                            codec = stsd.children[0].type_str
                        stsz = next((n for n in stbl.children if n.type_str == "stsz"), None)
                        if stsz:
                            sample_count = int(stsz.fields.get("sample_count", 0))
                        stts = next((n for n in stbl.children if n.type_str == "stts"), None)
                        if stts:
                            stts_entries = stts.fields.get("entries", [])
                        ctts = next((n for n in stbl.children if n.type_str == "ctts"), None)
                        if ctts:
                            ctts_entries = ctts.fields.get("entries", [])

            # Compute sample payload hash for this track
            payload_hash = self._hash_track_payload(trak)

            tracks.append(
                TrackAnalysis(
                    track_id=track_id,
                    handler_type=hdlr_type,
                    codec=codec,
                    timescale=ts,
                    duration_track=dur_track,
                    duration_movie=dur_movie,
                    width=w,
                    height=h,
                    sample_count=sample_count,
                    sample_payload_sha256=payload_hash,
                    stts_entries=stts_entries,
                    ctts_entries=ctts_entries,
                    elst_entries=elst_entries,
                )
            )

        return tracks

    def hash_track_prefix(self, tree: list[AtomNode], track_id: int, max_samples: int) -> str:
        """Hash only the first ``max_samples`` samples of a track (ghost-tail excluded)."""
        moov = next((n for n in tree if n.type_str == "moov"), None)
        if not moov:
            return ""
        for trak in [n for n in moov.children if n.type_str == "trak"]:
            tkhd = next((n for n in trak.children if n.type_str == "tkhd"), None)
            if tkhd and int(tkhd.fields.get("track_id", 0)) == track_id:
                return self._hash_track_payload(trak, max_samples)
        return ""

    def hash_real_mdat_samples(self, tree: list[AtomNode]) -> dict[int, tuple[int, str]]:
        """Return {track_id: (real_sample_count, sha256_hex)} for samples strictly inside mdat."""
        moov = next((n for n in tree if n.type_str == "moov"), None)
        mdat = next((n for n in tree if n.type_str == "mdat"), None)
        if not moov or not mdat:
            return {}
        mdat_start = mdat.start + mdat.header_size
        mdat_end = mdat.start + mdat.size
        out: dict[int, tuple[int, str]] = {}
        for trak in [n for n in moov.children if n.type_str == "trak"]:
            tkhd = next((n for n in trak.children if n.type_str == "tkhd"), None)
            track_id = int(tkhd.fields.get("track_id", 0)) if tkhd else 0
            if track_id <= 0:
                continue
            mdia = next((n for n in trak.children if n.type_str == "mdia"), None)
            minf = next((n for n in mdia.children if n.type_str == "minf"), None) if mdia else None
            stbl = next((n for n in minf.children if n.type_str == "stbl"), None) if minf else None
            if not stbl:
                continue
            stsz = next((n for n in stbl.children if n.type_str == "stsz"), None)
            stco = next((n for n in stbl.children if n.type_str == "stco"), None)
            co64 = next((n for n in stbl.children if n.type_str == "co64"), None)
            stsc = next((n for n in stbl.children if n.type_str == "stsc"), None)
            if not stsz or (not stco and not co64) or not stsc:
                continue
            try:
                chunk_offsets: list[int] = []
                if stco:
                    c_start = stco.start + stco.header_size + (4 if stco.version is not None else 0)
                    count = struct.unpack_from(">I", self.data, c_start)[0]
                    for i in range(count):
                        off32 = struct.unpack_from(">I", self.data, c_start + 4 + i * 4)[0]
                        chunk_offsets.append(off32)
                elif co64:
                    c_start = co64.start + co64.header_size + (4 if co64.version is not None else 0)
                    count = struct.unpack_from(">I", self.data, c_start)[0]
                    for i in range(count):
                        off64 = struct.unpack_from(">Q", self.data, c_start + 4 + i * 8)[0]
                        chunk_offsets.append(off64)

                sample_sizes: list[int] = []
                s_start = stsz.start + stsz.header_size + (4 if stsz.version is not None else 0)
                def_size, s_count = struct.unpack_from(">II", self.data, s_start)
                if def_size > 0:
                    sample_sizes = [def_size] * s_count
                else:
                    for i in range(s_count):
                        sz = struct.unpack_from(">I", self.data, s_start + 8 + i * 4)[0]
                        sample_sizes.append(sz)

                sc_start = stsc.start + stsc.header_size + (4 if stsc.version is not None else 0)
                sc_count = struct.unpack_from(">I", self.data, sc_start)[0]
                stsc_table: list[tuple[int, int, int]] = []
                for i in range(sc_count):
                    stsc_table.append(struct.unpack_from(">III", self.data, sc_start + 4 + i * 12))

                hasher = hashlib.sha256()
                sample_idx = 0
                real_count = 0
                for c_idx, c_offset in enumerate(chunk_offsets):
                    if sample_idx >= len(sample_sizes):
                        break
                    chunk_num = c_idx + 1
                    s_per_c = 0
                    for f_c, spc, _ in stsc_table:
                        if f_c <= chunk_num:
                            s_per_c = spc
                        else:
                            break
                    if not (mdat_start <= c_offset < mdat_end):
                        sample_idx += s_per_c
                        continue
                    cur_off = c_offset
                    for _ in range(s_per_c):
                        if sample_idx >= len(sample_sizes):
                            break
                        sz = sample_sizes[sample_idx]
                        if mdat_start <= cur_off and cur_off + sz <= mdat_end:
                            hasher.update(self.data[cur_off : cur_off + sz])
                            real_count += 1
                        cur_off += sz
                        sample_idx += 1
                out[track_id] = (real_count, hasher.hexdigest())
            except Exception:
                continue
        return out

    def _hash_track_payload(self, trak: AtomNode, max_samples: int | None = None) -> str:
        """Extract all sample byte slices pointed to by chunk offsets & sample sizes.

        If ``max_samples`` is given, stop after that many samples in table order.
        """
        mdia = next((n for n in trak.children if n.type_str == "mdia"), None)
        if not mdia:
            return ""
        minf = next((n for n in mdia.children if n.type_str == "minf"), None)
        if not minf:
            return ""
        stbl = next((n for n in minf.children if n.type_str == "stbl"), None)
        if not stbl:
            return ""

        stsz = next((n for n in stbl.children if n.type_str == "stsz"), None)
        stco = next((n for n in stbl.children if n.type_str == "stco"), None)
        co64 = next((n for n in stbl.children if n.type_str == "co64"), None)
        stsc = next((n for n in stbl.children if n.type_str == "stsc"), None)

        if not stsz or (not stco and not co64) or not stsc:
            return ""

        try:
            # Parse full chunk offsets
            chunk_offsets: list[int] = []
            if stco:
                c_start = stco.start + stco.header_size + (4 if stco.version is not None else 0)
                count = struct.unpack_from(">I", self.data, c_start)[0]
                pos = c_start + 4
                for _ in range(count):
                    chunk_offsets.append(struct.unpack_from(">I", self.data, pos)[0])
                    pos += 4
            elif co64:
                c_start = co64.start + co64.header_size + (4 if co64.version is not None else 0)
                count = struct.unpack_from(">I", self.data, c_start)[0]
                pos = c_start + 4
                for _ in range(count):
                    chunk_offsets.append(struct.unpack_from(">Q", self.data, pos)[0])
                    pos += 8

            # Parse full sample sizes
            sample_sizes: list[int] = []
            s_start = stsz.start + stsz.header_size + (4 if stsz.version is not None else 0)
            def_size, s_count = struct.unpack_from(">II", self.data, s_start)
            if def_size > 0:
                sample_sizes = [def_size] * s_count
            else:
                pos = s_start + 8
                for _ in range(s_count):
                    sample_sizes.append(struct.unpack_from(">I", self.data, pos)[0])
                    pos += 4

            # Parse stsc entries (first_chunk, samples_per_chunk, sample_description_index)
            sc_start = stsc.start + stsc.header_size + (4 if stsc.version is not None else 0)
            sc_count = struct.unpack_from(">I", self.data, sc_start)[0]
            stsc_table: list[tuple[int, int, int]] = []
            pos = sc_start + 4
            for _ in range(sc_count):
                f_chunk, s_per_c, desc_idx = struct.unpack_from(">III", self.data, pos)
                stsc_table.append((f_chunk, s_per_c, desc_idx))
                pos += 12

            hasher = hashlib.sha256()
            sample_idx = 0
            num_chunks = len(chunk_offsets)
            cap = len(sample_sizes) if max_samples is None else min(max_samples, len(sample_sizes))

            for c_idx in range(num_chunks):
                if sample_idx >= cap:
                    break
                chunk_num = c_idx + 1
                # Find matching stsc entry
                s_per_c = 0
                for f_c, spc, _ in stsc_table:
                    if f_c <= chunk_num:
                        s_per_c = spc
                    else:
                        break

                c_offset = chunk_offsets[c_idx]
                for _ in range(s_per_c):
                    if sample_idx >= cap:
                        break
                    sz = sample_sizes[sample_idx]
                    if c_offset + sz <= self.limit:
                        hasher.update(self.data[c_offset : c_offset + sz])
                    c_offset += sz
                    sample_idx += 1

            return hasher.hexdigest()
        except Exception:
            return ""

    def _build_summary(
        self, tree: list[AtomNode], tracks: list[TrackAnalysis]
    ) -> dict[str, Any]:
        moov = next((n for n in tree if n.type_str == "moov"), None)
        mvhd = next((n for n in moov.children if n.type_str == "mvhd"), None) if moov else None
        v_track = next((t for t in tracks if t.handler_type == "vide"), None)
        a_track = next((t for t in tracks if t.handler_type == "soun"), None)

        fps = 0.0
        if v_track and v_track.stts_entries and v_track.timescale > 0:
            first_delta = v_track.stts_entries[0][1]
            if first_delta > 0:
                fps = v_track.timescale / first_delta

        return {
            "movie_timescale": mvhd.fields.get("timescale") if mvhd else None,
            "movie_duration": mvhd.fields.get("duration") if mvhd else None,
            "video_track_id": v_track.track_id if v_track else None,
            "video_codec": v_track.codec if v_track else None,
            "video_timescale": v_track.timescale if v_track else None,
            "video_duration": v_track.duration_track if v_track else None,
            "video_fps": round(fps, 3),
            "video_width": v_track.width if v_track else 0.0,
            "video_height": v_track.height if v_track else 0.0,
            "audio_track_id": a_track.track_id if a_track else None,
            "audio_codec": a_track.codec if a_track else None,
            "audio_timescale": a_track.timescale if a_track else None,
        }


def compare_mp4_files(orig_path: Path, patched_path: Path) -> ForensicDiffResult:
    orig_bytes = orig_path.read_bytes()
    patch_bytes = patched_path.read_bytes()

    orig_analyzer = MP4ForensicAnalyzer(orig_bytes, str(orig_path))
    patch_analyzer = MP4ForensicAnalyzer(patch_bytes, str(patched_path))

    orig_report = orig_analyzer.parse()
    patch_report = patch_analyzer.parse()

    # 1. Byte diff comparison
    byte_diffs: list[ByteDiffSpan] = []
    min_len = min(len(orig_bytes), len(patch_bytes))
    idx = 0

    while idx < min_len:
        if orig_bytes[idx] != patch_bytes[idx]:
            start_diff = idx
            while idx < min_len and orig_bytes[idx] != patch_bytes[idx]:
                idx += 1
            length = idx - start_diff
            atom_path = _find_atom_path_at_offset(orig_report.atom_tree, start_diff)
            byte_diffs.append(
                ByteDiffSpan(
                    offset=start_diff,
                    length=length,
                    atom_path=atom_path,
                    old_bytes_hex=orig_bytes[start_diff : start_diff + length][:32].hex(),
                    new_bytes_hex=patch_bytes[start_diff : start_diff + length][:32].hex(),
                )
            )
        else:
            idx += 1

    # 2. Changed atom paths
    orig_atoms = _flatten_atom_paths(orig_report.atom_tree)
    patch_atoms = _flatten_atom_paths(patch_report.atom_tree)
    changed_atoms: list[str] = []

    for path, o_hash in orig_atoms.items():
        if path in patch_atoms:
            if patch_atoms[path] != o_hash:
                changed_atoms.append(path)
        else:
            changed_atoms.append(f"{path} (removed)")
    for path in patch_atoms:
        if path not in orig_atoms:
            changed_atoms.append(f"{path} (added)")

    # 3. Semantic differences
    semantic_diffs: list[SemanticDiffEntry] = []
    _diff_summaries(orig_report.summary_fields, patch_report.summary_fields, semantic_diffs)

    # Track semantic diffs
    _diff_tracks(orig_report.tracks, patch_report.tracks, semantic_diffs)

    # 4. Payload integrity checks
    mdat_changed = orig_report.mdat_payload_sha256 != patch_report.mdat_payload_sha256
    v_orig = next((t for t in orig_report.tracks if t.handler_type == "vide"), None)
    v_patch = next((t for t in patch_report.tracks if t.handler_type == "vide"), None)
    a_orig = next((t for t in orig_report.tracks if t.handler_type == "soun"), None)
    a_patch = next((t for t in patch_report.tracks if t.handler_type == "soun"), None)

    video_payload_changed = (
        bool(v_orig and v_patch and v_orig.sample_payload_sha256 != v_patch.sample_payload_sha256)
    )
    audio_ghost_samples = 0
    if a_orig and a_patch and a_patch.sample_count > a_orig.sample_count:
        # Extra samples appended (BXD ghost tail): compare only the original sample range.
        audio_ghost_samples = a_patch.sample_count - a_orig.sample_count
        prefix_hash = patch_analyzer.hash_track_prefix(
            patch_report.atom_tree, a_patch.track_id, a_orig.sample_count
        )
        audio_payload_changed = prefix_hash != a_orig.sample_payload_sha256
    else:
        audio_payload_changed = bool(
            a_orig and a_patch and a_orig.sample_payload_sha256 != a_patch.sample_payload_sha256
        )

    # 5. BXD classification and hypothesis
    bxd_class: dict[str, list[str]] = {
        "UNCHANGED": [],
        "CHANGED": [],
        "UNKNOWN": [],
    }
    if not mdat_changed:
        bxd_class["UNCHANGED"].append("mdat")
    else:
        bxd_class["CHANGED"].append("mdat")

    if not video_payload_changed:
        bxd_class["UNCHANGED"].append("video sample payload")
    else:
        bxd_class["CHANGED"].append("video sample payload")

    if not audio_payload_changed:
        bxd_class["UNCHANGED"].append("audio sample payload")
    else:
        bxd_class["CHANGED"].append("audio sample payload")

    for atom in changed_atoms:
        if atom in (
            "moov/mvhd",
            "moov/trak/mdia/mdhd",
            "moov/trak/edts/elst",
            "moov/trak/mdia/minf/stbl/stts",
            "moov/trak/mdia/minf/stbl/ctts",
        ):
            bxd_class["CHANGED"].append(atom)
        else:
            bxd_class["UNKNOWN"].append(atom)

    hypotheses: list[str] = []
    if not mdat_changed and not video_payload_changed:
        hypotheses.append("VERIFIED: Video sample payload was preserved completely losslessly.")
    else:
        hypotheses.append("VERIFIED: Video payload was modified or re-encoded.")

    if "moov/trak/mdia/mdhd" in changed_atoms:
        hypotheses.append("OBSERVED: Track timescale was modified in mdhd.")
    if "moov/mvhd" in changed_atoms:
        hypotheses.append("OBSERVED: Container movie timescale was modified in mvhd.")
    else:
        hypotheses.append("OBSERVED: Container movie timescale was left untouched in mvhd.")

    return ForensicDiffResult(
        original_path=str(orig_path),
        patched_path=str(patched_path),
        file_size_changed=len(orig_bytes) != len(patch_bytes),
        size_difference=len(patch_bytes) - len(orig_bytes),
        mdat_changed=mdat_changed,
        video_payload_changed=video_payload_changed,
        audio_payload_changed=audio_payload_changed,
        moov_changed=orig_report.moov_sha256 != patch_report.moov_sha256,
        changed_atoms=changed_atoms,
        byte_diffs=byte_diffs,
        semantic_diffs=semantic_diffs,
        bxd_classification=bxd_class,
        hypothesis=hypotheses,
        before=orig_report,
        after=patch_report,
        audio_ghost_samples=audio_ghost_samples,
    )


def _find_atom_path_at_offset(tree: list[AtomNode], offset: int, current_path: str = "") -> str:
    for node in tree:
        if node.start <= offset < node.start + node.size:
            path = f"{current_path}/{node.type_str}" if current_path else node.type_str
            if node.children:
                sub = _find_atom_path_at_offset(node.children, offset, path)
                if sub:
                    return sub
            return path
    return current_path or "unknown"


def _flatten_atom_paths(
    tree: list[AtomNode], current_path: str = ""
) -> dict[str, str]:
    out: dict[str, str] = {}
    type_counts: dict[str, int] = {}
    for node in tree:
        type_counts[node.type_str] = type_counts.get(node.type_str, 0) + 1

    type_seen: dict[str, int] = {}
    for node in tree:
        idx = type_seen.get(node.type_str, 0)
        type_seen[node.type_str] = idx + 1
        tag = f"{node.type_str}[{idx}]" if type_counts[node.type_str] > 1 else node.type_str
        path = f"{current_path}/{tag}" if current_path else tag
        out[path] = node.sha256
        if node.children:
            out.update(_flatten_atom_paths(node.children, path))
    return out


def _diff_summaries(
    s1: dict[str, Any], s2: dict[str, Any], diffs: list[SemanticDiffEntry]
) -> None:
    for k in (
        "movie_timescale",
        "movie_duration",
        "video_timescale",
        "video_duration",
        "video_fps",
        "video_codec",
        "audio_codec",
    ):
        v1 = s1.get(k)
        v2 = s2.get(k)
        if v1 != v2:
            diffs.append(
                SemanticDiffEntry(
                    target="container",
                    field=k,
                    old_value=v1,
                    new_value=v2,
                    interpretation=f"{k}: {v1} -> {v2}",
                )
            )


def _diff_tracks(
    t1: list[TrackAnalysis], t2: list[TrackAnalysis], diffs: list[SemanticDiffEntry]
) -> None:
    for tr1 in t1:
        tr2 = next((t for t in t2 if t.track_id == tr1.track_id), None)
        if not tr2:
            diffs.append(
                SemanticDiffEntry(
                    target=f"trak[{tr1.track_id}]",
                    field="track",
                    old_value="present",
                    new_value="missing",
                    interpretation=f"Track {tr1.track_id} removed",
                )
            )
            continue
        if tr1.timescale != tr2.timescale:
            diffs.append(
                SemanticDiffEntry(
                    target=f"trak[{tr1.track_id}]/mdia/mdhd",
                    field="timescale",
                    old_value=tr1.timescale,
                    new_value=tr2.timescale,
                    interpretation=f"Track timescale: {tr1.timescale} -> {tr2.timescale}",
                )
            )
        if tr1.duration_track != tr2.duration_track:
            diffs.append(
                SemanticDiffEntry(
                    target=f"trak[{tr1.track_id}]/mdia/mdhd",
                    field="duration",
                    old_value=tr1.duration_track,
                    new_value=tr2.duration_track,
                    interpretation=f"Track duration: {tr1.duration_track} -> {tr2.duration_track}",
                )
            )


def export_diff_artifacts(
    orig_or_diff: Path | MP4DiffResult,
    patched_or_out: Path | None = None,
    out_dir: Path | None = None,
) -> tuple[Path, Path, Path]:
    if isinstance(orig_or_diff, ForensicDiffResult):
        diff_res = orig_or_diff
        target_dir = patched_or_out if isinstance(patched_or_out, Path) else out_dir
        if target_dir is None:
            raise ValueError("Destination out_dir is required.")
        before_rep = diff_res.before or MP4ForensicAnalyzer(
            Path(diff_res.original_path).read_bytes(), diff_res.original_path
        ).parse()
        after_rep = diff_res.after or MP4ForensicAnalyzer(
            Path(diff_res.patched_path).read_bytes(), diff_res.patched_path
        ).parse()
    else:
        if patched_or_out is None or out_dir is None:
            raise ValueError("orig_path, patched_path, and out_dir are required.")
        diff_res = compare_mp4_files(orig_or_diff, patched_or_out)
        target_dir = out_dir
        before_rep = diff_res.before or MP4ForensicAnalyzer(
            orig_or_diff.read_bytes(), str(orig_or_diff)
        ).parse()
        after_rep = diff_res.after or MP4ForensicAnalyzer(
            patched_or_out.read_bytes(), str(patched_or_out)
        ).parse()

    target_dir.mkdir(parents=True, exist_ok=True)
    before_json = target_dir / "before.json"
    after_json = target_dir / "after.json"
    diff_json = target_dir / "diff.json"

    before_json.write_text(json.dumps(before_rep.to_dict(), indent=2), encoding="utf-8")
    after_json.write_text(json.dumps(after_rep.to_dict(), indent=2), encoding="utf-8")
    diff_json.write_text(json.dumps(diff_res.to_dict(), indent=2), encoding="utf-8")

    return before_json, after_json, diff_json
