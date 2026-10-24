# Audit — UI Responsiveness, File Lifecycle & MP4 Integrity

**Date**: 2026-10-24  
**Baseline**: `v0.7.0` working tree (phase 2 handoff, `docs/handoff/phase2.md`)  
**Method**: code reading, targeted subagent review, reproduction tests, and `tools/bench_audit.py`. Every finding below is either reproduced by a test or measured; unverified suspicions are marked.

---

## Severity ranking

### Critical — would corrupt or destroy user data

**C1. `colr` chunk-offset rewrite corrupted `mdat → moov → mdat` layouts** (fixed)
- File: `src/fps_patcher/core/colr.py` — `_adjust_offsets` / `sanitize`
- Cause: one global `delta` was applied to every `stco`/`co64` entry whenever a `moov` existed before *any* `mdat`. In a mixed layout, chunk offsets that point into an earlier `mdat` were shifted too, and entries pointing into the moved `moov` were not detected.
- Evidence: new tests in `tests/test_colr.py` build a mixed layout and assert per-`mdat` payload SHA-256 is unchanged.
- Fix: shift per entry — unchanged when the offset is before `moov`, rejected when it lands inside `moov`, shifted and range-checked against a real `mdat` payload when after `moov`. All top-level `mdat` payload ranges are collected.

**C2. Output replacement had a no-file window and shared temp names** (fixed)
- File: `src/fps_patcher/core/patcher.py` — `_temp_output`, `_cleanup_stale_temps`, `patch_file`
- Cause: `final.unlink()` then `tmp.rename(final)` leaves the destination missing if the process dies between the two calls; a fixed temp name lets two jobs targeting the same folder collide.
- Fix: `mkstemp` in the destination directory (same filesystem), `os.replace()` for atomic swap, temp files are name-scoped (`*.fps-*.tmp`) and swept only when older than 24 h. Dry runs clean their own temp.

**C3. Settings save could truncate the config and lost concurrent writes** (fixed)
- File: `src/fps_patcher/config.py` — `save`
- Cause: direct `open("w")` write; a crash mid-write leaves a truncated JSON. Two threads saving at once interleave. The destructive fallback path wrote directly again after a failed atomic attempt.
- Fix: module-level save lock, unique per-thread temp, `os.replace()`; on failure the temp is removed and the error is logged, never written over the live file. Regression test: `tests/test_settings_v2.py` concurrent saves.

### High — visible freeze or work lost on exit

**H1. `_init_ffmpeg()` ran `locate()` on the Tk thread** (fixed)
- File: `src/fps_patcher/ui/main_window.py` — `_init_ffmpeg`, `_init_ffmpeg_worker`, `_handle_ffmpeg_event`
- Cause: subprocess probes with 10 s timeouts executed synchronously during startup.
- Fix: locate runs on a daemon thread; the UI applies `ready`/`missing` when the event arrives. Test asserts `_init_ffmpeg` returns in <0.5 s while the probe is gated (`tests/test_ffmpeg_downloader.py`).

**H2. Closing the window did not stop the patch worker** (fixed)
- File: `src/fps_patcher/app/controller.py` — `shutdown`; `src/fps_patcher/ui/main_window.py` — `_on_close`
- Cause: `_on_close` stopped timers but never cancelled/joined the worker, so a running patch could keep writing after Tk teardown.
- Fix: `shutdown(timeout=5)` cancels the token and joins; called before destroy.

### Medium — stale state, leaked resources, measurable UI cost

**M1. `set_info()` downgraded terminal status** (fixed)
- File: `src/fps_patcher/app/queue_model.py`
- Cause: a late probe result set `status = "ready"` on a `done`/`failed` item, so the row appeared unprocessed and could be re-run.
- Fix: terminal statuses are preserved. Test in `tests/test_queue_model.py`.

**M2. `remove_selected()` left `current` pointing at a removed item** (fixed)
- File: `src/fps_patcher/app/controller.py`
- Cause: when the queue emptied, `current` kept the removed path; progress/UI code then referenced a nonexistent row.
- Fix: clear `current` when no items remain. Test in `tests/test_app.py`.

**M3. Preflight left partial temp files on cancel/error** (fixed)
- File: `src/fps_patcher/core/preflight.py`
- Fix: unlink the partial temp on both paths; test in `tests/test_preflight_and_updater.py`.

**M4. Unbounded thumbnail memory cache and per-row image leaks** (fixed)
- Files: `src/fps_patcher/ui/thumbnails.py` — `_remember`; `src/fps_patcher/ui/input_list.py`
- Cause: `_MEM_CACHE` grew with every preview ever shown; removed rows kept `_ctk_images`/`_thumb_requested` entries.
- Fix: FIFO bound of 128 entries and explicit pruning on row removal/empty queue.
- Measured: 1000 inserts → 128 entries after the fix (previously 1000).

**M5. `InputQueue.add()` resolves each path three times** (open, not fixed)
- File: `src/fps_patcher/app/queue_model.py` — `add`, `QueueItem.__post_init__`
- Measured: **1069 ms for 2000 files (535 µs/file)** on this machine; `remove_selected` for the same queue is 0.7 ms. `Path.resolve()` dominates.
- Impact: adding thousands of files blocks the UI for ~1 s. Typical drops are tens of files (<50 ms), so this is not fixed in this pass. One-line fix when it matters: resolve once in `add()` and pass the resolved path into `QueueItem`.

**M6. Watch-folder scan cost scales with file count** (measured, acceptable)
- File: `src/fps_patcher/app/watcher.py` — `scan`
- Measured: 2000 files → first scan 15.4 ms, settle scan 59.0 ms (the settle scan opens each candidate `O_RDWR` on Windows for the lock check).
- 59 ms on a background thread at a 1 s interval is fine; no change.

**M7. Watcher stop joins the Tk thread for up to 3 s** (open, unverified worst case)
- File: `src/fps_patcher/ui/main_window.py` — `_sync_watcher`; `watcher.py` — `stop`
- `stop()` is called from the UI thread on settings apply and close. With a 1 s poll interval the typical join is ≤1 s, but a slow scan (network folder) can reach the 3 s cap and freeze the window.
- Not fixed: needs a measured slow-folder reproduction before adding async teardown complexity.

**M8. Hard kill can orphan ffmpeg** (open)
- File: `src/fps_patcher/core/ffmpeg_runner.py` — `run_streaming`
- Cancel kills the direct child, but there is no Job Object / parent-death handling, so killing the app (Task Manager, crash) can leave ffmpeg running.
- Not fixed: requires a Windows Job Object and a real kill test; deferred.

**M9. No startup sweep for preflight temps** (open)
- `patcher` now sweeps its own stale temps, but `.preflight` files from a previous crash are still only cleaned by the watcher ignore rules, not deleted.
- Not fixed: sweeping beside arbitrary sources needs an ownership marker to avoid deleting another app's files.

### Low — correctness edges and accepted limits

**L1. Concurrent patches to the same destination are last-writer-wins** — `os.replace` makes each result atomic and never corrupt, but one job's output is silently lost. No locking added (would need a cross-process lock and user-visible policy).

**L2. Thumbnail cache is FIFO, not LRU** — a hot thumbnail can be evicted by a burst of new ones. Cheap and bounded; accepted.

**L3. `verify_payload_integrity` does not FAIL on bad chunk offsets** — each patch strategy validates offsets internally; the verifier reports non-standard payloads as `EXPERIMENTAL` because BXD presets legitimately produce them. Deliberately unchanged.

**L4. Non-visual sample entries** — `colr` tagging assumes the 78-byte `VisualSampleEntry` layout. Vendor/non-visual entries that reuse a visual fourcc are refused by the `moov` round-trip guard rather than patched wrongly; no dedicated test for exotic entries.

**L5. Fragmented MP4 is skipped** — `moof`/`trun` offset repair is not implemented; `sanitize` returns `skipped`.

---

## Measurements (`uv run python tools/bench_audit.py`)

| Scenario | Result |
|---|---|
| Queue add, 2000 files | 1069 ms (535 µs/file) |
| Queue remove_selected, 2000 files | 0.7 ms |
| Watcher scan, 2000 files | 15.4 ms first / 59.0 ms settle |
| `sanitize`, 256 MB MP4 | 0.41 s (621 MB/s), peak Python memory 2.0 MB |
| Thumbnail cache, 1000 inserts | 128 entries (bound 128) |

The 2.0 MB peak confirms `sanitize` streams `mdat` with a 1 MB buffer and never loads media into memory.

## Verification

```text
uv run ruff check src tests tools   -> All checks passed
uv run mypy src tests tools         -> Success: no issues found in 83 source files
uv run pytest -q                    -> 286 passed in 24.05s
```

Not verified in this session: real-media smoke test, packaged EXE smoke test, network-folder watcher timing, and hard-kill ffmpeg orphaning.
