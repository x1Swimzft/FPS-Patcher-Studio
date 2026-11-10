# FPS Patcher Studio — Reverse Engineering Report

**Target:** `E:\Project\fps-patcher-studio`

**Version analysed:** `2.1.0` (base analysis at `2.0.1`; §9.6 added for the Zilem preset)

**Build identity:** unsigned Windows x64 one-folder build; the 2.0.1 manifest recorded commit `abb6d9b6b088c220f31571f04b6c51620bd2daf0`, built `2026-11-04T11:31:32Z` with Python 3.11.18, PyInstaller 6.22.3 and Inno Setup 7.1.1
**Method:** full static read of the Python source, build scripts and tests; repository-wide quality-gate runs; controlled media experiment with the bundled FFmpeg; atom-level inspection of every output preset and engine; comparison of hashes, sample tables and edit lists.

This report is analysis only. No application source file was modified.

---

## 1. One-page mental model

FPS Patcher Studio is a Windows desktop app and headless CLI that changes the **clock stored in an MP4/MOV container**, not the encoded frames. It is a container editor, not a frame-rate converter.

There are two families of engines:

1. **Standards-oriented direct patchers**
   - **Method V3** (`direct-atom`): edits video `mdhd`, `stts`, `ctts`, `elst`, moves `moov` in front of `mdat`, and rewrites every chunk offset.
   - **Method V4** (`v4-forensic`): edits the same timing tables but performs a full-file SHA-256 and per-track sample-payload verification; optionally synchronises `mvhd`/`tkhd`; preserves the source layout instead of forcing faststart.
2. **X1T/BXD presets** (`bxd-pc`, `bxd-mobile`, `bxd-hybrid`, `bxd-clean`)
   - Rebuild the complete `moov` in memory.
   - Force `mvhd.duration` to the indeterminate `-1` value.
   - Add either **ISO-BMFF `free` padding** (Mobile/Hybrid), **trailing ghost audio samples outside `mdat`** (PC), or nothing (Clean).
   - Hybrid additionally extends the last video sample by up to `bxd_max_tail_ms` (default 50 ms).

The default GUI preset is **X1T Zilem** since 2.1.0. The four X1T/BXD presets are still registered for saved settings and the CLI but are hidden from the pickers. The default CLI strategy is whatever is in `settings.json`; new installs start at `zilem`. A saved `tiktok-ts-remux` from 2.0.x is migrated to `zilem` once on first 2.1.0 launch; other saved values are preserved.

Two important truths about the product:

- The **video `mdat` payload is genuinely copied byte-for-byte** in all direct engines. The experiment in §23 confirms identical video sample hashes after every preset.
- The X1T "bypass" is a **container-metadata heuristic**, not a guarantee that TikTok, Instagram or YouTube will skip transcoding. The repository itself says this repeatedly, and `reports/tiktok_benchmark/README.md` explicitly says no preset has been proven a winner.

---

## 2. Repository inventory

| Area | Contents | Size |
|---|---|---:|
| `src/fps_patcher/core` | Container engines, probing, preflight, verification, profiles, updater, history | 22 files, 8,405 LOC |
| `src/fps_patcher/app` | Controller, queue model, watcher, quick patch, Explorer/startup integration | 7 files, 1,470 LOC |
| `src/fps_patcher/ui_qt` | PySide6 shell, queue, inspector, settings, dialogs, theme, motion | 17 files, 9,565 LOC |
| `src/fps_patcher/ui` | English/Thai strings and image/font assets | 2 files, 896 LOC |
| `src/fps_patcher` root | Entry point, CLI, settings, logging | 5 files, 900 LOC |
| `tests` | 56 `test_*.py` modules, 556 `def test_` functions, 635 collected cases | 11,649 LOC |
| `build` | PyInstaller spec, Inno Setup script, release/signing scripts, manifest | 302-line release script |
| `docs` | Privacy, signing, platform presets, roadmap, security reports | 33 files |
| `release` | v0.9.0 → v2.0.1 zips, setup EXEs, hashes, SBOMs, JSON manifests | v2.0.1 zip 123,246,468 B; Setup 88,411,782 B |
| `dist/FPSPatcherStudio` | Built one-folder app with bundled `_internal/bin/ffmpeg.exe` and `ffprobe.exe` | ~211 MB of FFmpeg binaries before compression |
| `experiments/tiktok-fps` | Six generated variants and TikTok download samples | media experiments |
| `graphify-out` | Generated knowledge-graph output, not part of the app runtime | ~8.7 MB JSON + HTML |

**Python count:** 53 source modules, 21,236 lines. Runtime dependencies are only `pillow>=13.0.0` and `pyside6==6.12.0`; development uses pytest 9.1.1, pytest-qt 4.5.0, mypy 2.4.0 and ruff 0.16.10. The lockfile pins PySide6/shiboken6 6.12.0 and Pillow 13.0.0.

The repository contains four generated/reference trees that are not part of the shippable Python package: `release/`, `dist/`, `experiments/`, `graphify-out/`. `release/` and `dist/` are git-ignored; `experiments/` and `graphify-out/` are working artifacts.

---

## 3. Entry points and startup paths

`src/fps_patcher/__main__.py` is the single dispatcher.

```
fps-patcher-studio
├── --cli ...            -> fps_patcher.cli.main   (no Qt import)
├── --quick-patch FILE   -> app.quick_patch.run    (no Qt import)
├── --startup            -> strip flag, then Qt GUI, hidden in tray if available
└── default              -> ui_qt.app.run          (PySide6)
```

Details:

- `--cli` is detected anywhere in argv; everything after the first `--cli` is passed to argparse. The CLI deliberately never imports PySide6, so it works in a console/service context and in the frozen windowed EXE through `attach_console()`.
- `--quick-patch` is intended for the Explorer context-menu verb. It loads settings, probes FFmpeg, calls `core.patcher.patch()` synchronously, shows a Windows toast, and exits 0/1.
- `--ui tk` and `FPS_PATCHER_UI=tk` are accepted for compatibility but emit a deprecation warning and still launch Qt. There is no Tk UI left in the source.
- `--startup` is the per-user Run-key argument. If the tray is available, `ui_qt.app.run()` constructs the window but does not show it.
- On Windows the GUI path sets `SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)` so taskbar grouping and toasts use the app identity.
- Root logging is configured by `logging_setup.py`: `%APPDATA%\FPSPatcherStudio\fps_patcher.log`, 1 MB × 3 rotating files.

There is **no application-level single-instance mutex**. Multiple GUI instances can run. Per-destination locking prevents two processes from writing the same output file, but settings, queue and job-history writes are only thread-locked inside one process (the CHANGELOG calls out the history limitation).

---

## 4. Architecture and threading

```
┌────────────────────────────────────────────────────────────────────┐
│ Presentation                                                       │
│  ui_qt (PySide6)          CLI (argparse)        quick_patch        │
│  MainWindow / QueueView   patch|probe|score     Explorer verb      │
│  Inspector / Console      history|undo                             │
└───────────────┬──────────────────────┬─────────────────────────────┘
                │ Qt signals / queue    │ direct calls
┌───────────────▼──────────────────────▼─────────────────────────────┐
│ Application orchestration                                          │
│  AppController (2 patch workers, event queue)                      │
│  InputQueue/QueueItem, FolderWatcher, Settings, job_history        │
└───────────────┬────────────────────────────────────────────────────┘
                │ PatchRequest
┌───────────────▼────────────────────────────────────────────────────┐
│ core.patcher — one-file transaction                                │
│  validate -> probe -> preflight plan -> run preflight              │
│  -> strategy -> colr -> verify -> backup -> atomic replace         │
│  -> job history                                                    │
└───┬───────────┬────────────┬────────────┬────────────┬─────────────┘
    │           │            │            │            │
 atom_patcher  bxd_patcher  v4_patcher   preflight    verifier
 (V3)          (X1T)        (V4)         (FFmpeg)     (structure/payload)
    │           │            │            │
    └───────────┴────────────┴────────────┴──> ISO-BMFF bytes / mdat
```

**Threading rules:**

- Core modules have no Qt dependency.
- `AppController` workers only `put()` events on a `queue.Queue`.
- `ControllerBridge` drains that queue on the Qt main thread with a single-shot `QTimer` (50 ms when busy, 200 ms when idle, max 500 events per drain).
- Widgets are therefore never touched from worker threads.
- Preflight FFmpeg encodes are serialised process-wide by `threading.Semaphore(1)`, while up to two sources can be patched concurrently. The semaphore is **process-local**; two app instances can still encode simultaneously.
- `ProcessJob` (Windows job object) assigns each ffmpeg/ffprobe child so cancel, app exit or crash kills the whole process tree.

---

## 5. Data model and event model

`core/models.py` defines the whole cross-layer contract:

| Type | Role |
|---|---|
| `VideoInfo` | Frozen probe result: codec, dimensions, `Fraction` fps, duration, timescale, frame count, audio codec/rate/channels, bitrate, format, color tags, pixel format, file size. `fps` falls back to `r_fps`; `is_vfr` means `abs(avg-r) > 0.5`. |
| `PatchRequest` | Frozen request with source, output dir, timescale, strategy, V4 controls, BXD padding/tail controls, preflight flags, color/scrub flags, verification, backup, mtime, diagnostics, extra FFmpeg args, filename template, platform profile. |
| `PatchResult` | Source/output, before/after `VideoInfo`, elapsed time, `experimental` flag, optional `.bak` path. |
| `LogEvent` | Message plus `INFO/OK/WARN/ERROR/DEBUG`. |
| `ProgressEvent` | Overall fraction, per-file fraction, current file, file/total index. |
| `ProbeDoneEvent` | Probe info or error plus queue count/paths. |
| `PatchDoneEvent` | Last result, error, stderr tail, all batch results, failures, total, cancelled flag. |
| `QueueChangedEvent` | UI should re-render rows. |
| `FFmpegDownloadEvent` | Download/extract/verify/done/error progress. |
| `UpdateAvailableEvent` / `UpdateDownloadEvent` | Updater lifecycle. |

`app/queue_model.py` adds `QueueItem` (path, status, info, error, selection, output, per-item timescale/strategy/profile override, progress) and `InputQueue`, a pure-Python append-only queue with duplicate rejection, selection, moves, status updates, overrides, JSON persistence and legacy strategy migration.

Statuses: `pending`, `probing`, `ready`, `patching`, `done`, `failed`, `skipped`.

---

## 6. End-to-end patch transaction

`core/patcher.py::patch()` is the transaction boundary. Its order is important:

1. **Validate** the source exists and has `.mp4`, `.mov` or `.m4v`.
2. **Resolve the strategy.** Direct engines do not require FFmpeg; `ffmpeg-copy` does.
3. **Probe** with ffprobe when available, otherwise with the direct MP4 parser.
4. **Warn** on VFR, bitrate > 25 Mbps and non-AAC audio.
5. **Compute the output base**:
   - default: `<stem>_ts<timescale><ext>`;
   - X1T on `.mov`/`.qt` outputs `.mp4`;
   - custom template tokens `{name}`, `{fps}`, `{timescale}`, `{date}`, `{platform}`, `{strategy}`.
6. **Acquire the destination lock.** A per-path `threading.Lock` plus a Windows named mutex (`Local\fps-patcher-<sha256(path)[:24]>`) serialises writers across threads and processes.
7. **Choose a collision-safe final path.** `overwrite` wins; otherwise auto-rename `(1)`, `(2)`, … or raise `OutputFileExistsError`.
8. **Create a temporary output beside the final path**, `.<stem>.<random><ext>.part`, and clean abandoned temps older than 24 h.
9. **Plan preflight** (`make_plan`) and optionally run a temporary FFmpeg pass:
   - audio normalisation to AAC 48 kHz stereo 192 kbps;
   - bitrate cap to 1–24 Mbps (default 16);
   - VFR → CFR;
   - codec → H.264 when the selected profile does not support the source codec;
   - resolution fit within profile caps.
10. **HDR guard.** If a video re-encode is planned and the source transfer is PQ/HLG and the plan is *not* a bitrate cap, abort instead of silently destroying HDR. (The exact condition has a gap; see §24.)
11. **Colour/metadata rewrite** with `colr.sanitize()`:
    - on the preflight copy for PC mode, because the finished PC file has trailing ghost bytes a box parser would reject;
    - after the engine for Mobile/Hybrid/Clean/V3/V4/FFmpeg;
    - PC without a preflight copy logs `[COLOR] skipped` rather than failing.
12. **Dispatch** to V4, BXD/X1T, V3 or FFmpeg streaming.
13. **Probe the temporary output.**
14. **Hard verification** via `verify(before, after, target_timescale)`: codec, stream count, resolution, timescale, audio presence, frame count, duration tolerance. Failures raise `VerifyError`.
15. **Payload/structural report** via `verify_payload_integrity()`: structure, trailing data, chunk offsets, sample tables, mobile compatibility, mdat head/mid/tail hashes, video/audio sample chunks, optional ghost detection. Important: statuses of `FAIL` are logged but **do not abort**; only `EXPERIMENTAL` influences the result flag (§24).
16. **Back up an existing final file** with an exclusive `.bak` or `.<n>.bak` copy.
17. **Atomic replace** with `os.replace(temp, final)` (atomic on NTFS).
18. **Preserve the source mtime/atime** on the final file when enabled.
19. **Delete the preflight temp** and release the destination lock in `finally`.
20. **Record history** (`job_history.json`, best-effort; a history failure never fails a successful patch).
21. **Emit** the final progress and log event.

Failure handling deletes the temp, writes an auto-diagnostic log (unless it fails), and wraps unexpected exceptions in `PatchError`. `finally` always removes a preflight temp and releases the destination lock.

### Output naming and multi-platform fan-out

- Default naming is deterministic and collision-safe.
- With `use_filename_template`, `{fps}` is `round(timescale/1000)`; `{timescale}` is the full integer.
- Multi-platform runs force a `{platform}` token into the template (appending `_{platform}` if absent), so one input can produce TikTok/Instagram/YouTube variants.
- If a queue item has a platform override, that item exports only that profile, even when global multi-export is enabled.

---

## 7. ISO-BMFF internals used by the app

The relevant boxes:

| Box | Meaning |
|---|---|
| `ftyp` | File brand/compatibility. BXD rewrites QuickTime `qt  ` to `mp42/isom/iso2/mp41`. |
| `moov` | Movie metadata: `mvhd`, one `trak` per track, optional `udta`/`meta`. |
| `mvhd` | Movie header: movie timescale and duration. |
| `trak/tkhd` | Track header: track ID, movie-timescale duration, dimensions. |
| `trak/edts/elst` | Edit list: segment duration (movie timescale), media start time (media timescale), media rate. |
| `trak/mdia/mdhd` | Media header: media timescale and duration. |
| `trak/mdia/minf/stbl/stts` | Decode-time table: runs of `(sample_count, sample_delta)`. |
| `stbl/ctts` | Composition-time offsets (B-frames). |
| `stbl/stsz` | Sample sizes. |
| `stbl/stsc` | Samples-per-chunk mapping. |
| `stbl/stco` / `co64` | Chunk byte offsets (32/64-bit). |
| `mdat` | Encoded media payload. |

The app's core operation is changing the video `mdhd.timescale` (e.g. `15360 → 60000`) and scaling all video decode deltas/offsets by `60000/15360`, then leaving `mdat` untouched. Players then interpret the same frames on a different clock. This does **not** interpolate frames or make motion smoother.

---

## 8. Method V3 — `direct-atom`

`core/atom_patcher.py::patch_video_track_timescale()`.

Algorithm:

1. Refuse if output path resolves to the source.
2. Read the entire file into a `bytearray`.
3. Parse top-level boxes with 32-bit, extended 64-bit and `size == 0` support. A truncated tail is tolerated only after `moov`/`mdat` were seen.
4. Reject fragmented files containing `moof`.
5. Find `moov`; find exactly one video `trak` by `hdlr` type `vide`. Multiple video tracks are rejected.
6. If the source timescale already equals the target, write the original bytes unchanged.
7. Compute `scale = target / old`.
8. Patch the video `mdhd`:
   - version 0: 32-bit duration, version 1: 64-bit;
   - never patch audio `mdhd`.
9. Scale the video track's `edts/elst.media_time`; segment durations stay in movie timescale.
10. Expand `stts` runs to per-sample deltas, scale with cumulative rounding (`_scale_deltas`), recompress into runs; the new payload must fit in the original box size or the patch aborts.
11. Scale signed `ctts` composition offsets.
12. **Faststart reorganisation:** if `moov` is after `mdat`, rebuild as `pre-mdat + moov + mdat + rest`. Add `moov.size` to every `stco`/`co64` offset because the media moved later by exactly the moov size.
13. Write to `<out>.tmp_direct`, run structural verification, then `replace()` the temp.

Strengths:

- Very conservative; only video timing boxes are touched.
- No `moov` rebuild and no padding/ghost data.
- Faststart shift is correct for multiple `mdat`s because all media after the inserted `moov` moves by the same amount.
- Structural verification is performed before publishing.

Limits:

- Reads the whole file into RAM.
- One video track only; no `moof`.
- Does not update `mvhd` or `tkhd`; this is fine because the movie timescale is unchanged.
- Does not scale audio timing; correct, because audio is left alone.
- If scaling increases the number of `stts` runs beyond the original box capacity, it fails rather than relocating/rebuilding `stbl`.
- Audio `edts` is left unchanged, which is correct because music/audio clock is unchanged.

Empirical result: 105,446 B source → 105,446 B output; `ftyp/free/moov/mdat`; video `60000` timescale, 60 × 2000 ticks; audio untouched; `mvhd` unchanged at 48000/96000; all payload hashes identical.

---

## 9. X1T/BXD engine

`core/bxd_patcher.py` is the product's differentiating engine. `strategies.py` exposes four GUI presets plus legacy aliases:

| UI name | Key | `strip_edts` | Audio ghost samples | `free` box | `mvhd` |
|---|---|---:|---:|---:|---|
| X1T For PC | `bxd-pc` | yes | yes (10×, capped 50,000 samples) | no | `-1` |
| X1T For Mobile | `bxd-mobile` | no | no | yes (default payload ≤ 4096 B) | `-1` |
| X1T Hybrid | `bxd-hybrid` | no | no | yes (default payload ≤ 4096 B) | `-1` |
| X1T Clean | `bxd-clean` | no | no | no | `-1` |

`bxd-experimental`/`x1t-experimental` map to PC behaviour. Legacy `x1t-*` keys are aliases of `bxd-*`.

### 9.1 `MethodBXDDirectPatch.execute()`

1. Read the whole source (`src.read_bytes()`).
2. Parse top-level atoms; reject `moof`.
3. Take the **first** `ftyp`, `moov` and `mdat`. Missing `moov`/`mdat` is fatal.
4. Normalise `.mov` or QuickTime `ftyp` to `mp42/isom/iso2/mp41` branding.
5. Hash a sample of the original mdat payload (head, middle, tail; 64 KiB each).
6. Classify tracks:
   - first `vide` → video track;
   - first `soun` → audio track;
   - everything else → generic tracks (shifted but not retimed).
7. Determine the video timescale: target if provided, otherwise source.
8. Hybrid only: compute tail extension:
   - `tail_add_mdhd = max(1, round(max_tail_ms/1000 × effective_video_ts))`;
   - `tail_add_mvhd = round(tail_add_mdhd × mvhd_ts / effective_video_ts)`.
9. Compute padding:
   - **PC with audio:** `raw_pad_count = audio_sample_count × (multiplier−1)` with `multiplier=10`, capped at 50,000 ghost samples; each ghost sample is 8 bytes of `PADDING_NAL` (`00 00 00 04 00 00 00 00`) written **after** `mdat`; audio sample tables are inflated to claim them.
   - **PC without audio:** no ghost inflation.
   - **Mobile/Hybrid:** a standards-compliant `free` box. Explicit `padding_bytes` wins; otherwise payload is `min(max(10, base_pad_samples × 9) × 8, 4096)`. For typical audio files this is exactly 4,096 B payload / 4,104 B total.
   - **Clean:** no padding.
10. Build a new `mvhd` with duration `-1`:
    - version 1 always;
    - 64-bit `0xFFFFFFFFFFFFFFFF`;
    - preserves creation/modification times and timescale.
11. Build the `moov` **twice**:
    - first with `shift=0` to learn the exact final moov size;
    - compute `new_mdat_offset = len(ftyp) + len(moov)`;
    - `shift = new_mdat_offset − old_mdat_offset`;
    - `ghost_offset = new_mdat_offset + old_mdat_size`;
    - rebuild with real offsets. If the second moov size changes, repeat once.
12. Rebuild the video track:
    - patch `mdhd` timescale/duration;
    - scale `stts` deltas, optionally add `tail_add_mdhd` to the last delta;
    - scale `ctts`;
    - shift `stco`/`co64`;
    - keep, scale or strip `edts/elst` depending on preset;
    - recompute `tkhd.duration` from the edit-list sum or scaled `mdhd` when appropriate.
13. Rebuild audio:
    - normal presets: shift offsets only, keep `edts`;
    - PC: strip `edts` and, if audio exists, inflate `stsz`, `stts`, `stsc`, `stco` to add the ghost chunk.
14. Rebuild other tracks with offset shifts only.
15. Preserve other `moov` children (e.g. `udta`) after tracks, except `mvhd`/`trak`.
16. Check disk space: expected output + 64 MB headroom.
17. Write `ftyp + moov + mdat header + mdat payload` in 8 MiB chunks; append `free` and/or ghost bytes.
18. Verify:
    - structural parse; malformed atoms abort and delete the output;
    - trailing data is reported (expected for PC);
    - chunk offsets are checked; outside-mdat offsets are reported experimental, not fatal;
    - sample tables must validate or the output is deleted;
    - mdat head/middle/tail hashes must match the source or the output is deleted;
    - mobile compatibility issues are warnings, not fatal.
19. Emit `[SUCCESS]`.

### 9.2 What each preset actually changes

- **PC**
  - `mvhd` v1 duration `-1`.
  - Video timescale retimed; `edts` stripped from all tracks.
  - Audio `stsz` grows from `N` to `N + min(9N, 50,000)` samples; `stts` gains a run `(ghost_count, 1)`; `stsc` gains a final chunk; `stco` gains an offset after `mdat`.
  - Ghost bytes are **outside** `mdat`, so strict parsers see unboxed trailing data and a chunk offset outside every mdat.
  - Audio `mdhd.duration` is **not** updated for the ghost samples. This makes `stts` sum exceed `mdhd.duration`; the verifier reports it.
  - Intentionally non-standard; `PatchResult.experimental = True`.
- **Mobile**
  - `mvhd` `-1`.
  - Video retimed; `edts` kept and media_time scaled.
  - Audio unchanged except shifted chunk offsets.
  - `free` box after `mdat`.
  - Structurally valid; mobile check passes (with a warning about indeterminate `mvhd`).
- **Hybrid**
  - Everything Mobile does, plus:
    - last video sample delta += `max_tail_ms` worth of ticks;
    - video `mdhd.duration` increases by the same amount;
    - video `tkhd.duration` and `elst.segment_duration` increase by the movie-timescale equivalent;
    - `mvhd` remains `-1`, so only the track/edit list carries the extra duration.
  - Default 50 ms at 60,000 timescale = 3,000 ticks; movie timescale 48,000 → 2,400 ticks.
- **Clean**
  - `mvhd` `-1`, video retimed, `edts` kept, no padding and no ghosts.
  - Smallest output; layout is `ftyp/moov/mdat`.

### 9.3 BXD constraints and side effects

- Only the **first** `ftyp`, `moov` and `mdat` survive. Other top-level boxes (`uuid`, `sidx`, `udta`, second `mdat`) are dropped. This is acceptable for conventional single-`mdat` files but not for arbitrary ISO-BMFF.
- `mdat` is streamed from source to output, but the source is first read completely into memory.
- The original `mdat` header is copied verbatim. If the source uses `size == 0` (extends to EOF), appending `free`/ghost bytes changes what “EOF” means: the padding becomes part of `mdat` rather than a separate box. Edge case; see §24.
- The `mvhd` version-1 tail extraction has an offset bug (`data[36:]` instead of `data[40:]`), so a source with a version-1 `mvhd` gains 4 extra bytes and a misaligned matrix/tail. Version-0 sources (the common case) are handled correctly.
- The constructor ignores its `indeterminate_mvhd` argument and always sets `True`; see §24.
- PC mode's output is not ISO-BMFF-clean by design. The UI warns that mobile decoders may reject it, and the verifier labels it `EXPERIMENTAL / NON-STANDARD`.

### 9.4 Repair engine — `repair_for_mobile()`

This is the lossless inverse for PC-style outputs. It is exposed from the Forensic window and `AppController.repair_file_for_mobile()`, not as a normal preset.

Strict six-step order:

1. Baseline SHA-256 of **real in-mdat samples** for every track (`MP4ForensicAnalyzer.hash_real_mdat_samples`).
2. Strip confirmed BXD ghost chunks from each `stbl`:
   - primary criterion: chunk offset outside `[mdat_payload_start, mdat_end)`;
   - confirmation gate: every sample size is 8, every delta is 1, and the bytes exactly match `PADDING_NAL`;
   - also detects the H2 in-mdat variant at the end of an audio track.
   - Non-BXD out-of-mdat chunks raise an error instead of being guessed away.
3. Parse the post-`mdat` region: keep only `free`, `skip`, `udta`, `meta`, `uuid`; strip unboxed tail bytes.
4. Recompute every `mdhd.duration` from the cleaned `stts` sum.
5. Reconstruct a missing video `edts/elst` from the first positive `ctts` composition offset, **before** computing `tkhd.duration`.
6. Compute `tkhd.duration` from the edit-list sum (or scaled `mdhd`), set `mvhd.duration` to the longest track, shift offsets, write a temp, verify full real-sample hashes and mobile compatibility, then `replace()`.

Empirical repair of the PC sample:

```
input  bxd-pc.mp4        115,662 B
output bxd-pc-repaired   105,414 B
removed 855 ghost samples / 6,840 trailing bytes
reconstructed video edts: segment 92,800, media_time 4,000
mvhd 97,280; video tkhd 92,800; audio tkhd 97,280
mobile check: Structure OK
```

Note the repaired file is **not** byte-identical to the Clean preset: it reconstructs the video edit list from `ctts`, removes the audio edit list (AAC priming cannot be recovered), and recomputes `mvhd`/`tkhd` durations. The real sample payload remains bit-identical.

### 9.5 Isolation variant generator

`generate_isolation_variants()` creates H1–H4 to test individual bypass hypotheses:

- H1: only indeterminate `mvhd`.
- H2: audio ghost table with ghost bytes inside `mdat`.
- H3: unboxed trailing ghost bytes + `stco` outside `mdat`.
- H4: only stripped `edts`.

However, the constructor always forces `indeterminate_mvhd = True`, so H1, H3 and H4 are **not** single-variable variants: all get `-1` `mvhd`. H2 is built from H3 and inherits that state. The test `test_phase0_isolation_variants_h1_to_h4` currently asserts H1's indeterminate header and never checks H3/H4's `mvhd`, so it blesses the bug. The hypothesis generator should not be treated as scientifically clean until the flag is honoured.

### 9.6 X1T Zilem (2.1.0)

`core/zilem_patcher.py` is a fifth, separate direct engine. It is not a BXD
variant and never calls FFmpeg. It reproduces the Zilem v1 container
fingerprint by extending and duplicating the audio track while leaving every
H.264 and AAC sample payload untouched.

**Accepted input.** `_validate_source()` parses the top-level boxes and the
`moov` tree, then requires:

- no `moof`/`mvex` (non-fragmented MP4);
- exactly one video track with an `avc1`/`avc3` sample entry;
- exactly one audio track with an `mp4a` sample entry, 2 channels, 48,000 Hz,
  and an AudioSpecificConfig whose first 13 bits are AAC-LC/48 kHz/stereo
  (a sync-extension tail is tolerated);
- variable-size `stsz` tables and 32-bit `stco` offsets, with a size guard
  below 4 GiB.

Anything else raises `ZilemSourceError` before the output file is opened.

**Transform.** `build_zilem()` copies the source byte-for-byte, then:

1. rewrites the old top-level `moov` type to `free` (size and payload are not
   changed);
2. appends an 8-byte `mdat` header plus 17 copies of the 6-byte AAC-LC silence
   frame `21 10 04 60 8c 1c` (110 bytes);
3. rebuilds the source audio track and a clone:
   - `stts` +17 samples at 1,024 samples/frame;
   - `stsz` +17 six-byte samples;
   - `stsc` +2 chunks (9 and 8 frames);
   - `stco` +2 offsets into the appended `mdat`;
   - `sgpd`/`sbgp` roll groups extended to cover the new samples;
   - `mdhd`, `tkhd`, and `elst` durations advanced by 17,408 audio ticks;
   - primary `stsd` holds two entries (original + alternate); the clone holds
     one entry;
4. adds `udta/meta/ilst/©too` to the video track with the neutral tag
   `X1T Zilem v1`, keeping existing track metadata and dropping the old
   movie-level `udta`;
5. updates `mvhd` duration and `next_track_ID`, then writes the rebuilt `moov`
   at EOF.

The 1080p reference pair has this layout:

```
ftyp 32
free 80,548                    (old moov, type changed)
mdat 161,394,760               (source video + audio, unchanged)
mdat 110                       (17 silence frames)
moov 100,951                   (rebuilt)
free 71                        (reference trailer; production omits it)
```

The reference tag
`TikQuick Quality Method - https://tikquick.online/ - v25 - Orion` is only a
golden-test input. Production always writes `X1T Zilem v1`. With the reference
tag supplied, `build_zilem()` matches the reference file byte-for-byte up to
the 71-byte trailer.

**Pipeline integration.** The `zilem` strategy is `direct = True`, so it needs
no FFmpeg. `patcher.patch()` skips `make_plan()`, the preflight stage, and the
colour/metadata rewrite. The target timescale is ignored, and the default
output name is `<stem>_zilem.mp4`. `verify_zilem_output()` re-checks the size,
top-level order, `ftyp`, the old-`moov`-as-`free` payload, every source `mdat`
hash, the silence frames, the two audio tracks, the durations, and the tag.
The golden test is gated by `FPS_ZILEM_SOURCE` and `FPS_ZILEM_REFERENCE` and
skips when the real fixture is absent.

**Limits.** Zilem cannot improve codec, resolution, frame rate, or bitrate; it
does not claim to bypass TikTok transcoding; and it rejects fragmented MP4,
multi-track inputs, non-H.264 video, and non-AAC-LC/48 kHz/stereo audio.

---

## 10. Method V4 — `v4-forensic`

`core/v4_patcher.py::MethodV4DirectPatch` is the strict-lossless sibling of V3.

- Rejects output == source; optional `max_file_size` guard (not wired by the patcher).
- Reads the whole file into memory.
- Rejects `moof`; requires `mdat` and at least one video track.
- Parses the top-level box tree with the V3 parser helpers.
- Patches the video `mdhd`, `stts`, `ctts` and video `elst` exactly like V3.
- Optionally (`v4_sync_mvhd`):
  - retimes `mvhd` timescale/duration;
  - retimes every `tkhd.duration`;
  - scales non-video `elst.segment_duration` by the movie scale;
  - scales video `elst.media_time` by the video scale and segment duration by the movie scale.
- **Does not force faststart**; the output keeps the source layout.
- Writes to `<out>.tmp_v4` (or simulates in dry-run).
- Verifies:
  - full mdat payload SHA-256 (strict lossless);
  - per-track sample payload SHA-256 for video and audio;
  - target video timescale.
- On mismatch, deletes the temp and raises `VerifyError`.
- Optional `export_report` writes a forensic diff bundle beside the output.
- Dry-run returns a `PatchResult` with output == source and does not create a file.

V4 is exposed through the CLI/strategy registry but not in the four GUI preset cards. It is the best choice when a user wants a standards-preserving retime with explicit forensic proof and no faststart rewrite.

Empirical result: 105,446 B source → 105,446 B output; layout unchanged (`ftyp/free/mdat/moov`); video 60,000/120,000 ticks; audio unchanged; `mvhd` unchanged 48,000/96,000; payload hashes identical. It is **not** faststart, so the mobile compatibility checker emits the “moov after mdat” warning.

---

## 11. Colour and metadata sanitizer

`core/colr.py::sanitize()` is a separate lossless moov rewriter used by `fix_color_tag` and `scrub_metadata`.

What it does:

1. Scan top-level boxes; reject multiple `moov`; record all `mdat` payload ranges; detect `moof`/`sidx`.
2. Read only `moov`; parse nested containers (`moov`, `trak`, `mdia`, `minf`, `stbl`).
3. Parse `stsd` visual sample entries (`avc1`, `avc3`, `hvc1`, `hev1`, `mp4v`, `av01`, `vp09`). Unsupported entries are preserved raw and reported.
4. For each visual entry:
   - if any explicit HDR box (`mdcv`, `clli`, `dvcC`, `dvvC`) or BT.2020/Display-P3 primaries, PQ/HLG transfer, or BT.2020 matrix is present → **skip colour**, leave tags untouched;
   - if no `colr` → append Rec.709 `nclx` (`primaries=1, transfer=1, matrix=1, full_range=0`);
   - if an existing `colr` is already Rec.709 → drop duplicate `colr` boxes;
   - otherwise replace the first `colr` with Rec.709.
5. `scrub_metadata` recursively removes every `udta` and `meta` child from the moov tree.
6. Verify the parsed tree serialises back byte-identically before making changes (`_serialize(moov) != moov_data` → refuse).
7. Recompute `moov` size delta; adjust **only** chunk offsets that point after the rewritten moov; offsets into media before moov stay put. This supports `mdat → moov → mdat` layouts.
8. Write prefix + new moov + suffix with a temp file, `fsync`, then `os.replace`.

Deliberate limits:

- Fragmented MP4 (`moof`/`sidx`) is refused (`status="skipped"`), not guessed.
- Only known VisualSampleEntry layouts are parsed; unknown sample entries are not tagged.
- Untagged HDR is indistinguishable from untagged SDR; only explicit signalling is detected.
- It does not tone-map; HDR is left alone.
- It accepts pipeline temps ending `.mp4.part`.
- `meta` scrubbing also removes metadata nested inside sample entries, not only top-level editor metadata.

Pipeline ordering detail: PC outputs append ghost NALs after `mdat`, which `colr`'s box parser would reject. For PC, the app therefore applies colour/metadata to the **preflight copy before** BXD appends ghosts. If no preflight copy exists, it logs a warning and skips the colour rewrite rather than producing a corrupt file.

---

## 12. Verification subsystem

`core/verifier.py` contains five independent checks with different semantics.

### 12.1 `verify_atom_structure()`

- Parses top-level boxes and recursively validates nested container boxes (`moov`, `trak`, `edts`, `mdia`, `minf`, `dinf`, `stbl`, `mvex`).
- Detects:
  - truncated headers;
  - non-printable box types;
  - size < header;
  - size beyond parent;
  - `size=0` not at EOF;
  - unboxed gaps inside containers.
- Statuses:
  - `VALID`;
  - `EXPERIMENTAL / NON-STANDARD` when the only problem is trailing data after valid `moov`/`mdat` and no nested issues (this is the PC ghost case);
  - `INVALID` for actual malformation.
- Note: experimental outputs have `is_valid=False`, even though `malformed_atoms=False`.

### 12.2 `verify_offsets()`

- Finds every `stbl` and its `stsz`/`stsc`/`stco`/`co64`.
- For each chunk, computes chunk byte length from `stsc` sample counts and `stsz` sizes.
- Requires the whole chunk to fit inside an `mdat` payload range.
- Falls back to a raw `stco`/`co64` scan if no moov tree exists.
- PC ghost chunks intentionally fail this check; the app reports `[REPORT] Chunk offsets status: EXPERIMENTAL` and continues.

### 12.3 `verify_sample_tables()`

- Checks `stsz` count > 0 and not truncated.
- Checks `sum(stts.sample_count) == stsz.sample_count`.
- Checks `stsc.first_chunk` range, monotonicity and mapped sample total.
- **Does not compare durations.** PC's audio `stts` sum can exceed `mdhd.duration` and still pass this check; the mobile check catches that separately.

### 12.4 `verify_mobile_compatibility()`

Returns `MobileCompatibilityReport` with:

- atom structure OK;
- chunk offsets OK;
- sample tables OK;
- faststart (moov before mdat);
- `mvex` presence;
- `mvhd` duration defined;
- `tkhd` duration consistent with `elst` or scaled `mdhd`;
- audio duration consistent with video;
- BXD ghost signature detection (last audio `stts` run delta 1, count ≥ 5, last sample sizes 8);
- an issues/warnings list.

Statuses:

- `Structure OK (likely mobile-compatible)` when no issues;
- `Non-standard (PC-oriented / likely fails on mobile)` otherwise.

Important semantic: an indeterminate `mvhd` duration (`0xFFFFFFFF`/`0xFFFFFFFFFFFFFFFF`) is treated as **defined** and only recorded as a warning. Thus all four X1T outputs, including Clean/Mobile, can be labelled mobile-compatible while carrying an unknown movie duration. That is intentional for the bypass hypothesis, but it means “mobile-compatible” here means *structural*, not *duration-complete*.

### 12.5 `verify_payload_integrity()`

Fast mode (`fast=True`, used by the patcher):

- samples mdat **head, middle and tail** (64 KiB each) and compares SHA-256;
- samples the first, middle and last chunk of the video and audio tracks and compares bytes;
- reports an `audio ghost samples` entry as experimental when the patched audio sample count exceeds the original;
- returns a status map.

Statuses: `PASS`, `EXPERIMENTAL`, `FAIL`, `CHECK`.

The patcher computes this map and logs each entry, but **does not abort on `FAIL`**. It only sets `PatchResult.experimental` if some status is `EXPERIMENTAL`. This is a deliberate “report, don't block” design for the payload check, but it means a `FAIL` can still be published. BXD, V4 and repair have their own internal hard aborts; V3 and `ffmpeg-copy` rely more heavily on this outer report.

### 12.6 `verify()`

Hard checks before publishing:

- codec unchanged;
- stream count unchanged;
- resolution unchanged;
- output timescale equals target;
- audio presence unchanged;
- frame count unchanged when both probes provide it;
- duration difference within tolerance.

Tolerance:

- default `max(0.1 s, source_duration × 0.001)`;
- Hybrid uses `max(0.25 s, bxd_max_tail_ms/1000 + 0.1 s)`.

Raises `VerifyError` on any failure; returns soft warning strings for minor duration deltas.

### 12.7 `forensic_analyzer.py`

This is the inspection/diff layer used by the Forensic dialog, V4, repair and the full compare path.

- `MP4ForensicAnalyzer.parse()` builds an atom tree with versions, flags, fields, children and per-box SHA-256; records top-level mdat/moov hashes and trailing data.
- `_extract_tracks()` pulls track ID, handler, codec, timescales, durations, dimensions, sample count, `stts`/`ctts`/`elst` entries and a sample-payload SHA-256.
- `hash_real_mdat_samples()` hashes only samples whose chunk offsets are strictly inside `mdat`; this is the lossless baseline used by repair.
- `compare_mp4_files()` produces byte diff spans, changed atom paths, semantic diffs, mdat/video/audio payload flags, BXD classification and hypotheses. It handles ghost samples by comparing only the original sample prefix.
- It reads both files completely into memory, so forensic comparison of large files is memory-heavy and linear in file size.

---

## 13. Probing

`core/prober.py`:

1. If a working `ffprobe` is available, run:
   `ffprobe -v error -print_format json -show_streams -show_format <file>`.
2. Parse the first video stream and first audio stream into `VideoInfo`:
   - codec, dimensions, `avg_frame_rate`, `r_frame_rate`, duration, time base denominator as timescale;
   - `nb_frames`, audio codec/sample rate/channels;
   - video/format bitrate, or whole-file `size × 8 / duration` fallback;
   - format name, color primaries/transfer/space, pixel format, file size.
3. On any ffprobe failure, fall back to `probe_direct()`.

`probe_direct()`:

- Reads only the `moov` box (64 MiB cap); never reads `mdat`.
- Scans top-level box headers with seek/read.
- Walks `trak/mdia/hdlr` to find `vide`/`soun`.
- Reads `tkhd` width/height; `mdhd` timescale/duration; `stsd` codec; `stsz` sample count; `stts` total deltas for average fps.
- Reads `colr` `nclx`/`nclc` from the first visual sample entry and audio sample rate/channels from the audio sample entry.
- Computes bitrate from file size ÷ duration.

Limitations:

- Only the first visual sample entry is inspected.
- `pix_fmt` is not available in direct mode.
- Audio rate/channels use version-0 AudioSampleEntry offsets even for QuickTime v1/v2 entries.
- The direct parser does not understand fragmented files.
- `stream_count` counts tracks, not all elementary streams.

The GUI prefers ffprobe data because it is richer (bitrate, color strings, pixel format); direct probing is the fallback that keeps the app usable without FFmpeg.

---

## 14. Preflight remediation

`core/preflight.py` separates pure planning from FFmpeg execution.

### 14.1 Plan

`PreflightPlan`:

- `normalize_audio`: source audio is not AAC/MP4A, or known sample rate ≠ 48 kHz, or known channels ≠ 2. Unknown values are **not** treated as mismatches.
- `cap_bitrate`: source bitrate > target. Target is clamped 1–24 Mbps; default 16. The 25 Mbps constant is only an advisory warning.
- `fix_vfr`: `VideoInfo.is_vfr` (avg vs r fps differ > 0.5).
- `transcode_codec`: source codec not in the selected profile's accepted set.
- `scale_width`/`scale_height`: only shrink; fit inside profile `max_dimension`/`max_short_side`; never upscale.

`needs_video_encode` is true for cap, VFR, codec or scale; `needed` also includes audio normalisation.

### 14.2 FFmpeg command

- Maps `0:v:0` and `0:a:0?` only. Additional audio/subtitle/data streams are dropped.
- If no video encode: `-c:v copy`.
- If video encode: H.264 encoder, `-pix_fmt yuv420p`, `-b:v <target>M`, `-maxrate <target+2>M`, `-bufsize <target*2>M`; software `libx264` adds `-preset veryfast`.
- Audio: either `-c:a copy` or AAC 48 kHz stereo 192 kbps.
- `-fps_mode cfr` for VFR fixes; scale filter with `force_original_aspect_ratio=decrease:force_divisible_by=2`.
- `-map_metadata 0`; user extra args inserted before the output path.

### 14.3 Encoder attempts

For a video encode, it lists available H.264 encoders (`h264_nvenc`, `h264_amf`, `h264_qsv`, `libx264`) and tries:

```
(d3d11va, encoder) for each encoder
then
(None, encoder) for each encoder
```

First successful output wins. Each failure deletes the partial temp and logs the next attempt. If all fail, raises `PatchError` with the last stderr tail.

### 14.4 Ownership and cleanup

- Output temp: `<stem>.preflight-<pid>-<token><ext>` beside the source.
- A JSON ownership marker `.<temp>.preflight-owner.json` is created with `O_EXCL`; includes tool name, hostname, PID, source, temp name.
- Stale cleanup only deletes temps with a valid marker, from the same host, older than 24 h, not modified in the last 60 s, and with a dead PID after a 60 s grace period. Files without a marker are never touched.
- The marker stays until the caller deletes the temp, so a hard kill is recoverable at next startup.
- A single global semaphore serialises preflight encodes; it is released before the caller patches the returned temp.
- On cancellation/error, the partial temp and marker are removed.

### 14.5 HDR guard

`patcher.py` refuses a VFR/codec/resolution re-encode of PQ/HLG source because it would silently produce 8-bit SDR. A bitrate-only cap is allowed to proceed. The guard uses `color_transfer` only (`smpte2084`, `arib-std-b67`), not BT.2020 primaries or `colr` boxes.

---

## 15. Platform profiles and readiness scoring

`core/platform_profiles.py` is deliberately pure, offline and read-only.

### 15.1 Profiles

| Profile | Codecs | Geometry | FPS | Duration | Audio | Bitrate warning |
|---|---|---|---|---|---|---|
| `generic` | common MP4 codecs | not checked | not checked | not checked | AAC 48 kHz stereo recommended | none |
| `tiktok` | H.264/H.265/VP8/VP9 | 360–4096 px; 9:16 recommended | 23–60 | 10 min API limit | AAC 48 kHz stereo | 20 Mbps heuristic |
| `instagram` | H.264/H.265/VP9/AV1 | 1.91:1 to 9:16; 9:16 recommended; 1920 px | min 30, max 60 | 180 s | AAC 48 kHz stereo | 25 Mbps heuristic |
| `youtube` | H.264/H.265/VP9/AV1 | square/vertical; max short side 1080 | 24–60 | 180 s | AAC-LC 48 kHz stereo | none (no required limit) |

Each profile carries source URLs and evidence labels (`documented`, `recommended`, `heuristic`). The documentation correctly says these are local heuristics, not platform ingest guarantees.

### 15.2 Checks

`evaluate_readiness(info, profile_id)` builds:

- container (MP4/MOV; MOV is a recommendation warning for platform profiles that prefer MP4);
- video codec (blocker if unsupported, recommendation if accepted but not preferred);
- frame geometry (blocker/warning depending on severity; aspect ratio; vertical recommendation; short-side cap);
- frame rate (range, preferred minimum, VFR warning);
- duration (warning over platform window);
- file size (TikTok 4 GiB documented blocker);
- audio (AAC-LC, sample rate, channels; unknown fields cap severity);
- bitrate (per-profile heuristic threshold, or unknown);
- HDR/color (explicit HDR/BT.2020 warning; unknown if tags missing).

### 15.3 Score

```
start at 100
blocker error        −40
warning             −12
recommendation      −3
critical unknown    no penalty, score cap 70
optional unknown    no penalty, score cap 95

blocker present      score cap 40
score ≤ 49           status = issues
any blocker          status = issues
warning / critical unknown / score < 85 → review
otherwise            ready
```

`REMEDIABLE_CHECK_IDS` = `audio`, `bitrate`, `frame_rate`, `video_codec`, `frame_geometry`; these are the checks the opt-in preflight can repair. Duration, file size, container and HDR need trim/split/remux/tone-map and are not auto-remediated.

### 15.4 UI/CLI

- Queue rows show a readiness badge with tooltip; clicking logs the full check list.
- The inspector has a global profile selector; queue items can override the profile.
- `fps-patcher-studio --cli score FILE --profile tiktok [--json]` exposes the same report.
- Multi-platform export creates one output per selected profile.

---

## 16. Settings and persistence

`config.py`:

- App data: `%APPDATA%\FPSPatcherStudio` on Windows (`~/Library/Application Support` on macOS, `$XDG_CONFIG_HOME`/`~/.config` elsewhere).
- `settings.json` is loaded with field filtering, type validation and clamping. New installs get `Crimson Gamer`, opaque window and `qt_v090_migrated=True` without writing a file until save.
- Pre-v0.9 settings are migrated once: an old Obsidian theme or translucent window is replaced by the current default and `window_alpha=1.0`.
- `save()` clamps first, serialises only `init=True` fields, writes a PID/thread-unique temp and `replace()`s atomically. `save_async()` uses a daemon thread and a process-wide save lock.
- Strategy names are migrated through `migrate_strategy_name()`; the transient `migrated_strategy_from` is logged by the controller and not persisted.
- Filename templates support `{name}`, `{fps}`, `{timescale}`, `{date}`, `{platform}`, `{strategy}`; invalid path characters are replaced with `_`.
- Multi-platform template helper appends `_{platform}` when needed.

Key defaults:

| Setting | Default |
|---|---|
| `last_preset` | `60 FPS` (60,000) |
| `custom_timescale` | 90,000 |
| `strategy` | `tiktok-ts` (X1T/BXD keys still accepted) |
| `platform_profile` | `generic` |
| `export_platforms` | `[]` |
| `overwrite` | false |
| `auto_rename` | true |
| `backup_original` | true |
| `preserve_mtime` | true |
| `verify_after` | true |
| `auto_normalize_audio` | true (GUI), false (PatchRequest/CLI default) |
| `auto_cap_bitrate` | false |
| `auto_fix_vfr` / `auto_fix_codec` / `auto_cap_resolution` | false |
| `bitrate_target_mbps` | 16 |
| `bxd_padding_bytes` | 0 (automatic) |
| `bxd_max_tail_ms` | 50 |
| `check_updates_on_start` | false |
| `watch_folder_enabled` | false |
| `tray_enabled` | true |
| `start_with_windows` | false |
| `language` | `en` |

Other persistence:

- `queue.json`: paths, selection and per-item overrides; missing files are pruned on load. Written directly (not atomically).
- `job_history.json`: newest-first, max 200 records, atomic temp+replace, thread lock only.
- `fps_patcher.log`: 1 MB × 3 rotating file log.
- Diagnostic logs: `%APPDATA%\FPSPatcherStudio\logs`, 5 MB total budget, 20-file rotation, path/username masking.

---

## 17. Job history, backups and undo

`core/job_history.py`:

- `JobRecord`: `job_id` (UUID hex), local ISO timestamp with offset, source, output, backup, timescale, strategy, platform profile, `rolled_back`.
- `record_job()` inserts at the front under a thread lock and truncates to 200. A history write failure is logged and ignored so a successful patch is never reported as failed.
- `undo_job(job_id=None)`: selects the given job or the newest non-rolled-back job; refuses if already rolled back or no `.bak`; checks the backup exists; acquires the same destination lock; `os.replace(backup, output)`; marks the record rolled back.
- Because undo **moves** the backup, the `.bak` is consumed. A second undo of the same job is refused.
- History is not cross-process locked; two instances can lose each other's records.

Backups are created by `patcher.backup_existing_output()` before replacing an existing output:

- tries `<name>.bak`, then `<name>.1.bak` … `<name>.9999.bak`;
- opens the candidate with exclusive create (`xb`) so an existing user file is never overwritten;
- copies bytes and metadata;
- aborts the patch if no backup can be created.

---

## 18. Application orchestration

`app/controller.py::AppController` owns all mutable runtime state.

- **Events:** `queue.Queue[Event]`; `emit()` also mirrors log events to the Python logger. `drain()` is main-thread-only and updates `current`, `_worker` and `ffmpeg` before forwarding.
- **Probing:** `load_files()` validates paths and probes only the first file for the inspector; `add_files()` appends and probes every new file on a background thread, updating `QueueItem.info` and emitting `QueueChangedEvent`.
- **Patching:** `start_patch(timescale, strategy, overwrite, auto_rename, only_selected, only_paths)`:
  - builds a snapshot of source paths (selected only, or all non-done);
  - resets their status;
  - creates a `ThreadPoolExecutor(max_workers=2)`;
  - submits sources; `stop_on_error` drops parallelism to one in-flight source;
  - each worker resolves per-item overrides (`timescale`, `strategy`, `platform_profile`);
  - if the item has a profile, one target; otherwise if global `export_platforms` has more than one, fan out; otherwise one global profile;
  - builds a `PatchRequest` per target with the current settings;
  - coalesces progress monotonically under a lock;
  - collects results/failures under a state lock;
  - marks the item done/failed;
  - emits `PatchDoneEvent` with the last result, all results, failures, total and cancellation state.
- **Cancellation:** sets a shared `threading.Event`; patchers check it at preflight, before writing and at engine checkpoints. The FFmpeg runner terminates the child job and force-kills the tree after a 5 s grace period or on a second Ctrl+C.
- **FFmpeg download:** only if `FPS_PATCHER_ALLOW_NETWORK=1`; background thread; progress events throttled to percent/stage changes; re-locates after install.
- **Updates:** only if network is enabled and `check_updates_on_start`; background thread; update download is cancellable; update install is deferred while patching.
- **Repair:** `repair_file_for_mobile()` selects `<stem>_mobile_repaired<ext>`, avoids overwrite unless allowed, calls the repair engine, writes diagnostics, returns the path or `None`.
- **Undo:** refuses while `busy`.
- **Shutdown:** cancels, joins the patch worker up to 5 s, then drops queued futures and never blocks process exit.

### 18.1 Queue model

`InputQueue` is the single source of truth. The Qt model holds item references and resets when the queue changes. Rules:

- append never replaces;
- duplicates are detected by resolved path;
- only supported extensions are accepted;
- selection and per-item overrides live in the queue model;
- late probe results do not resurrect a `done` item;
- `snapshot_for_run()` returns copies so workers do not mutate live rows;
- `reset_for_run()` clears status/error/progress/output;
- `save/load` persists only paths, selection and overrides, not transient status;
- legacy strategy overrides are migrated to `bxd-*` keys.

### 18.2 Folder watcher

`app/watcher.py::FolderWatcher` is stdlib-only:

- polls every 1 s by default;
- a file is ready after `settle_scans=2` stable scans, older than `min_age_s=1.0`, and not exclusively locked (Windows `O_RDWR` probe);
- files already present when watching starts are primed and ignored, so pointing at an old export folder does not patch its backlog;
- own outputs are filtered by recorded path, `_ts<digits>` / `_<template>fps` regexes, hidden/temp names and `.preflight`/`.colr` markers;
- callback runs on the watcher thread and must be quick; the Qt UI pushes into a `queue.Queue` and drains it on the main thread;
- `stop(wait=False)` never blocks on a scan; it waits only for an in-flight callback under a lock;
- state for vanished files is pruned to keep long-running watchers bounded.

### 18.3 Quick patch, Explorer and startup

- `app/quick_patch.py` builds a `PatchRequest` from settings, runs `patch()` with a no-op emitter, shows a toast, prints the output and returns 0/1. It is used by `--quick-patch` and the Explorer verb.
- `app/shell_integration.py` registers `HKCU\Software\Classes\SystemFileAssociations\{.mp4,.mov,.m4v}\shell\FPSPatcherStudio` with the command `"<exe>" --quick-patch "%1"`. No admin rights. Uninstall deletes command then verb; missing keys are ignored.
- `app/startup.py` uses `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` value `FPSPatcherStudio`, command `"<exe>" --startup` (source mode uses `pythonw -m fps_patcher --startup`). Enabling/disabling is idempotent; failures return false and the UI warns.

---

## 19. Qt UI

The UI is PySide6 only. `src/fps_patcher/ui/` contains only strings and assets; there is no Tk code.

### 19.1 Shell

`MainWindow` (`ui_qt/main_window.py`):

- creates `AppController`, `ThemeManager`, `MotionController`, `ControllerBridge`;
- builds a toolbar (brand, title, version badge, FFmpeg status button, Forensic, History, Open output, Update, theme toggle, Settings);
- body split: `QueueView` + fixed-width `Inspector`;
- bottom `ConsolePanel`;
- shortcuts: `Ctrl+,` settings, `Ctrl+A` select all, `Delete` remove selected, `Ctrl+O` browse, `Enter` start patch;
- loads `queue.json`, restores geometry from `QSettings("FPSPatcherStudio", "QtUI")`;
- initialises FFmpeg on a background thread, syncs watcher/Explorer/startup, cleans stale preflight temps, starts optional update check;
- tray: closing hides instead of quitting while patching/watch folder continues; tray menu Show/Quit; first close shows a notification;
- on real close: stops motion/bridge/watch timer, stops watcher, shuts down controller, saves geometry/settings/queue.

### 19.2 Event bridge

`ControllerBridge` polls the controller queue and re-emits typed Qt signals (`log`, `progress`, `probe_done`, `patch_done`, `queue_changed`, `ffmpeg`, `update_available`, `update_download`, `drained`, forensic signals).

MainWindow buffers logs and progress until `drained`, then flushes in one batch, avoiding a repaint per line.

### 19.3 Queue view

`QueueView` + `QueueModel` + `QueueDelegate`:

- custom-painted 56 px rows with thumbnail, filename, metadata, status/readiness pills, selection checkbox and hover actions;
- native drag-and-drop with a rich empty-state `DropCard` (breathing animation, drag-active scale);
- folder import;
- selection, select-all, clear selection, remove, move up/down, context menu, open file/preview, per-row readiness tooltip, per-row profile badge;
- thumbnails generated off-thread by `ThumbnailLoader`/`request_thumbnail` (Pillow + optional ffmpeg) and delivered as PNG bytes; in-memory 128-entry cache and temp disk cache;
- refresh is model-reset based so a 500-row queue stays cheap;
- theme-aware painting, motion reduction support, accessible names.

### 19.4 Inspector

`Inspector`:

- 60/120/Custom target FPS segmented control; custom FPS validated and stored as a timescale;
- output folder, effective timescale, source/estimated bitrate, strategy combo, platform profile combo;
- PC warning label;
- readiness summary and info button;
- progress bar/caption and Start/Cancel buttons;
- VFR safety banner with “Use lossless” action that disables the VFR fix;
- per-item override card (enable switch, FPS, preset, profile, Apply/Clear), only shown when a row is selected;
- busy/can-patch state; accessibility names.

### 19.5 Settings

`SettingsDialog` is a modal draft/apply dialog with a left rail and four main pages (General, Output, Appearance, System) plus a lazy search page and collapsed Advanced sections. It covers:

- target preset/custom timescale, strategy, platform profile;
- output folder, filename template toggle, open-when-done, preserve mtime, backup, overwrite/auto-rename, confirmations, stop-on-error;
- preflight toggles and bitrate target, V4 controls, BXD padding/tail, color/metadata, diagnostics masking, extra FFmpeg args;
- theme preset, accent, tint, backdrop (Acrylic/Mica/Aero/Solid), UI scale, font size, radius, density, reduce motion, language;
- tray, startup, always-on-top, notifications, log options, watch folder, Explorer menu, FFmpeg folder, check updates, export platforms.

Applying copies all `init=True` fields back to the live `Settings`, re-applies theme, tray, startup, watcher, Explorer menu, FFmpeg, profile strip and readiness. Settings are saved asynchronously.

### 19.6 Other dialogs

- **ConsolePanel:** collapsible 36 px summary → 180 px log; timestamped, color-coded levels, ffmpeg-output filtering, save-log, “repair for mobile” action, context files.
- **ForensicDialog:** original/patched pickers; atom-tree analysis; track/sample/color/drift/payload report; compare/diff; repair; JSON export; markdown report; diagnostic log. Uses worker threads and signals.
- **HistoryDialog:** recent jobs, output/backup/strategy/profile, rollback action; invokes `AppController.undo_job`.
- **UpdateDialog:** release notes, version/install mode, progress, Update now/Skip/Cancel.
- **Theme/theme manager:** seven presets (`Crimson Gamer`, `Graphite`, `Midnight Violet`, `Emerald Terminal`, `Obsidian`, `Amber Warm`, `Light`), generated QSS palette, density/radius/font tokens, Windows DWM title-bar/backdrop helpers, light/dark switching.
- **Motion:** easing/fade/slide/height animations, `MotionProgressBar`, reduced-motion support.
- **Widgets:** `Card`, `InsetRow`, `CardGroup`, `CollapsibleSection`, `SettingRow`, `ConsequenceBadge`, `ElidedLabel`, `WrapLabel`, `SegmentedControl`, `Switch`, `Popover`.
- **i18n:** `ui/strings.py` is a 895-line English/Thai dictionary with `t()` formatting and readiness label helpers. Language switching retranslates live widgets.

---

## 20. CLI

`src/fps_patcher/cli.py` is a self-contained argparse app. Commands:

| Command | Purpose |
|---|---|
| `patch INPUT...` | Patch one or more files. |
| `probe INPUT` | Print metadata. |
| `score INPUT --profile P` | Print readiness score/checks. |
| `history [--limit N]` | List recent jobs. |
| `undo [JOB_ID] [--last]` | Restore a backup. |

`patch` options:

- `--preset 60|120`, `--timescale N`;
- `--strategy` (validated against the registry);
- `--template`, `--profile`, `--platforms`;
- `--output DIR`;
- `--normalize-audio`, `--cap-bitrate`, `--fix-vfr`, `--fix-codec`, `--cap-resolution`;
- `--tag-bt709`, `--scrub-metadata`;
- `--overwrite` XOR `--auto-rename`;
- `--json`.

Exit codes: `0` success, `1` file/patch error, `2` usage error, `130` cancelled.

Signal handling: first Ctrl+C sets the cancel event, second sets a force event and force-kills the FFmpeg process tree. The previous SIGINT handler is restored after the command.

Headless characteristics:

- no PySide6 import;
- `attach_console()` rebinds stdout/stderr in a frozen windowed build when launched from a console; a double-click launch has no console and stays silent;
- JSON output is machine-readable; human logs go to stderr.

CLI nuance: `auto_normalize_audio=bool(args.normalize_audio)` and `auto_cap_bitrate=bool(args.cap_bitrate)` ignore the corresponding `settings.json` values. The GUI defaults normalisation on; the CLI defaults it off unless the flag is passed. `fix_vfr`, `fix_codec` and `cap_resolution` do OR with settings. This asymmetry is documented in §24.

---

## 21. Network, updater and FFmpeg download

### 21.1 Network gate

`config.network_downloads_enabled()` returns true only when `FPS_PATCHER_ALLOW_NETWORK=1`. The controller checks it before:

- starting an FFmpeg download;
- starting a startup update check;
- starting an update download.

The UI hides the FFmpeg download action unless the gate is true. The README/PRIVACY docs describe the shipped build as network-disabled; the code path is still present and can be enabled by the environment variable. There is no telemetry, analytics, crash reporting or media upload.

### 21.2 Updater

`core/updater.py`:

- Latest release from `https://api.github.com/repos/x1Swimzft/FPS-Patcher-Studio/releases/latest`.
- Rejects drafts/prereleases; compares numeric versions (`v2.0.1` → `(2,0,1)`).
- Host allowlist: `api.github.com`, `github.com`, `objects.githubusercontent.com`, `release-assets.githubusercontent.com`; requires HTTPS.
- Asset choice: installed → Setup `.exe` first, then any `.exe`; portable → `-win64.zip` first, then any `.zip`.
- Looks for `<asset>.sha256`/`.sha256sum` and extracts the first 64-hex digest.
- Downloads to a `.part` file with progress/cancel, checks Content-Length, optional SHA-256, then renames.
- Installed: `launch_installer()` verifies Authenticode (unless `FPS_PATCHER_ALLOW_UNSIGNED_UPDATE=1`) and starts the installer detached with `/SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS`.
- Portable: extracts to `%TEMP%\FPSPatcherStudioUpdate\staging`, rejects path traversal and total extraction > 1 GiB, requires `FPSPatcherStudio.exe`, verifies Authenticode, writes a detached `cmd.exe` trampoline that waits for the current PID, `robocopy /MOVE`s staging into the app directory, relaunches, cleans up and deletes itself.
- Update install is deferred if a patch is running.

Operational mismatch: the current releases are **unsigned**, but `verify_authenticode()` rejects unsigned files unless the QA environment override is set. With network enabled, a user can download an update and then fail at installation. Signing or an explicit unsigned-update opt-in is required to make the default path work.

### 21.3 FFmpeg download

`core/ffmpeg_downloader.py`:

- Fixed URL: BtbN `ffmpeg-master-latest-win64-gpl.zip`.
- HTTPS only; default TLS context.
- Streams to `.ffmpeg-download.zip`; extracts only `*/bin/ffmpeg.exe` and `*/bin/ffprobe.exe` into a staging directory, with a fixed output name (no Zip Slip) and a 512 MiB per-member cap.
- Verifies both binaries by running `-version`, then atomically moves them into `%LOCALAPPDATA%\FPSPatcherStudio\bin`.
- Supports an optional `expected_sha256`, but the controller calls it **without** a hash. The download is therefore authenticated only by HTTPS/GitHub, not by a pinned digest. It also tracks the moving `latest` branch, so binary provenance is not reproducible.

`ffmpeg_locator.py` search order:

1. explicit settings directory;
2. bundled `_MEIPASS/bin` (frozen), `exe_dir/bin`, and project `bin/`;
3. `%LOCALAPPDATA%\FPSPatcherStudio\bin`;
4. system PATH (prefer ffprobe's directory, then ffmpeg).

Each candidate must run `-version` (10 s timeout) and both binaries must be present.

---

## 22. Build, packaging and release

### 22.1 PyInstaller

`build/fps_patcher.spec`:

- one-folder, windowed (`console=False`), no UPX (avoids AV heuristics);
- entry `src/fps_patcher/__main__.py`;
- data: `src/fps_patcher/ui/assets` → `fps_patcher/ui/assets`;
- binaries: every `bin/*.exe` → `bin`;
- excludes Tk, unittest/test, PySide6 WebEngine/Pdf/Qml/Quick/Multimedia/Charts/3D/Bluetooth/etc.;
- prunes Qt plugins to `platforms` (`qwindows`, `qoffscreen`, `qminimal`), `styles` (`qmodernwindowsstyle`, `qwindowsvistastyle`), `imageformats` (`gif`, `ico`, `jpeg`, `svg`, `tiff`, `webp`), and drops dependent QML/PDF/OpenGL/virtual-keyboard DLLs;
- version resource `build/version_info.txt` and manifest `build/fps_patcher.manifest`;
- icon `build/app.ico`.

The built `dist/FPSPatcherStudio` is ~123 MB zipped; bundled FFmpeg accounts for ~211 MB uncompressed, so the app is not a small utility.

### 22.2 Release script

`build/release.ps1`:

1. Reads `__version__`; enforces `build/version_info.txt` `'FileVersion', '<version>.0'`.
2. Quality gates unless `-SkipChecks`: `ruff`, `mypy src tests tools`, `pytest`.
3. PyInstaller via `uv run --with pyinstaller`.
4. Signing modes:
   - default: explicitly unsigned (avoids “invalid signature” AV flags);
   - `-Sign`: production Authenticode via `CERT_PFX_PATH`/`CERT_PASSWORD`;
   - `-SignDev`/`-GenerateSelfSigned`: local self-signed cert (untrusted).
5. Launch smoke test: start EXE, wait 6 s, require it still alive, then force kill.
6. Copy docs and write `READ_ME_FIRST.txt`.
7. Create `release/FPSPatcherStudio-v<version>-win64.zip`, SHA-256 sidecar.
8. Optional Inno Setup `Setup.exe` (per-user, `PrivilegesRequired=lowest`, `asInvoker` manifest, x64).
9. CycloneDX SBOM + dependency audit report via `tools/generate_sbom.py`; combined SHA-256 manifest; JSON manifest with commit, timestamp, tool versions, artifact hashes/signature status and SBOM path.

### 22.3 CI

- `.github/workflows/release.yml`: on tags `v*` or manual; installs uv/Python 3.11, `uv sync --frozen`, runs **pytest only**, optionally bundles FFmpeg from the same BtbN `latest` URL, generates SBOM, builds with `-SkipChecks`, uploads unsigned artifacts, optional SignPath submission, removes stale pre-signing checksums, uploads signed artifacts. It does **not** run ruff/mypy.
- `.github/workflows/security-audit.yml`: on main/PR/manual; `uv sync --all-groups --frozen`, `uv lock --check`, ruff, `mypy src tests tools`, pytest, SBOM, `pip-audit` via `uvx`, uploads artifacts. The mypy step currently fails (see §23).

### 22.4 Release artifacts present

`release/` contains v0.9.0, v1.0.0, v1.2.0, v2.0.0 and v2.0.1 artifacts. v2.0.1:

- zip 123,246,468 B, SHA-256 `c978ae0c…af66`;
- Setup 88,411,782 B, SHA-256 `e9db9d02…a8fb`;
- SBOM `FPSPatcherStudio-v2.0.1.cdx.json`;
- JSON manifest records unsigned, Python 3.11.18, PyInstaller 6.22.3, Inno 7.1.1, no signtool.

---

## 23. Test suite and quality-gate results (measured in this analysis)

### 23.1 Test inventory

- 56 `test_*.py` modules, 11,649 total test-tree lines.
- 556 `def test_` functions; pytest collects 635 cases due parametrisation.
- `tests/conftest.py`:
  - sets `QT_QPA_PLATFORM=offscreen` before Qt import;
  - raises Windows stdio limit to 2048;
  - forces `FPS_PATCHER_ALLOW_NETWORK=1` for all tests via an autouse fixture (so network-disabled behaviour must be tested explicitly);
  - processes deferred Qt deletes between tests;
  - orders Qt tests with motion first and main-window last to avoid offscreen timer teardown issues;
  - generates synthetic 2 s 320×240 clips with `testsrc`/`sine`, libx264/AAC, including 30 fps, 59.94 `.mov`, and no-audio variants.
- `tests/qt_support.py` isolates `%APPDATA%`, stubs update/startup/watcher/FFmpeg/theme side effects, and builds MainWindow cheaply.

Coverage is broad:

| Area | Representative modules |
|---|---|
| Atom/BXD/V4 engines | `test_atom_patcher`, `test_bxd_presets_and_repair`, `test_bxd_audio_verify`, `test_bxd_bypass`, `test_v4_forensic`, `test_core`, `test_fixture_matrix` |
| Verification/payload | `test_capability_and_verifier`, `test_bxd_audio_verify`, `test_fixture_matrix` |
| Preflight/parallel pipeline | `test_preflight_and_updater`, `test_preflight_cleanup`, `test_parallel_pipeline`, `test_remediation`, `test_remediation_wiring` |
| Platform profiles | `test_platform_profiles`, `test_template_and_profile`, `test_multi_platform` |
| CLI/settings/history | `test_cli`, `test_settings_v2`, `test_settings_wired`, `test_job_history` |
| App/queue/watcher | `test_app`, `test_queue_model`, `test_queue_selection_patch`, `test_watcher`, `test_watch_integration` |
| Automation | `test_shell_and_quick_patch`, `test_windows_startup`, `test_destination_lock` |
| UI (19 modules) | main window, settings, queue, inspector, console, forensic, history, update, theme, motion, typography, accessibility, drag-and-drop, multi-platform, overrides |
| Benchmark tooling | `test_tiktok_benchmark`, `test_ffmpeg_downloader`, `test_ffmpeg_lifecycle`, `test_packaging_and_manifest` |

`test_fixture_matrix` builds a matrix of synthetic layouts (moov-at-end/front, 64-bit/size-0 boxes, co64, multi-track, MOV/tmcd, etc.) and audits every output; `test_bxd_presets_and_repair` exercises all eight preset aliases and external FFmpeg decode checks; `test_all_four_bxd_presets_and_external_ffmpeg` asserts real-sample hashes and mdat hashes across every preset.

### 23.2 Actual gate results

Command and result:

```text
uv run pytest -q
635 passed in 39.23s

uv run ruff check src tests tools
All checks passed!

uv run mypy src
Success: no issues found in 53 source files

uv run mypy src tests tools
tests\test_windows_startup.py:43: error: Module "fps_patcher.app.startup" does not explicitly export attribute "os"  [attr-defined]
tests\test_ui_qt_settings.py:110: error: Item "None" of "QLabel | None" has no attribute "isVisible"  [union-attr]
tests\test_ui_qt_settings.py:113: error: Item "None" of "QLabel | None" has no attribute "isVisible"  [union-attr]
tests\test_ui_qt_main_window.py:243: error: "QCoreApplication" has no attribute "quitOnLastWindowClosed"  [attr-defined]
tests\test_ui_qt_main_window.py:257: error: "QCoreApplication" has no attribute "quitOnLastWindowClosed"  [attr-defined]
tests\test_ui_qt_main_window.py:272: error: Item "QCoreApplication" of "QCoreApplication | None" has no attribute "quitOnLastWindowClosed"  [union-attr]
tests\test_ui_qt_main_window.py:272: error: Item "None" of "QCoreApplication | None" has no attribute "quitOnLastWindowClosed"  [union-attr]

Found 7 errors in 3 files (checked 117 source files)
```

Consequences:

- `README.md` tells contributors to run `uv run mypy src tests tools` — that command is currently red.
- `build/release.ps1` runs the same command in its default gate — a normal release build aborts unless `-SkipChecks` is used.
- `.github/workflows/security-audit.yml` runs the same command — the security-audit job is red on the current tree.
- `.github/workflows/release.yml` does **not** run mypy and invokes `release.ps1 -SkipChecks`, so tagged CI builds can still publish despite the red gate. The pipelines disagree about the quality bar.

CHANGELOG 2.0.1 claims “593 tests, ruff and mypy clean”; the measured suite is 635 tests and full-tree mypy has 7 errors. The source-only mypy check (`mypy src`) is clean.

No coverage tool or threshold is configured in `pyproject.toml`. There is no fuzzing campaign, no sanitizer run, no real iOS/Android playback test, and no manual QA evidence in the tree. `reports/tiktok_benchmark/README.md` says its presets are “untested”; `CHANGELOG` 2.0.0/2.0.1 say manual Windows QA is pending.

---

## 24. Empirical media experiment

### 24.1 Fixture

Using the bundled `bin/ffmpeg.exe`:

```
2.0 s, 320×240, 30 fps H.264 (libx264, yuv420p), AAC 48 kHz stereo
source size: 105,446 bytes
layout: ftyp(32) / free(8) / mdat(101,907) / moov(3,499)
video: timescale 15,360; duration 30,720; 60 samples × 512 ticks
audio: timescale 48,000; duration 97,280; 95 samples × 1,024 ticks
movie: timescale 48,000; duration 96,000
video edts: segment 96,000, media_time 1,024
audio edts: segment 96,000, media_time 1,024
```

Reproduction sketch:

```powershell
# source clip
bin\ffmpeg.exe -hide_banner -y -f lavfi -i "testsrc=size=320x240:rate=30:duration=2" `
  -f lavfi -i "sine=frequency=440:duration=2" -c:v libx264 -preset ultrafast `
  -pix_fmt yuv420p -c:a aac -shortest re_test.mp4

# one engine/preset per output directory (repeat for each strategy)
uv run fps-patcher-studio --cli patch re_test.mp4 --preset 60 `
  --strategy bxd-mobile --output re_out

# repair the PC output
uv run python -c "from pathlib import Path; from fps_patcher.core.bxd_patcher import repair_for_mobile; repair_for_mobile(Path('bxd-pc.mp4'), Path('bxd-pc-repaired.mp4'), emit=print)"
```

The clip was patched with target timescale 60,000 through each engine and preset. Outputs were inspected with `MP4ForensicAnalyzer`, `verify_*`, and direct `struct` reads.

### 24.2 Results

| Engine/preset | Size (B) | Top-level layout | Video | Audio | Padding/ghost | Structure | Mobile check | Real payload |
|---|---:|---|---|---|---|---|---|---|
| Source | 105,446 | `ftyp/free/mdat/moov` | 15,360; 60×512 | 95×1,024; edts 1,024 | none | VALID, not faststart | OK (warning) | baseline |
| V3 `direct-atom` | 105,446 | `ftyp/free/moov/mdat` | 60,000; 60×2,000; edts mt 4,000 | unchanged | none | VALID, faststart | OK | identical |
| V4 `v4-forensic` | 105,446 | `ftyp/free/mdat/moov` | 60,000; 60×2,000; edts mt 4,000 | unchanged | none | VALID, not faststart | OK (warning) | identical |
| `ffmpeg-copy` | 105,446 | `ftyp/moov/free/mdat` | 60,000; 60×2,000; edts 768,000 | unchanged | none | VALID, faststart | OK | identical |
| **X1T PC** | **115,662** | `ftyp/moov/mdat` + trailing | 60,000; 60×2,000; edts stripped | 950 samples; stts `95×1024 + 855×1`; mdhd still 97,280 | **6,840 trailing ghost bytes** | **EXPERIMENTAL**, offsets outside mdat | **Non-standard** | real samples identical; audio ghost flagged |
| **X1T Mobile** | **109,554** | `ftyp/moov/mdat/free(4,104)` | 60,000; 60×2,000; edts mt 4,000 | 95×1,024; edts kept | 4,096 B free payload | VALID, faststart | OK (warning) | identical |
| **X1T Hybrid** | **109,562** | `ftyp/moov/mdat/free(4,104)` | 60,000; **123,000**; last delta 5,000; tkhd 98,400; edts 98,400 | unchanged | 4,096 B free payload | VALID, faststart | OK (warning) | identical |
| **X1T Clean** | **105,450** | `ftyp/moov/mdat` | 60,000; 60×2,000; edts mt 4,000 | unchanged | none | VALID, faststart | OK (warning) | identical |
| PC → repair | 105,414 | `ftyp/moov/mdat` | 60,000; 60×2,000; edts segment 92,800, mt 4,000 | 95×1,024; audio edts removed | none | VALID, faststart | OK (no warning) | identical real samples |

Key observations:

- **All engines preserve the real media payload.** In this experiment the source mdat SHA-256 is unchanged in every output and video sample hashes match. This is the strongest correctness property of the tool.
- **X1T always forces `mvhd` v1 duration `-1`.** In the PC output, `mvhd` is 120 bytes (v1) with `0xFFFFFFFFFFFFFFFF`; Mobile/Hybrid/Clean likewise.
- **PC's audio inconsistency is real.** 855 ghost samples are appended, audio `stsz` becomes 950, `stts` sum becomes 98,135, but audio `mdhd.duration` remains 97,280. `verify_sample_tables` passes because counts match; `verify_mobile_compatibility` reports the duration mismatch and the ghost signature. This is expected by design but means PC is not merely “non-faststart”; its audio timeline is internally inconsistent.
- **Mobile/Hybrid/Clean are structurally valid and faststart.** The `free` box total is 4,104 B (4,096 payload + 8 header); Clean has no free box. Mobile is 4,104 B larger than Clean because it adds that free box. Clean is 4 B larger than the source because its moov grows from 3,499 B to 3,511 B (+12) while the source's 8-byte `free` box is dropped (−8).
- **Hybrid adds exactly 50 ms** at 60,000: last video delta 2,000 → 5,000 (+3,000 ticks), video duration 120,000 → 123,000, video tkhd/elst 96,000 → 98,400 (movie timescale 48,000). The movie duration remains `-1`.
- **V3 and V4 both preserve the source `mvhd`** (48,000/96,000) and audio. V3 adds faststart and keeps the source `free` box; V4 keeps the source order and is not faststart.
- **`ffmpeg-copy` is not layout-equivalent to the direct engines.** In this fixture it rewrote the movie timescale to 384,000 and edit durations to 768,000, while video mdhd is 60,000. It is valid and faststart, but it changes more than the requested timescale. This is a reason the project prefers direct patching.
- **Repair removes the PC artifacts.** It strips 855 ghost samples and 6,840 trailing bytes, reconstructs the video edit list from the first `ctts` offset, sets `mvhd` to 97,280 and produces a mobile-compatible file. Audio edit-list/priming information is lost (the code emits a note).
- **Archive output is not byte-identical to Clean.** Repair is 105,414 B vs Clean 105,450 B because the audio `edts` is gone and the video edit list is reconstructed.

### 24.3 Caveats

- This is a 2 s, 320×240, 30 fps synthetic clip. It proves container mechanics, not platform behaviour, not playback on real phones, and not high-bitrate/long-GOP edge cases.
- The PC output is intentionally non-standard; a structural “EXPERIMENTAL” result is the correct outcome, not a test failure.
- The `ffmpeg-copy` movie-timescale rewrite is a muxer behaviour, not an app bug, but it illustrates why `ffmpeg-copy` should be considered a different tool from direct patch.
- No VMAF/SSIM/PSNR measurement was performed here; because mdat is unchanged, those metrics are identity unless preflight re-encoded.
- The repair result depends on `ctts`/`stts`/`stco` correctness; no real-device playback was tested.

---

## 25. Correctness, security and operational risk register

Severity is a practical assessment for a Windows desktop media utility, not a formal CVSS score.

### High

1. **Payload `FAIL` does not block publishing.**
   - Evidence: `patcher.py` computes `verify_payload_integrity()` and logs each status, but only sets `experimental` for `EXPERIMENTAL`; it never raises on `FAIL` before `os.replace`.
   - Impact: a corrupt or partially mismatched output from `ffmpeg-copy`/V3 (or a future engine bug) can replace the destination and be recorded as a successful job. BXD/V4/repair have internal hard aborts, but the outer safety net does not.
   - Recommendation: treat any `FAIL` as fatal (or require an explicit `allow_failed_verification` override), and keep the temp file for inspection rather than deleting it on failure.

2. **HDR guard can be bypassed by combining a bitrate cap with VFR/codec/resolution fixes.**
   - Evidence: `patcher.py` aborts only when `plan.needs_video_encode and not plan.cap_bitrate and transfer in (PQ, HLG)`. If `cap_bitrate` is true and `fix_vfr`/`fix_codec`/`cap_resolution` is also true, the plan needs a video encode but the guard is skipped.
   - Impact: PQ/HLG source is encoded to 8-bit `yuv420p` without tone-mapping; HDR is silently destroyed.
   - Recommendation: guard on any planned video re-encode of HDR, regardless of the cap flag; reserve the existing “bitrate-only cap allowed” exception explicitly.

3. **Full-file memory use in the default engines can exhaust RAM on large media.**
   - Evidence: `bxd_patcher.py` `src.read_bytes()`; `atom_patcher.py` `src.read_bytes()` + `bytearray`; `v4_patcher.py` `src.read_bytes()` + `bytearray`. `V4.max_file_size` exists but `patcher.py` never passes it. `compare_mp4_files()` also reads both files fully.
   - Impact: a 4 GB TikTok-limit file can require roughly 4–8 GB per job before output buffering; two patch workers can exceed typical desktop RAM. This is a realistic failure mode, not a theoretical one.
   - Recommendation: mmap/stream parsing, cap input size for full-memory engines, run heavy jobs one at a time, and wire `max_file_size` into the request/settings.

### Medium

4. **PC preset is intentionally non-standard and can fail mobile playback.**
   - Evidence: ghost samples after `mdat`, `stco` outside every mdat, audio `stts`/`mdhd` mismatch, `mvhd=-1`. The verifier labels it `EXPERIMENTAL / NON-STANDARD` and mobile check fails.
   - Impact: users who pick “For PC” for a phone upload can get a file that desktop players open but mobile decoders reject. The UI warning exists, but the preset is still selectable and legacy aliases map to it.
   - Recommendation: keep it labelled legacy/desktop-only; consider hiding it from the main preset list or requiring a confirmation.

5. **`indeterminate_mvhd` constructor argument is dead; H1–H4 isolation is not single-variable.**
   - Evidence: `MethodBXDDirectPatch.__init__` unconditionally sets `self.indeterminate_mvhd = True`, ignoring the argument. `generate_isolation_variants()` passes `False` for H1/H3/H4, but all outputs get `-1`.
   - Impact: the hypothesis generator cannot isolate `mvhd` from ghost/padding/edts effects; conclusions from H1–H4 are confounded. The test only asserts H1's `-1`, so it does not catch this.
   - Recommendation: assign the parameter, add tests that read `mvhd.duration` for all four variants, and regenerate any hypothesis results.

6. **The default auto-update path is incompatible with unsigned releases.**
   - Evidence: `verify_authenticode()` rejects unsigned installers/portable EXEs unless `FPS_PATCHER_ALLOW_UNSIGNED_UPDATE=1`; the current release is unsigned and `release.ps1` defaults to unsigned. The network gate is off by default, but enabling it exposes the mismatch.
   - Impact: a user who enables updates can download successfully and then fail at install, with a security error that looks like tampering.
   - Recommendation: sign releases before enabling update install by default, or present an explicit “unsigned build” opt-in that is separate from the QA environment variable.

7. **FFmpeg auto-download has no pinned checksum and tracks a moving `latest` build.**
   - Evidence: `download_ffmpeg()` accepts `expected_sha256` but the controller calls it without one; the URL is `.../releases/download/latest/ffmpeg-master-latest-win64-gpl.zip`; no version pin.
   - Impact: supply-chain and reproducibility risk; two builds can contain different FFmpeg binaries. HTTPS/GitHub is the only integrity control.
   - Recommendation: pin a version and SHA-256 in code, or bundle the already-verified binaries into the release and disable the downloader.

8. **The documented/CI mypy gate is red.**
   - Evidence: 7 strict-mode errors in 3 test files; `release.ps1` and `security-audit.yml` run `mypy src tests tools`; `release.yml` skips it.
   - Impact: local release builds abort by default; the security-audit workflow fails; the project’s advertised “ruff and mypy clean” claim is false on this tree. Release CI can still ship because it bypasses checks.
   - Recommendation: fix the test types (or add targeted ignores), or make all pipelines consistently gate on `mypy src` plus a separate test-type policy.

9. **CLI preflight flags do not follow settings.**
   - Evidence: `auto_normalize_audio=bool(args.normalize_audio)`, `auto_cap_bitrate=bool(args.cap_bitrate)`; GUI defaults normalisation on, CLI defaults it off. `fix_vfr`/`fix_codec`/`cap_resolution` OR with settings.
   - Impact: identical settings produce different audio/bitrate behaviour between GUI, CLI and quick patch; a user who relies on “normalize audio” globally gets non-normalized audio from CLI unless they remember the flag.
   - Recommendation: inherit settings and add `--no-normalize-audio`/`--no-cap-bitrate` explicit overrides.

10. **Preflight drops all but the first audio stream and all non-A/V streams.**
    - Evidence: `build_preflight_args()` maps `0:v:0` and `0:a:0?` only.
    - Impact: multi-audio, subtitles, chapters and data tracks disappear whenever audio normalisation or any video preflight fix runs. `verify()` compares against the preflight copy, so it does not flag the loss relative to the original.
    - Recommendation: map all streams and copy the ones not being transformed, or explicitly warn/reject multi-stream inputs before preflight.

11. **BXD drops top-level boxes other than the first `ftyp`/`moov`/`mdat`.**
    - Evidence: `execute()` selects the first of each and writes only `ftyp + moov + mdat (+ free/ghost)`.
    - Impact: `uuid`, `sidx`, `udta`, second `mdat` and other top-level metadata are lost. Conventional files are fine; unusual or multi-`mdat` files are silently simplified.
    - Recommendation: preserve/relocate safe top-level boxes, or reject layouts the engine cannot represent.

12. **`verify_mobile_compatibility()` treats an indeterminate `mvhd` as “defined”.**
    - Evidence: it sets `mvhd_duration_defined = True` for `0xFFFFFFFF`/`0xFFFFFFFFFFFFFFFF` and only appends a warning; tests assert this.
    - Impact: “Structure OK (likely mobile-compatible)” can be reported for files with unknown movie duration. This is intentional for X1T, but the label overstates duration completeness.
    - Recommendation: keep structural compatibility separate from duration-defined status; do not use a single “mobile-compatible” label for both.

13. **`bxd_max_tail_ms` clamp and documentation disagree.**
    - Evidence: `config.py` comments “provisional ceiling (ms, <=200ms)” but clamps to 5,000; `bxd_patcher.py` also clamps 5,000. Default 50.
    - Impact: a user can add up to 5 s to the last video sample, creating a large A/V end-time mismatch. `verify()` tolerance grows to 5.1 s for Hybrid, so it may not flag.
    - Recommendation: align the documented and actual ceiling, cap the UI, and warn above 200 ms.

### Low / robustness

14. **`_build_indeterminate_mvhd()` version-1 tail is misaligned by 4 bytes.**
    - Evidence: it reads a version-1 `mvhd` from raw atom data but uses `tail = data[36:]`; the correct payload tail starts at byte 40 (8 header + 4 vflags + 8 creation + 8 modification + 4 timescale + 8 duration). Version-0 sources use the correct `data[28:]`.
    - Impact: source files with a version-1 `mvhd` (large durations) get a 4-byte-too-long `mvhd`, shifting matrix/predefined/next-track fields. Version-0 files are unaffected. No test covers a v1 `mvhd` X1T patch.
    - Recommendation: use `data[40:]`, add a synthetic v1 `mvhd` fixture, and validate the full `mvhd` tail.

15. **Size-0 `mdat` headers are copied verbatim when appending `free`/ghost data.**
    - Evidence: BXD reads the original `mdat` header and writes it unchanged; `size=0` means “to EOF”. Appended padding then becomes part of `mdat`, and the `free`/ghost layout is no longer what the offset math assumes.
    - Impact: rare but valid streaming-style files get a different box layout; PC ghost samples may end up inside `mdat` rather than outside, and `free` may be swallowed.
    - Recommendation: rewrite a size-0 `mdat` header to its actual size before appending data, and add a fixture.

16. **BXD audio-table parsing uses raw `bytes.find()` rather than a box tree.**
    - Evidence: `_parse_audio_table()` searches for `soun`, `stbl`, `stsz`, `stts`, `stsc`, `stco`/`co64` inside the track bytes; `_extract_video_sample_count()` similarly searches `stsz`.
    - Impact: a string matching a box name inside payload data could select the wrong offset on malformed or unusual files. Conventional files are fine; hostile inputs can cause wrong values or exceptions.
    - Recommendation: reuse the box-tree parser and validate bounds before `struct.unpack_from`.

17. **`atom_patcher._patch_stts()` expands every sample delta into a Python list.**
    - Evidence: it extends a list per sample, with `max_samples = len(data)` as the only cap. A 4 GB file can still produce a multi-million-element list.
    - Impact: time and memory blow-up on long/hostile `stts` tables; a malformed file can cause a large allocation before failing.
    - Recommendation: scale run-by-run with remainder carry, or cap sample counts more tightly and stream.

18. **Queue persistence is not atomic.**
    - Evidence: `InputQueue.save()` calls `target_path.write_text(...)` directly; settings and job history use temp+replace, but queue.json does not.
    - Impact: a crash during queue save can leave invalid JSON; the loader returns an empty queue.
    - Recommendation: reuse the atomic-write pattern.

19. **Job history and settings are not cross-process locked.**
    - Evidence: `_HISTORY_LOCK` and `_SAVE_LOCK` are `threading.Lock`; CHANGELOG explicitly notes history is not cross-process locked. Multiple GUI instances are allowed.
    - Impact: two instances can overwrite each other's history/settings updates; queue and history can diverge.
    - Recommendation: single-instance mutex or OS file locks for shared JSON files.

20. **No single-instance guard.**
    - Evidence: no named mutex in `ui_qt/app.py` or `__main__.py`; only destination locks.
    - Impact: two GUIs can each run watchers, preflight encodes and update checks; settings/history races; duplicate notifications.
    - Recommendation: a per-user named mutex with “activate existing window” behaviour, or explicit documentation that multiple instances are unsupported.

21. **`verify()` duration tolerances are loose.**
    - Evidence: default `max(0.1 s, duration × 0.001)`; Hybrid `max(0.25 s, tail_ms/1000 + 0.1)`. A 2 s clip tolerates 0.1 s (5%) plus a 0.35 s Hybrid window.
    - Impact: small but real A/V drift can pass; frame-count checks help only when both probes report `nb_frames`.
    - Recommendation: tighten to a tick-level or frame-level tolerance where possible; report drift explicitly.

22. **Documentation drift.**
    - `AI_CODEBASE_SUMMARY.md` says v2.0.0, 52 test modules/566 tests and seven settings tabs; actual 2.0.1, 56 modules/635 cases and four tabs plus search.
    - `SECURITY.md` supported-versions table still starts at 1.0.x and calls v1.0.0 current.
    - `docs/PLATFORM_PRESETS.md` says badge rendering happens on the “Tk main thread” and claims direct probing does not expose color/audio fields; the Tk UI was removed and v1.4 added those fields.
    - `CHANGELOG.md` 2.0.1 says 593 tests and mypy clean; measured 635 and 7 full-tree mypy errors.
    - `README.md`/`docs/PRIVACY.md` describe the build as network-disabled, while the code has env-gated download paths; the release script’s default unsigned state conflicts with the updater’s Authenticode default.
    - `release/READ_ME_FIRST.txt` says FFmpeg is only for thumbnails; it is also used for audio normalisation/bitrate/VFR/codec/resolution preflight.

23. **Parser/input hardening is not fuzzed.**
    - Evidence: no fuzzing target, no AFL/libFuzzer harness, no malformed-MP4 corpus beyond unit fixtures.
    - Impact: the app accepts untrusted media from drag/drop, Explorer, watch folders and CLI. Bounds checks exist, but complex box trees and table relationships are a large attack surface.
    - Recommendation: add a corpus-based parser fuzz target and property tests for `stts`/`stsc`/`stco` invariants.

24. **No code coverage threshold and no real-device QA in the repo.**
    - Evidence: pyproject has no coverage config; CHANGELOG says manual QA pending; benchmark README says untested.
    - Impact: tests are broad but unmeasured; mobile compatibility is structural only; platform behaviour is unverified.
    - Recommendation: add coverage reporting (at least for `core`), a small real-device playback matrix, and keep platform claims explicitly heuristic.

---

## 26. Security and privacy assessment

### Positive controls

- **No telemetry, analytics, advertising or crash-reporting SDKs.** Media is processed locally; no upload path exists for media.
- **Network is opt-in** via `FPS_PATCHER_ALLOW_NETWORK=1`; default shipped behaviour is offline.
- **Update URLs are HTTPS + host-allowlisted**; SHA-256 is checked when the release publishes a sidecar; Authenticode is checked before executing installers/portable EXEs.
- **Portable update extraction** rejects path traversal, caps total extraction at 1 GiB, requires the expected EXE, and uses a detached trampoline rather than in-process replacement.
- **FFmpeg download** uses HTTPS and extracts to fixed filenames (no Zip Slip), with per-file size caps and `-version` validation. The missing pinned hash is the main gap.
- **Subprocesses use argv lists, `shell=False`**, no shell interpolation; FFmpeg extras are tokenised with `shlex`, NUL-rejected, and `-i`/`-y`/`-n` are reserved.
- **Cancellation kills the process tree** through a Windows job object, with a force-kill fallback.
- **Atomic output writes** (`.part` + verify + `os.replace`) and exclusive `.bak` creation prevent partial outputs and backup clobbering.
- **Destination locking** uses a thread lock plus named mutex, so two app instances cannot write the same output concurrently.
- **Diagnostics** mask home directories, UNC server/share names and usernames by default; logs are capped and rotated.
- **Least privilege:** `asInvoker` manifest, HKCU-only Explorer integration and startup, no service/driver/kernel components, no admin requirement.
- **Registry writes** are limited to per-user `SystemFileAssociations` and `Run`; uninstall removes them.
- **UI path handling** uses `Path`/`os.startfile` and quoted subprocess args; no shell string concatenation for media paths.

### Residual risks

| Threat | Assessment |
|---|---|
| Untrusted MP4/MOV input | Large parser surface (`stts`/`stsc`/`stco`/`elst`, nested boxes). Bounds checks exist, but no fuzzing. A malicious file can cause exceptions, large allocations or CPU spend. Treat media as untrusted and run the app as a standard user. |
| Supply chain: FFmpeg download | HTTPS only, no pinned SHA-256, moving `latest` build. A compromised GitHub/BtbN release or TLS interception could deliver a different binary. Bundled builds are safer. |
| Supply chain: update | SHA-256 sidecar + Authenticode when signed. Unsigned releases are rejected by default, which is secure but currently blocks the normal update path. `FPS_PATCHER_ALLOW_UNSIGNED_UPDATE=1` is a QA bypass. |
| Local attacker / shared PC | Settings, queue, history and logs live in the user profile; no encryption. Another process running as the same user can read paths/history. This is normal desktop behaviour. |
| Registry/Explorer integration | HKCU only; the command is quoted; `%1` is the standard Explorer placeholder. A malicious local process with the same user can modify the key, as with any per-user integration. |
| Notifications | Static PowerShell script with values passed via environment variables and length caps; no user text interpolation into script syntax. ExecutionPolicy Bypass is used for that one static script. |
| Resource exhaustion | Full-file memory engines, 512 MB padding cap, large `stts` expansion, 1 GiB update extraction cap, 5 MB diagnostic budget. The app has no global input-size limit. |
| Privacy | No telemetry; local paths in settings/logs/history; path masking available. The optional update/FFmpeg downloads contact GitHub only when the env gate is enabled. |

---

## 27. Compatibility and behavioural limitations

- **Not frame interpolation.** A 30 fps clip retimed to a 60,000 timescale still contains 30 unique frames per second of content; playback timing changes, motion smoothness does not.
- **Fragmented MP4 is rejected** by V3, V4 and BXD (`moof`). `colr.sanitize` skips fragmented files.
- **V3 supports exactly one video track.** BXD retimes only the first video and first audio track; other tracks are shifted but not retimed.
- **BXD drops unsupported top-level boxes** (see risk 11).
- **PC output is non-standard** and may fail mobile/streaming decoders. It is marked experimental.
- **`mvhd=-1` is not a duration.** Players/ingest tools may show unknown length, seek oddly or reject the file; the app’s own README says this is a heuristic.
- **Preflight re-encodes video** for bitrate cap/VFR/codec/resolution. The default GUI normalises non-AAC audio; turn it off to keep the original audio stream. Preflight also drops extra streams (risk 10).
- **HDR:** auto-remediation refuses PQ/HLG unless a bitrate cap is also active (risk 2); the colour sanitizer refuses explicit HDR tags; untagged HDR can be misclassified as SDR.
- **Platform scores are local heuristics**, not guarantees of platform acceptance, resolution retention or no recompression.
- **Windows-first:** the UI, tray, startup, Explorer verb, DWM backdrop, job objects and named mutexes are Windows-specific; CLI/core parsing is cross-platform but the packaged app and FFmpeg downloader target Windows x64.
- **Unsigned builds:** SmartScreen/AV warnings are expected; the README documents hash verification.
- **No real-device playback tests** are included; “mobile-compatible” is structural only.

---

## 28. File map (source)

### Root

| File | Role |
|---|---|
| `src/fps_patcher/__init__.py` | Version, app name, AppUserModelID. |
| `src/fps_patcher/__main__.py` | Dispatch CLI/quick-patch/GUI; startup flag; Tk deprecation. |
| `src/fps_patcher/cli.py` | Headless `patch/probe/score/history/undo`, JSON, exit codes, signal handling, console attach. |
| `src/fps_patcher/config.py` | Settings dataclass, defaults, migration, clamping, atomic save, templates, app data path, network gate. |
| `src/fps_patcher/logging_setup.py` | Rotating file log. |

### `core/`

| File | Role |
|---|---|
| `models.py` | `VideoInfo`, `PatchRequest`, `PatchResult`, events, supported extensions, FPS presets. |
| `errors.py` | Domain exception hierarchy. |
| `strategies.py` | Strategy protocol/registry, X1T aliases, migration, FFmpeg-required check. |
| `atom_patcher.py` | V3 parser and video timescale patch, faststart shift, structural check. |
| `bxd_patcher.py` | X1T PC/Mobile/Hybrid/Clean engine, isolation variants, mobile repair, audio ghost inflation. |
| `v4_patcher.py` | V4 strict-lossless forensic patch, optional mvhd/tkhd sync, dry-run/report. |
| `colr.py` | Lossless Rec.709 tagging, HDR refusal, udta/meta scrub, offset shifting. |
| `patcher.py` | One-file transaction: probe, preflight, dispatch, verify, backup, atomic replace, history. |
| `preflight.py` | Audio normalize/bitrate/VFR/codec/resolution planning and FFmpeg execution, GPU semaphore, stale cleanup. |
| `prober.py` | ffprobe JSON parser and direct moov parser. |
| `verifier.py` | Structure, offsets, sample tables, mobile compatibility, payload integrity, hard verify. |
| `forensic_analyzer.py` | Atom tree, track analysis, sample hashing, byte/semantic diff, report export. |
| `platform_profiles.py` | Generic/TikTok/Instagram/YouTube profiles and deterministic readiness scoring. |
| `job_history.py` | JSON history, 200-record cap, atomic write, backup rollback. |
| `updater.py` | GitHub release check, allowlisted HTTPS download, SHA-256/Authenticode, installer/portable update. |
| `ffmpeg_locator.py` | Search order, `-version` validation, managed bin dir. |
| `ffmpeg_downloader.py` | BtbN download, safe extraction, version check, install. |
| `ffmpeg_runner.py` | `ffprobe` JSON and streaming `ffmpeg` wrappers, extra-arg sanitizer, cancellation. |
| `win_job.py` | Windows job objects and named mutexes. |
| `notify.py` | Windows toast/sound. |
| `diagnostic_logger.py` | Diagnostic report builder, path masking, 20-file/5 MB log rotation. |

### `app/`

| File | Role |
|---|---|
| `controller.py` | `AppController`: events, probing, 2-worker patching, multi-platform, cancel, updates, repair, undo, shutdown. |
| `queue_model.py` | `InputQueue`/`QueueItem`, statuses, selection, overrides, JSON persistence. |
| `watcher.py` | Stdlib folder watcher with settle/lock/own-output/priming rules. |
| `quick_patch.py` | One-shot headless patch for Explorer. |
| `shell_integration.py` | HKCU Explorer verb. |
| `startup.py` | HKCU Run key. |

### `ui_qt/`

| File | Role |
|---|---|
| `app.py` | `QApplication`/`MainWindow` entry. |
| `main_window.py` | Shell, toolbar, queue/inspector split, console, tray, watcher, updates, close/save. |
| `bridge.py` | Controller event queue → Qt signals, forensic worker tasks. |
| `queue_view.py` | Drop card, model, delegate, row painting, thumbnails, drag/drop, context menu, selection. |
| `inspector.py` | FPS/preset/output/bitrate/profile controls, readiness, progress, overrides, VFR banner. |
| `settings_dialog.py` | Four-page draft/apply settings + search + advanced sections. |
| `console.py` | Collapsible activity console, log levels, save/repair. |
| `forensic_dialog.py` | Analyze/compare/repair/export/diagnostic UI. |
| `history_dialog.py` | Job history and rollback. |
| `update_dialog.py` | Release notes/progress/skip/cancel. |
| `theme.py` | Tokens, presets, density/radii/fonts, DWM title bar/backdrop. |
| `qss.py` | Generated QSS and palette. |
| `motion.py` | Easing/fade/slide/height animations, progress bar, reduced motion. |
| `thumbnails.py` | Off-thread ffmpeg/Pillow thumbnail cache. |
| `widgets.py` | Card, section, setting row, segmented control, switch, popover, labels. |
| `icons.py` | Dark/light icon loading and cache. |
| `ui/strings.py` | English/Thai strings and readiness labels. |
| `ui/assets/` | App icon, PNG icons, Inter fonts. |

### Tests and tools

| Area | Files |
|---|---|
| Engine tests | `test_atom_patcher.py`, `test_bxd_audio_verify.py`, `test_bxd_bypass.py`, `test_bxd_presets_and_repair.py`, `test_v4_forensic.py`, `test_core.py`, `test_fixture_matrix.py`, `test_integration.py` |
| Pipeline/quality | `test_capability_and_verifier.py`, `test_preflight_and_updater.py`, `test_preflight_cleanup.py`, `test_parallel_pipeline.py`, `test_remediation.py`, `test_remediation_wiring.py`, `test_destination_lock.py` |
| App/CLI/state | `test_app.py`, `test_cli.py`, `test_job_history.py`, `test_queue_model.py`, `test_queue_selection_patch.py`, `test_settings_v2.py`, `test_settings_wired.py`, `test_watcher.py`, `test_watch_integration.py`, `test_shell_and_quick_patch.py`, `test_windows_startup.py`, `test_network_policy.py`, `test_packaging_and_manifest.py` |
| Profiles/export | `test_platform_profiles.py`, `test_template_and_profile.py`, `test_multi_platform.py` |
| UI | 19 `test_ui_qt_*.py` modules |
| Benchmark/FFmpeg | `test_tiktok_benchmark.py`, `test_ffmpeg_downloader.py`, `test_ffmpeg_lifecycle.py` |
| Tools | `generate_sbom.py`, `tiktok_test.py`, `bench_audit.py`, `capture_qt_screens.py`, `make_icon.py` |

---

## 29. Glossary

| Term | Meaning here |
|---|---|
| **ISO-BMFF** | ISO Base Media File Format, the box structure used by MP4/MOV. |
| **Atom/box** | Length-prefixed container or leaf in an MP4 file. |
| **Timescale** | Ticks per second in `mvhd`/`tkhd`/`mdhd`; `60000` ≈ 60 fps units. |
| **stts** | Decode-time-to-sample table; per-sample durations. |
| **ctts** | Composition-time offsets, usually for B-frames. |
| **elst** | Edit list mapping movie time to media time. |
| **faststart** | `moov` before `mdat`, allowing playback before the whole file is read. |
| **mdat** | Media data payload; the app never re-encodes it in direct engines. |
| **ghost samples** | BXD PC-only fake 8-byte audio samples appended outside `mdat`. |
| **X1T/BXD** | The project's container-bypass presets; BXD is the engine, X1T the UI/preset naming. |
| **Experimental** | Output intentionally violates strict ISO-BMFF (PC trailing bytes / offsets outside mdat). |
| **Preflight** | Optional FFmpeg pass to normalise audio, cap bitrate, fix VFR/codec/resolution before container patching. |
| **Readiness** | Local heuristic score against platform upload rules; not a platform guarantee. |
| **Lossless** | Here: encoded sample bytes unchanged; container metadata still changes. |

---

## 30. Bottom line

FPS Patcher Studio is a well-structured, unusually safety-conscious container editor for a Windows desktop utility. Its strongest properties are:

- the media payload is genuinely preserved across all direct engines;
- atomic writes, destination locks, backups/history and multiple verification layers;
- a clean core/app/UI split with an event-driven, non-blocking Qt shell;
- a broad 635-case test suite covering presets, malformed layouts, UI, CLI and update paths.

Its most important caveats are:

- the X1T presets are **metadata heuristics**, and PC mode is deliberately non-standard;
- the outer payload verification currently reports `FAIL` without blocking publication;
- large files can exhaust memory because the default engines read the whole file;
- the HDR guard has a combined-cap gap;
- the release/update story is internally inconsistent: unsigned artifacts, an Authenticode-required updater, and a documented mypy gate that currently fails;
- documentation has drifted behind the 2.0.1 code.

For a production release, the highest-value fixes are: make verification failures fatal, close the HDR guard gap, stream/cap large inputs, honour the dead `indeterminate_mvhd` flag, pin the FFmpeg download, and make the release/update/signing story coherent.

---

## Appendix A. TikTok TS preset fingerprint

The TikTok TS presets (added after the analysis above) are a separate family. `tiktok-ts` and `tiktok-ts-1080` re-encode H.264/AAC into MPEG-TS and save it with a `.mp4` extension. `tiktok-ts-remux` copies an existing H.264 video bitstream unchanged and re-encodes only the audio. Unlike every direct engine above, they do not preserve the source container; the remux preset does preserve the source video payload.

The reference file is a **remux, not a re-encode**. Its video MD5 (`cd919e08e8f0f79cc4e99cbbe58bf430`) matches a `-c:v copy` remux of `Thekrakong1.mp4`, and its SEI `cmp:6 rnd:1 wrk:16` matches that source. A video re-encode with the bundled `h264_mf` produces `cmp:0 rnd:0 wrk:1` and 18-19 Mbps instead of the reference's 13.1 Mbps. `tiktok-ts-remux` is therefore the preset that reproduces the reference; the re-encode presets are for AV1/HEVC or arbitrary sources.

| Area | Value |
|---|---|
| Container | MPEG-TS, 188-byte packets, first byte `0x47`, extension `.mp4` |
| TS layout | PMT PID 4096, PCR/video PID 0x100, audio 0x101, `service_name=Service01`, `service_provider=FFmpeg` |
| Encoder | Microsoft H.264 Encoder V1.5.3 (Media Foundation, FFmpeg `h264_mf`) |
| Profile / level | Main (77) / up to 4.2 at 1080p60, `avc1.4d402a` |
| Entropy | CAVLC (`entropy_coding_mode_flag=0`) |
| Rate control | `u_vbr` at 20.48 Mbps target |
| GOP | IDR every 60 frames, 2 B-frames requested |
| Timing | 60/1 fps, VUI `num_units_in_tick=1 time_scale=120 fixed_frame_rate_flag=0`, no HRD |
| Colour | No VUI colour description |
| Pixel format | yuv420p, 8-bit, progressive; 1920x1080 for `tiktok-ts-1080` |
| Audio | AAC-LC 48 kHz stereo, `-b:a 128k` |
| Muxer | FFmpeg `mpegts` |

The encoder writes the settings string `pf:77 b:2 gop:60 idr:60 slc:1 rc:2 qp:26 rate:20480000 peak:0 buff:0 ref:2 cabac:0 aud:1 vui:1` as an SEI user_data_unregistered payload. The preset passes the numeric Main profile (`-profile:v 77`) because the bundled `h264_mf` build registers no named profile table. Output resolution follows the source for `tiktok-ts` and is letterboxed to 1920x1080 for `tiktok-ts-1080`.

The Inspector, Settings and queue pickers now offer only the three TikTok TS presets. The four X1T/BXD keys remain registered for saved settings, queue overrides and `--strategy bxd-*`; a saved X1T preset is kept as a legacy entry so it is not changed silently. New installs default to `tiktok-ts-remux`.
