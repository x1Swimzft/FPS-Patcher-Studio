# Method V4 Audit & Architectural Analysis

## 1. Project Overview & Structure
- **Runtime**: Python 3.11, CustomTkinter (UI), TkinterDnD (Drag-and-Drop), FFmpeg/ffprobe subprocess integration.
- **Architecture**:
  - `src/fps_patcher/core/`: Domain logic, models, MP4 parsers, FFmpeg wrappers, patchers. Free of UI dependencies.
  - `src/fps_patcher/app/`: Controller (`AppController`) running worker threads and queue dispatch into Tk main thread.
  - `src/fps_patcher/ui/`: CustomTkinter GUI widgets (`MainWindow`, `DropZone`, `InfoPanel`, `ControlPanel`, `LogConsole`).
  - `tests/`: Pytest suite (`test_core.py`, `test_app.py`, `test_integration.py`, `test_atom_patcher.py`).

## 2. Method V3 Implementation Analysis
Method V3 (`src/fps_patcher/core/atom_patcher.py`) performs in-place binary patching on MP4/MOV atoms without invoking FFmpeg.

### What Method V3 Does
1. Parses top-level boxes (`ftyp`, `moov`, `mdat`, `free`, etc.).
2. Finds the single video track (`trak -> mdia -> hdlr == b'vide'`).
3. Computes scaling factor: `scale = Fraction(target_timescale, old_timescale)`.
4. Patches `mdhd`:
   - Writes `target_timescale` at offset 12 (v0) or 20 (v1).
   - Scales and rewrites `duration` at offset 16 (v0) or 24 (v1).
5. Patches `elst` (Edit List Box):
   - Scales `media_time` field (which is in track timescale units).
   - Leaves `segment_duration` untouched (it is in movie timescale units).
6. Patches `stts` (Time-to-Sample Box):
   - Unpacks run-length delta entries.
   - Scales per-sample deltas using cumulative drift reduction (`_scale_deltas`).
   - Re-compresses runs using `_compress_values`.
   - Overwrites original `stts` payload in-place, zero-padding remainder if smaller.
7. Patches `ctts` (Composition Time-to-Sample Box):
   - Unpacks composition offsets.
   - Scales offsets using `_scale_int`.
   - Re-compresses runs and overwrites payload in-place with zero-padding.

### Atoms Modified by Method V3
- `moov/trak/mdia/mdhd`
- `moov/trak/edts/elst`
- `moov/trak/mdia/minf/stbl/stts`
- `moov/trak/mdia/minf/stbl/ctts`

## 3. Limitations of Method V3 & Points of Failure

| Area | Limitation / Failure Mode in V3 | Impact |
|---|---|---|
| **Movie Timescale (`mvhd`)** | Does NOT patch `mvhd.timescale` or `mvhd.duration`. | Video track timescale changes (e.g., 60000), but container movie timescale remains (e.g., 1000 or 600). Platforms reading `mvhd` see mismatched timescale. |
| **Track Header (`tkhd`)** | Does NOT patch `tkhd.duration`. | `tkhd.duration` is expressed in `mvhd.timescale` units. If total duration drifts slightly, `tkhd` becomes inconsistent with `mdhd`. |
| **Box Capacity (`stts` / `ctts`)** | Re-compressed run count must be `<= original box capacity`. | If variable frame rate or non-uniform scaling expands run count beyond original box size, V3 raises `PatchError("stts expansion exceeds original box capacity.")`. |
| **Multiple Tracks** | Fails with `Multiple video tracks are not supported`. | Cannot process multi-video, picture-in-picture, or auxiliary video tracks. |
| **Fragmented MP4** | Rejects `moof` boxes completely. | Dash/CMAF/fragmented MP4 cannot be patched. |
| **`stsz` Sample Size Integrity** | Completely ignores `stsz` (Sample Size Box). | Does not verify sample count against `stts`, nor check sample offset alignment. |
| **Chunk Offsets (`stco` / `co64`)** | Completely ignores `stco`/`co64`. | Cannot resize `moov` without corrupting sample data pointers in `mdat`. |

## 4. Why FFmpeg Fails for Precision Forensic Patching
- FFmpeg stream copy (`-c copy -video_track_timescale N`) does not perform an in-place container edit; it remuxes the file into a brand new container.
- FFmpeg rebuilds all sample tables (`stts`, `stsc`, `stco`, `stsz`, `ctts`), changes atom ordering, recalculates chunk boundaries, alters padding, and changes default metadata tags.
- Result: While media bytes are technically uncompressed, container layout differs significantly from native mobile camera or editing software outputs, allowing ingest platforms (TikTok, Instagram) to detect remuxing and trigger re-encoding pipelines.

## 5. Reusable Components for Method V4
- `Box` dataclass and binary unpacking primitives (`_read_box`, `_children`, `_find_children`).
- `_scale_deltas` drift-free cumulative rounding algorithm.
- `_compress_values` run-length encoding.
- Verification pipeline (`verifier.py`) with tolerance comparison and ffprobe validation.
- Subprocess runners and UI async controller framework.
