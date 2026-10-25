# Consolidation plan — Qt cutover, Phases 2–3, CLI, v1.0.0

**Date:** 2026-10-25 · **Auditor:** lead agent · **Repo:** `E:\Project\fps-patcher-studio`

## 0. Checkout reality (verified, not taken from the handoff)

| Item | Handoff said | Actual |
| --- | --- | --- |
| `main` working tree | Phase 3 uncommitted, v0.9.0 | **Clean.** Phase 3 was committed as `fa91355` on `baseline-v0.9.0-work` (parent = `main` @ `57c5af2`). |
| Qt line | 44 ahead, v0.9.0 | Confirmed `d53dbbb`; `main..ui/pyside6` = 44, `ui/pyside6..main` = **0** → fast-forward possible. |
| Phase 2 on the Qt line | "port it" | **Already ported and wired**: `core/colr.py`, `core/notify.py`, `app/watcher.py`, `app/shell_integration.py`, `app/quick_patch.py`, tests, settings keys, QTimer drain, registry sync, toast. Toolkit-free files are **byte-identical** to `baseline-v0.9.0-work`. |
| Phase 3 on the Qt line | "port it" | **Already ported**: `core/platform_profiles.py` (identical), prober/model extensions, profile selector in the Inspector (persisted as `platform_profile`), readiness badge + popover, tests. Only the *acceptance details* below are missing. |

Backup written to `docs/handoff/backup/` (patch of `main..baseline-v0.9.0-work` + README).
Nothing committed, stashed, or reset. `docs.7z` untouched.

## 1. Gates actually run (2026-10-25)

| Line | ruff | mypy | pytest |
| --- | --- | --- | --- |
| `ui/pyside6` @ `d53dbbb` | pass | pass (48 files) | **356 passed**, 0 failed, 33.3 s |
| `main` @ `57c5af2` (worktree, own venv) | pass | pass (53 files) | **284 passed, 2 failed**, 26.6 s |
| `baseline-v0.9.0-work` @ `fa91355` (worktree) | pass | pass (55 files) | **340 passed, 1 failed**, 33.0 s |

Pre-existing failures on the Tk lines (not caused by this work, both green on the Qt line):

- `test_core.py::test_locate_missing_raises_detailed_error` — environment finds a managed
  FFmpeg outside `shutil.which`/bundled dirs; fixed on `ui/pyside6` by `b4974da`.
- `test_queue_selection_patch.py::test_clear_all_button_ui_and_state` (main only) —
  `tkinterdnd2` cannot load `tkdnd` in this environment.

## 2. File map between the lines

`git diff --stat main..ui/pyside6` = 242 files, +16400/−12039. Categories:

- **Toolkit-free core/app (13 files, +1520/−144)** — the Phase 2/3 payload: `platform_profiles.py` (new),
  `win_job.py` (new), `colr.py`, `watcher.py`, `quota`-free `preflight.py`, `ffmpeg_runner.py`,
  `patcher.py`, `prober.py`, `models.py`, `config.py`, `queue_model.py`, `bxd_patcher.py`, `__main__.py`.
- **UI** — `src/fps_patcher/ui/` (Tk) deleted, `src/fps_patcher/ui_qt/` (18 modules) added.
- **Tests** — Tk UI tests deleted, `tests/test_ui_qt_*.py` (12 files, 75 tests) added; e2e kept.
- **Build/docs** — PySide6 lockfile, Qt specs/installer/manifest, migration + platform docs.

Qt UI map (for later stages): `ui_qt/app.py` (`run`), `main_window.py` (`MainWindow`, watcher drain
L546, patch-done L625, explorer sync L590, readiness L742), `settings_dialog.py` (7 tabs,
watch/Explorer/colr switches), `queue_view.py` (`QueueDelegate` paints rows, readiness pill L813,
cache L1147), `inspector.py` (profile combo L205, readiness card L239, popover L1135),
`console.py`, `bridge.py`, `theme.py`/`qss.py`/`motion.py`, `forensic_dialog.py`, `thumbnails.py`.

## 3. Version decision

The Qt line already contains Phase 2 + 3, so the original split (Qt cutover 0.9.0, ported phases
0.10.0) cannot be applied literally without re-writing history. Revised, same intent:

| Version | Content | Commit |
| --- | --- | --- |
| **v0.9.0** | Qt-only cutover **including** Phase 2+3 features as built | `d53dbbb` (current HEAD) |
| **v0.10.0** | Phase 2/3 **completion** delta: the gaps in §4 + docs/metadata | new commits on top |
| **v1.0.0** | headless CLI + Nuitka outcome + release prep | later commits |

The Tk Phase-3 line (`baseline-v0.9.0-work`) is archived, never released, and superseded
file-for-file on the toolkit side. **No renumbering of that branch is needed** (it ships nothing);
renaming it to `archive/phase3-tk` is enough. This is the one place I deviate from the brief —
say if you want the old tree renumbered anyway.

## 4. What is genuinely left

### Stage 1 — Qt baseline (v0.9.0)
Gates already green. Merge is a **fast-forward** (`main` is an ancestor). Commands prepared,
not run:

```powershell
git checkout main
git merge --ff-only ui/pyside6     # or: git branch -f main ui/pyside6
git tag -a v0.9.0 -m "v0.9.0 - Qt UI cutover" d53dbbb
```

Preservation of Phase 3 Tk work: branch `baseline-v0.9.0-work` + the patch backup already
capture it; nothing to replay. Requires your approval.

### Stage 2 — Phase 2 acceptance gaps (target v0.10.0)
1. `core/updater.py:138` — HTTP 404 from `/releases/latest` must mean "no release", not
   `UpdateError`. Add test (404 → `None`; 403 → raises).
2. `app/shell_integration.py:21` — extensions are `.mp4/.mov`; spec also wants **`.m4v`**
   (register + unregister + fake-registry test).
3. `app/watcher.py` — **existing files at start are ignored** is not implemented: a pre-existing
   file is emitted after ~2 scans. Add a priming pass in `start()` (record signatures, do not emit)
   + test; a file that keeps growing after start still emits.
4. Verify (tests already exist): colr behaviours, own-output/temp filters, lock probe, callback
   isolation, refused-start flag reset, watch batch toast instead of modal summary, watcher stop
   on close, registry resync at startup.
5. Qt glue is present; no rewrite needed. Commit only after approval.

### Stage 3 — Phase 3 acceptance gaps (target v0.10.0)
1. Readiness badge has text + colour but the row tooltip returns only the path
   (`queue_view.py:519`); add readiness text/reasons to the tooltip.
2. **Clicking the badge does not log to the Activity Console** (`QueueDelegate` paints it with no
   hit zone). Add a badge hit zone that appends one line per failed/review check (EN/TH strings)
   and keeps the existing inspector popover for detail.
3. Confirm no probe on render/poll (cache is keyed on `(id(info), profile)` — OK), profile change
   updates badges, scoring stays read-only, disclaimer strings kept.
4. Docs/CHANGELOG/ROADMAP + version bump to **0.10.0** (pyproject, `__init__.py`, `version_info.txt`,
   `installer.iss`, `fps_patcher.manifest`, `uv.lock`, docs headers).

### Stage 4 — Headless CLI
`argparse` in `__main__.py` (GUI default, `--quick-patch` kept), `--cli patch|probe|score`, exit
codes 0/1/2, `--json` on stdout, logs on stderr, Ctrl+C cleanup, no Qt import (test blocks Qt),
console-attach shim for the windowed exe. Reuses `patcher.patch`/`prober`/`evaluate_readiness`.

### Stage 5 — Nuitka (Windows, MSVC required)
**Environment check now: no MSVC (`cl.exe` absent, no VS install), PyInstaller not installed.**
So the Nuitka build will be script + checklist, marked **NOT RUN**, unless you install VS Build
Tools. Separate `build/run_nuitka.py` (does not replace the PyInstaller spec); re-read/rewrite
`docs/NUITKA_EVALUATION.md` (its Tk-era command and 0/70 VirusTotal claims are stale). Decision
defaults to keep PyInstaller.

### Stage 6 — v1.0.0
Version bump everywhere, README v0.7.0 links, CHANGELOG/RELEASE_NOTES/ROADMAP, run
`build/release.ps1` (Inno Setup 7 present; PyInstaller fetched via `uv run --with` — needs
network), sha256/manifest/SBOM, independent subagent review of the whole diff. No tag/push/upload
without approval.

## 5. Approvals needed

- **Now:** approve Stage 1 (and answer the one open question in §3).
- Before every commit, and before merge/tag/push/release upload.

## 6. Risk notes

- The Qt line was never merged/pushed; `main` on GitHub is still Tk v0.7.0.
- `release/` on disk was produced by an older `release.ps1` (no combined `.sha256`/`.manifest.json`),
  so any signing/VirusTotal submission must be regenerated.
- Dead settings on the Qt line (no consumer): `notify_done` for manual batches, `preserve_mtime`,
  `verify_after`, `backup_original`, `stop_on_error`, `extra_ffmpeg_args`, `log_to_file`,
  `confirm_overwrite`. Not fixed here; flagged for v1.0.0 honesty pass.
