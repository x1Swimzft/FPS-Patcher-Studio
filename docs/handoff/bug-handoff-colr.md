# Handoff Report — Phase 2 `colr` / MP4 Rewriter

**Status**: no active reproduction. All gates pass (`274 passed`), the built `v0.7.0` EXE probes Rec.709 correctly on a real 2s clip. This report captures the recent failure cluster and the remaining architectural risks for review.

## 1. Bug Description & Symptoms

**Target behavior**: `core/colr.py::sanitize()` must add/replace a Rec.709 `colr`/`nclx` box, remove `udta`/`meta`, preserve `mdat` byte-for-byte, repair `stco`/`co64` offsets when `moov` resizes, and replace the file atomically.

**Observed during bring-up** (valid synthetic ISO-BMFF inputs):

- `ColrError: truncated b'avc1' sample entry`
- `ColrError: invalid b'\x00\x01\x00\x02' box size 1852009592` (parser read `nclx` payload as a box header)
- `ColrError: invalid b'stco' entry count`
- `TypeError: argument must be read-write bytes-like object, not bytes` at `struct.pack_into`

**Side-effect regression**: after wiring the watch-completion toast, an imprecise edit replaced `_open_forensic()` with `_notify_watch_done()`. Clicking the Forensic button would raise `AttributeError`; no test covered that method. Restored, but it shows the UI wiring lacks lifecycle coverage.

**Current status**: the above are fixed; tests and a real-media smoke test are green. If a senior reproduces a failure now, it is more likely an unhandled container layout than the color payload itself (see §4).

## 2. Current Stack & Relevant Files

- Python 3.11.17, stdlib-only feature code, `uv`, PyInstaller 6.22.3, Inno Setup 7, Windows 10.0.26200.
- `src/fps_patcher/core/colr.py`
  - `_parse_children()` L92, `_expand_stsd()` L117, `_video_traks()` L144
  - `_entry_is_hdr()` L167, `_tag_entry()` L183, `_scrub()` L203, `_serialize()` L218
  - `_scan_layout()` L237, `_adjust_offsets()` L274, `_write()` L300, `sanitize()` L328
- `src/fps_patcher/core/patcher.py` — `patch()` L76; guard call at L252
- `src/fps_patcher/core/models.py` — `PatchRequest.fix_color_tag`, `.scrub_metadata`
- `src/fps_patcher/app/controller.py` — request construction with the two flags
- `src/fps_patcher/app/quick_patch.py` — headless request + toast
- `src/fps_patcher/app/watcher.py` — `scan()`, `is_own_output()`
- `src/fps_patcher/ui/main_window.py` — `_sync_watcher()` L866, `_drain_watch_inbox()` L889, `_notify_watch_done()` L914, `_open_forensic()` L917
- `tests/test_colr.py` — `_sample_entry()` L26, `_stco_payload()` L31, `_build()` L53, 8 tests
- Related: `tests/test_watcher.py`, `tests/test_shell_and_quick_patch.py`, `tests/test_watch_integration.py`

## 3. Failed Attempts

1. **Assumed the visual sample-entry prefix was 86 bytes.**
   - Result: child parsing started 8 bytes late, misread the `colr` payload as a box header (`truncated b'avc1'`, `invalid box size ...`).
   - Fix: corrected to `_VISUAL_ENTRY_FIELDS = 78` (8-byte `SampleEntry` + 70 visual fields) and deleted the dead `sample_entry` branch.
   - Still insufficient: every video sample entry is assumed to be 78-byte `VisualSampleEntry`; exotic/encrypted/QuickTime variants are untested.

2. **Fixture built `stco` with version/flags twice.**
   - `_stco_payload()` already emitted 4 zero bytes; `_full()` prepended another 4. The parser read `entry_count = 0`, producing `invalid b'stco' entry count`.
   - Fix: removed the duplicate prefix in the fixture.
   - Why it cost a cycle: a test-fixture defect looked like a production parser defect.

3. **`struct.pack_into()` called on immutable `bytes`.**
   - Result: `TypeError: argument must be read-write bytes-like object, not bytes`.
   - Fix: `bytearray(box.payload)`, patch offsets, then assign `bytes(payload)` back.
   - Why it matters: this path only runs when `moov` grows/shrinks before `mdat`, so it was invisible until the first metadata/offset test.

4. **Suspected a watch-folder feedback loop** because the default template is `{name}_{fps}fps` (`clip_60fps.mp4`) while `is_own_output()` only matches `_tsN`.
   - Verified `output_path_for()` always emits `<stem>_ts<timescale><ext>`; the template is preview-only. No code change.
   - Risk: if naming ever moves to the template, the watcher will re-ingest its own outputs indefinitely.

5. **Editor side effect**: replacing `self._init_ffmpeg()` swallowed `def _open_forensic()`. Fixed manually; no regression test exists.

## 4. Current Hypothesis

**Primary**: the remaining defect surface is the all-or-nothing chunk-offset shift, not the `colr` bytes.

```python
# _scan_layout() records only the FIRST mdat
layout = _scan_layout(src)
shift = delta if layout.mdat_start is not None and layout.moov_end <= layout.mdat_start else 0
if shift:
    _adjust_offsets(moov, shift)   # shifts EVERY stco/co64 entry by the same delta
```

- Standard `moov → mdat` / `ftyp → moov → mdat`: correct, covered by tests.
- `moov` at end (`mdat → moov`): no shift, correct, covered.
- **Mixed / multi-`mdat`** (`mdat → moov → mdat`, or offsets before and after `moov`): wrong. Offsets into media after `moov` become stale (`shift = 0`), or offsets before `moov` are over-shifted. Failure mode is silent sample corruption / unplayable output, not an exception.
- Correct model: shift per entry, e.g. `offset += delta if offset >= moov_end else 0`, or map every top-level media segment before rewriting.

**Secondary hypotheses** if real files still fail:

- `_expand_stsd()` assumes every entry is a 78-byte `VisualSampleEntry`; encrypted (`encv`) or vendor-specific entries with different preambles will desync.
- `sanitize()` deliberately returns `skipped` for fragmented MP4 (`moof`/`sidx`); the UI may look like "nothing happened".
- Toast/registry paths are unit-tested with fakes but not exercised live from the frozen EXE.

**Suggested probes for the architect**:

1. Build `mdat → moov → mdat` and `moov → mdat → mdat` fixtures; assert every chunk offset and decode a frame hash.
2. Run a corpus of phone/camera MP4/MOV with multiple `mdat`, `co64`, and `moov` at end; compare `ffprobe -show_packets` and frame decode hashes before/after.
3. Add a UI smoke test that invokes `_open_forensic()` (or checks the method exists) to catch wiring regressions.
4. Fuzz truncated/oversized box headers; the parser currently raises `ColrError`, which aborts the whole patch (`PatchError`), not a fallback.
