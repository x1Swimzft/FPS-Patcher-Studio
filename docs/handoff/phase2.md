# Phase 2 Handoff — `v0.7.0` Watch Folder, Explorer Quick Patch & Color Guard

**Status**: Delivered  
**Date**: 2026-10-24  
**Base**: `v0.6.4` (`57b03ad`)  
**Scope**: zero new third-party dependencies; stdlib + existing stack only.

---

## Delivered

| Area | File | Notes |
| --- | --- | --- |
| Watch folder intake | `src/fps_patcher/app/watcher.py` | 1s polling thread; requires stable size/mtime for 2 scans and a 1s minimum age; hold-back while locked; ignores its own outputs. |
| Explorer verb | `src/fps_patcher/app/shell_integration.py` | HKCU-only `SystemFileAssociations` registration for `.mp4`/`.mov`; install/uninstall/query are idempotent. |
| Headless quick patch | `src/fps_patcher/app/quick_patch.py` | One file in, toast out. Import graph contains no tkinter/customtkinter. |
| CLI hook | `src/fps_patcher/__main__.py` | `--quick-patch <file>` is dispatched before any Tk import; exit code `0` success, `1` failure, `2` usage. |
| Lossless color tag | `src/fps_patcher/core/colr.py` | Parses/rebuilds `moov`; writes `colr`/`nclx (1,1,1)`; removes `udta`/`meta`; copies `mdat` verbatim; atomic replace. |
| Toast | `src/fps_patcher/core/notify.py` | Static PowerShell WinRT script; title/body passed through environment variables, never interpolated. |
| Pipeline wiring | `src/fps_patcher/core/patcher.py` | Guard runs on the `.part` output before probe/verify, so manual, watch-folder, and quick patches all honor it. |
| Controller | `src/fps_patcher/app/controller.py` | `start_patch(..., only_paths=[...])` resets the run against watched paths without changing the user's selection. |
| UI | `src/fps_patcher/ui/main_window.py`, `settings_tabs/output.py`, `settings_tabs/patching.py`, `strings.py` | Watcher lifecycle on startup/apply/close, inbox drain in `_poll`, batch-complete toast, Explorer sync, EN/TH labels. |
| Settings | `src/fps_patcher/config.py` | `watch_folder_enabled`, `watch_folder`, `explorer_menu`, `fix_color_tag`, `scrub_metadata`. |

## Verification

Run on Windows with the project's uv environment:

```text
uv run ruff check src tests tools   -> All checks passed
uv run mypy src tests tools         -> Success: no issues found in 83 source files
uv run pytest -q                    -> 274 passed in 14.75s
```

Real-media smoke test: a 2s H.264 clip patched through `quick_patch.run()` with both options enabled reports `color_primaries=bt709`, `color_transfer=bt709`, `color_space=bt709` from `ffprobe`, with the original 2.000s duration and no probe errors.

Phase 2-specific tests:

- `tests/test_colr.py` — Rec.709 add/replace, HDR skip, metadata scrub, bit-exact `mdat` hash, `stco` shift with `moov` first, no shift with `moov` last, `.part` support.
- `tests/test_watcher.py` — settle state machine, growing file hold-back, locked file release, own-output exclusion, vanished files, callback failure isolation, thread lifecycle.
- `tests/test_shell_and_quick_patch.py` — fake-registry install/query/uninstall round trip, command quoting, CLI target parsing, headless success/failure, no-tkinter import check.
- `tests/test_watch_integration.py` — inbox drain, busy skip, only-watched-path dispatch, refused-start flag cleanup.

## Design Notes & Deliberate Limits

- **Lossless**: only `moov` is rewritten. `mdat` bytes are stream-copied; a SHA-256 of the payload is asserted in tests.
- **Faststart**: when `moov` ends before `mdat`, every `stco`/`co64` entry is shifted by the exact `moov` size delta. If `moov` follows `mdat`, offsets are left alone. Underflow/overflow aborts the rewrite.
- **Round-trip guard**: if serializing the parsed `moov` does not reproduce the original bytes, the file is refused rather than risk corruption.
- **HDR**: explicit HDR boxes (`mdcv`, `clli`, `dvcC`, `dvvC`) and BT.2020/Display-P3 primaries, PQ/HLG transfer, or BT.2020 matrix values cause the color step to be skipped. Untagged HDR cannot be distinguished from SDR.
- **Fragmented MP4**: `moof`/`sidx` inputs are reported as `skipped`; offset repair for fragments is not implemented.
- **Watcher**: output names are always `<stem>_ts<timescale><ext>`; `_tsN`, `_tsN (n)`, `.preflight`, `.colr`, `.tmp`, `.part`, `.crdownload`, dotfiles, and `~$` files are ignored. If the output folder is also the watched folder, outputs do not feed back.
- **Registry**: HKCU only, no admin and no default-association takeover. Disabling the option removes the verb on the next settings apply/start. Explorer usually picks up the change immediately; sign-out or Explorer restart is the fallback.
- **Toast**: best-effort. Unpackaged WinRT toasts can be suppressed when the AUMID has no Start Menu shortcut; failures are non-fatal and never block a patch.

## Operational Notes

- Source-mode verb command: `pythonw.exe -m fps_patcher --quick-patch "%1"`. Frozen builds use the EXE path.
- Watch-folder runs use `QUICK_PATCH_TIMESCALE = 60000` and the configured strategy/preset.
- Closing the window stops the watcher thread (3s join cap).
- Quick patch prints to stdout/stderr when a console is available; the toast is the primary feedback in windowed builds.

## Next

Phase 3 (`v0.8.0`): platform-specific presets, Instagram/YouTube ingest tuning, and a TikTok readiness score. See `docs/ROADMAP.md`.
