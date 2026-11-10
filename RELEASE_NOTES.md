# Release Notes

## v2.1.0 - 2026-11-10 (X1T Zilem)

Version 2.1.0 adds `X1T Zilem`, a container-only MP4 preset that becomes the
new default. It reproduces the Zilem v1 container fingerprint without touching
the encoded video or audio, so the patch is lossless by construction.

**The Windows build is unsigned; verify the release SHA-256 before running.**

### Added

- **X1T Zilem (`zilem`)** — accepts a non-fragmented MP4 with one H.264 video
  track and one AAC-LC 48 kHz stereo audio track. It converts the old `moov` to
  `free`, appends 17 silent AAC frames, extends the audio track, adds a
  duplicate audio track that shares the same chunks, writes a rebuilt `moov`
  at the end of the file, and tags the video track `X1T Zilem v1`.
- Box-level output verification and a golden test against the real reference
  pair. The 161 MB fixture is not shipped.
- `docs/ZILEM_METHOD.md` with the full transform, accepted inputs, and limits.

### Changed

- `X1T Zilem` is now the default for new installs and CLI runs without
  `--strategy`. `X1T Remux` remains available.
- A saved preset is migrated to Zilem only when it is exactly
  `tiktok-ts-remux`; every other saved choice is preserved.
- Zilem output is `<stem>_zilem.mp4`. It ignores the target FPS and skips
  preflight auto-fixes plus the colour/metadata rewrite.
- The README and website now present Zilem first.

### Compatibility

- Zilem rejects fragmented MP4, multiple video/audio tracks, HEVC/AV1/VP9
  video, non-AAC audio, non-48 kHz or non-stereo audio, and files above the
  32-bit chunk-offset limit. Use `X1T 1080p` or `X1T 60fps` for a lossy
  re-encode, or remux the source first.
- TikTok upload behaviour is not guaranteed. Matching a container fingerprint
  is not proof that TikTok will skip transcoding.

### Verification

- Full pytest suite, ruff, and mypy clean, plus the golden Zilem comparison on
  the real reference pair and a Windows release smoke test.

## v2.0.1 - 2026-11-04 (PC color rewrite hotfix)

Version 2.0.1 fixes a blocking X1T For PC failure when the color tag or
metadata scrub is enabled. The rewrite now runs on the preflight copy before
the PC ghost NAL tail is appended; without a preflight copy the patch still
succeeds and logs a `[COLOR] skipped` warning instead of failing.

**The Windows build is unsigned; the manual QA checklist remains pending.**

### Fixed

- X1T For PC + "Write a lossless Rec.709 color tag" / "Remove editor metadata"
  no longer ends with `color/metadata rewrite failed: invalid top-level
  b'\x00\x00\x00\x00' box size 4`.
- The no-preflight PC path now keeps the patch result and explains that the
  color/metadata rewrite was skipped.

### Verification

- 593 tests, ruff and mypy clean, plus the Windows build smoke test.

## v2.0.0 - 2026-11-04 (Autonomous Multi-Platform Studio)

Version 2.0.0 turns readiness into opt-in remediation, exports several platform
variants in one run, keeps a job ledger with one-click rollback, and patches two
sources in parallel. It also ships the Crimson Graphite redesign, four-tab
Settings, system-tray background mode, and optional Windows startup. **The
Windows build is produced and shipped unsigned; the manual QA checklist remains
pending.**

### Highlights

- **Pillar A — readiness auto-remediation** — the readiness popover can fix VFR
  sources (`-fps_mode cfr`), swap an unsupported codec for H.264 on the active
  platform, and cap resolution to the profile without upscaling. Every fix is
  opt-in, warns that the re-encode is lossy, and refuses HDR PQ/HLG rather than
  silently tone-mapping it. CLI: `--fix-vfr`, `--fix-codec`, `--cap-resolution`.
- **Pillar B — multi-platform export and filename routing** — `export_platforms`
  writes one output per selected platform with collision-safe `{platform}`
  naming, and `filename_template` accepts `{platform}`/`{strategy}`. The same
  release adds per-item platform overrides in the inspector and queue. CLI:
  `--platforms a,b` (not combined with `--profile`).
- **Pillar C — two-stage parallel batch** — up to two sources are patched at
  once while FFmpeg preflight work is serialized to a single pass. Progress stays
  monotonic, cancellation stops new scheduling, and `stop_on_error` keeps a
  one-source in-flight limit.
- **Pillar D — job history and rollback** — `job_history.json` records the last
  200 jobs newest-first, `PatchResult.backup_path` points at the `.bak`, and the
  History dialog or `--cli history|undo` restores the previous bytes and marks
  the row rolled back.

### UI and background

- **Crimson Graphite redesign** — warm graphite/paper surfaces, one muted accent
  per preset, hairline borders, a 44 px primary action, and a first-class light
  mode. Crimson Gamer remains the default preset.
- **Four-tab Settings** — General, Output, Appearance, and System, with Advanced
  accordions for technical patching, naming, visual, and FFmpeg options.
- **System tray** — closing the window keeps patching and watch-folder work
  running. The tray menu can reopen the window or quit, and the first close
  explains where the app went.
- **Windows startup** — optional per-user Run entry; `--startup` starts silently
  in the tray when the tray is enabled.
- **VFR safety banner** — the inspector states when compatibility VFR fixing may
  re-encode and offers a one-click "Use lossless" switch.
- **Faster Settings** — closed dialogs are detached and deleted, an unchanged
  theme is not re-applied, and the search index is built lazily. Close time drops
  from 600 ms+ to about 5 ms; open is about 130 ms.
- **Thai 125% and focus polish** — Thai text wraps at word boundaries, and input
  and button borders render fully in normal and 2 px focus states.


### Upgrade notes

- Defaults keep the old behavior: legacy `_ts<timescale>` naming, single-platform
  runs, lossless atom patching, and `.bak` handling are unchanged.
- Every new fix and export option is opt-in. The re-encoding fixes are lossy;
  HDR PQ/HLG sources are refused.
- With `stop_on_error` off, parallel batches may process files in a different
  order. With it on, processing stays sequential.

### Known limitations

- The preflight GPU semaphore is process-local; two app instances can still
  encode simultaneously.
- Job history writes are not cross-process locked.
- Aspect-ratio cropping/padding and HDR tone-mapping are not auto-fixed.
- Builds remain unsigned; the manual Windows QA checklist is still pending.
- System tray and Windows startup are Windows-only.

### Verification

- 591 tests, ruff and mypy clean, plus a Windows PyInstaller build and a
  6-second launch smoke test.

## v1.4.0 - 2026-11-04 (zero-copy prober)

Version 1.4.0 makes direct probing memory-safe: it reads box headers and the
`moov` payload instead of loading the whole file. **This version is source-only;
it has not been built or tagged, manual QA is pending, and builds remain
unsigned.**

### Highlights

- **Zero-copy probing** — `probe_direct` seeks through top-level MP4/MOV boxes and
  loads only the `moov` payload, capped at 64 MiB. `mdat` is never read into RAM,
  so probing a large file no longer allocates memory proportional to its size.
- **Metadata without ffprobe** — file size and bitrate come from `os.stat`
  (bitrate is still whole-file size ÷ duration). Color tags from `colr`
  (`nclx`/`nclc`) and audio sample rate/channels from `stsd` are now read
  directly, so readiness and preflight keep working when ffprobe is unavailable.

### Known limitations

- Only the first visual sample entry is inspected; `rICC`/`prof` color profiles
  and SPS/VUI values are not parsed, so `pix_fmt` remains unknown in direct mode.
- Audio rate/channels use the version-0 sample-entry offsets even for QuickTime
  v1/v2 entries.
- The Nuitka benchmark remains blocked: no MSVC v143 (`vswhere.exe` absent,
  `cl.exe` missing). No size, cold-start or AV numbers were measured and the
  release pipeline is unchanged.

### Verification

- Automated gates only. Manual QA has not been executed, and no v1.4.0 build has
  been built, tagged or published.

## v1.3.1 - 2026-11-03 (in-app self-update)

Version 1.3.1 turns the update check into a full in-app self-update: the app shows
release notes, downloads the right artifact for the install type, verifies it, and
installs it. **This version has not been built or tagged yet, manual QA is pending,
and builds remain unsigned until SignPath is live.** Do not treat the notes below as
a shipped-release announcement.

### Highlights

- **Update dialog** — the startup prompt is now a dialog with release notes, the
  detected install type, download progress, and **Update now** / **Skip this
  version** / **Cancel**. It replaces the old message box.
- **Installed vs portable** — an installed build (with `unins000.exe`) downloads the
  Setup EXE and runs it silently with `/SILENT /CLOSEAPPLICATIONS
  /RESTARTAPPLICATIONS`. A portable build downloads the `-win64.zip`, stages it, and
  a detached cmd trampoline waits for the app PID to exit, swaps files with
  `robocopy`, then relaunches.
- **Cancellable downloads** — a cancelled download aborts cleanly and its partial
  `.part` file is deleted.
- **Skip is remembered** — `skipped_update_version` persists and suppresses only the
  startup prompt; the toolbar update button stays available.
- **Patching is never interrupted** — if a download finishes during a patch batch,
  installation is deferred: the app does not close, the installer does not launch,
  and the toolbar shows an install-ready button until the batch ends.

### Security

- Downloaded installers and portable executables are verified with Authenticode
  before execution, after the existing SHA-256 check.
- Current releases are **unsigned**, so Authenticode verification rejects them. That
  is expected until SignPath signing is active.
- `FPS_PATCHER_ALLOW_UNSIGNED_UPDATE=1` skips the signature check (with a warning
  in the log). It exists for QA only and must not be used for normal installs.

### Verification

- Automated gates only. Manual QA has not been executed, and no v1.3.1 build has
  been built, tagged or published.

## v1.2.1 - 2026-11-03 (quick-patch timescale + diagnostic masking)

Version 1.2.1 fixes three issues found after 1.2.0. No features or settings change.
The builds are unsigned, and manual QA for this version is still pending.

### Fixes

- Quick Patch (`--quick-patch` and the Explorer verb) and the watch-folder path
  now honor the saved Target FPS preset or custom timescale. They previously
  used a hard-coded 60000 timescale.
- Diagnostic auto-logs written by the main patch path now honor
  `mask_diagnostic_paths`. The setting was ignored there; logs were always
  masked. The repair/forensic path already honored it.
- Removed stale Tkinter wording from two internal docstrings.

## v1.2.0 - 2026-11-01 (bitrate planning + startup update prompt)

Prepared on `fix/v1.0.1`. Version 1.2.0 adds bitrate visibility and a target control,
plus an automatic update prompt at startup. The installer and portable zip are
published on GitHub Releases. The builds are unsigned.

### Highlights

- **Bitrate is visible before patching** — queue rows and the Inspector show the
  source video bitrate and, when auto-cap applies, the estimated post-patch bitrate
  (`source → target`). The patch console now reports both values too.
- **Adjustable bitrate target** — the new `bitrate_target_mbps` setting (1-24 Mbps,
  default 16) controls the auto-cap target in the GUI, CLI and quick-patch. Sources
  at or below the target are still copied losslessly; only higher-bitrate sources
  are re-encoded to H.264 at the target.
- **Behavior change:** auto-cap now triggers when the source exceeds the selected
  target instead of the old fixed 25 Mbps threshold. With the default 16 Mbps target,
  sources between 16 and 25 Mbps are re-encoded when auto-cap is enabled.
- **Startup update prompt** — when a newer GitHub release exists, the app opens the
  existing update dialog automatically after launch. It still asks for confirmation
  before downloading or installing, and declining leaves the update button available.

### Verification

- `uv run ruff check src tests tools` — clean.
- `uv run mypy src tests tools` — clean (95 files).
- `uv run pytest -q` — 412 passed.
- The Windows build passed its launch smoke test.
- Not verified: manual GUI/watch/Explorer/DPI checks and code signing.

## v1.1.0 - 2026-11-01 (defect fixes + AV1 preflight)

Prepared on `fix/v1.0.1`. Version 1.1.0 combines the v1.0.0 defect fixes with an
AV1 preflight acceleration fix: no new features, no telemetry. The v1.0.0
artifacts in `release/` remain the current binaries until this version is built
and tagged.

### Highlights

- **AV1 bitrate cap no longer hangs** — with `auto_cap_bitrate` enabled, the
  preflight decode now tries `-hwaccel d3d11va` before the input and falls back to
  software decoding if the hardware path fails. On an 85 Mbps AV1 1920x1080p60
  clip the preflight dropped from ~101 s to ~13 s, and its progress lines now
  reach the console instead of being buffered. Direct AV1 patching without the
  cap is unchanged and stays lossless.
- **Persisted settings now work** — the eight settings that v1.0.0 stored but never
  read now have runtime consumers:
  - `verify_after` skips post-patch verification when disabled;
  - `backup_original` makes an exclusive `.bak`/`.<n>.bak` copy before replacing an
    existing output (an existing backup is never overwritten);
  - `preserve_mtime` copies the source's pre-patch timestamps onto the final output;
  - `stop_on_error` stops GUI/CLI batches at the first failure;
  - `extra_ffmpeg_args` is tokenised without a shell (`shlex.split(posix=True)`),
    rejects NUL bytes/malformed quoting, and is injected before the output path and
    into preflight. The app's input/output flags `-i`, `-y`, `-n` and `-i=...` are
    rejected before FFmpeg runs;
  - `log_to_file` controls rotating file logging at the entry points;
  - `confirm_overwrite` prompts in the GUI; unattended watch/quick-patch runs
    auto-rename, and the CLI `--overwrite` flag is explicit consent;
  - `notify_done` dispatches `sound`, `toast` or `none` after manual and watch batches.
- **No settings were hidden** — all eight already have UI controls and now have
  consumers, so their controls stay visible.
- **Two-stage Ctrl+C** — the first press requests a soft cancel and exits 130; a
  second press force-kills the job and its child process tree on Windows after a
  5-second grace period, followed by temporary-file cleanup.
- **Updater response cleanup** — non-404 `HTTPError` responses from the release
  check, checksum lookup and download are now closed. HTTP 404 still means "no
  release published".
- **Readiness labels in Thai** — all ten readiness check labels use English/Thai
  i18n keys with an English fallback for future checks.

### Behavior changes

- `notify_done` defaults to `none`, so a completed watch-folder or manual batch is
  silent unless `sound` or `toast` is selected. v1.0.0 always attempted a toast for
  watch completions.
- With `confirm_overwrite` enabled, unattended paths (watch folder, `--quick-patch`)
  auto-rename instead of overwriting, because no dialog can be shown.

### Documentation

- README: method order fixed (1 → 2 → 3), stale `v0.7.0` build names replaced with
  the current `v1.0.0` names, `tools` added to the ruff command, and the measured
  one-folder size recorded as 323,001,846 bytes (308.0 MiB, 189 files).
- CLI `score` added where the Nuitka checklist and release verification omitted it.
- New manual test checklist: `docs/handoff/manual-test-v1.0.1.md`. **Not executed in
  this change**; every pass/fail field is left for a human tester.

### Verification

- `uv run ruff check src tests tools` — clean.
- `uv run mypy src tests tools` — clean (95 files).
- `uv run pytest -q` — 405 passed (baseline 375).
- Not verified: manual GUI/watch/Explorer/DPI checks, a frozen v1.1.0 build, code
  signing, and a real Windows machine without a development environment.

## v1.0.0 - Consolidation (2026-10-25)

FPS Patcher Studio ships as a Qt-only application with the Phase 2 automation
features and Phase 3 platform profiles complete, plus a headless CLI. PyInstaller
remains the release backend; Nuitka was prepared but not adopted (see below).

### Highlights

- **Qt-only UI** — the Tk/CustomTkinter interface is gone; Qt is the sole runtime.
  Every Phase 2/3 surface lives in the Qt UI: watch folder switch + auto-queue,
  Explorer right-click verb, Rec.709 tag / metadata scrub options, platform profile
  selector, per-row readiness badge.
- **Readiness detail on the badge** — hovering a badge shows every check; clicking it
  writes the per-check status, detail and recommendation to the Activity Console.
- **Watch folder correctness** — files already in the folder when watching starts are
  ignored (no backlog storm), files that change or arrive afterwards are queued, and
  a Settings apply no longer restarts the watcher (so an export finishing during the
  dialog is not lost).
- **Headless CLI** — `--cli patch|probe|score` with `--json`, exit codes 0/1/2/130,
  and no Qt import on that path. A windowed frozen build rebinds the parent console's
  std handles, so output works from cmd/PowerShell including `> file`.
- **Explorer coverage** — the per-user verb now registers `.mp4`, `.mov` and `.m4v`.
- **Updater** — HTTP 404 from `/releases/latest` means "nothing published yet" instead
  of a failed check.
- **CI gates repaired** — `ruff check src tests tools` and `mypy src tests tools`
  (94 files) are clean again; the previous 30 test/tool typing errors were fixed.

### Release artifacts (v1.0.0, Windows x64, unsigned)

| Artifact | Approx. size |
|---|---:|
| `FPSPatcherStudio-v1.0.0-Setup.exe` | ~84 MB |
| `FPSPatcherStudio-v1.0.0-win64.zip` | ~117 MB |

Exact sizes and SHA-256 hashes are written next to the artifacts in
`FPSPatcherStudio-v1.0.0.sha256` and `FPSPatcherStudio-v1.0.0.manifest.json`; those
self-generated files are authoritative. The one-folder `dist/FPSPatcherStudio/`
build is ~323 MB (189 files), and the build also writes the CycloneDX SBOM
`FPSPatcherStudio-v1.0.0.cdx.json` (recorded as `sbom_path` in the manifest).

### Verification

- `build/release.ps1` exited **0** (gates → PyInstaller → 6-second launch smoke →
  Inno Setup → hashes → manifest). Artifacts are unsigned by design.
- Gates at build time: `ruff check src tests tools` clean, `mypy src tests tools`
  clean (94 files), `pytest -q` **372 passed**.
- Frozen build: `--quick-patch <clip>` returned 0 and wrote the patched file;
  `--cli probe <clip> --json` returned 0 with valid JSON on stdout (direct console
  and redirected to a file). The same CLI exposes `--cli score <clip> --profile
  tiktok --json`; it is not part of this frozen-build verification.
- Real-ffmpeg e2e tests (PCM `.mov` normalize, `colr` add/scrub with `mdat` hash)
  ran as part of the suite.

### Nuitka (roadmap 4.1)

Not adopted. `build/build_nuitka.ps1` (isolated, dry-run by default) and a rewritten
`docs/NUITKA_EVALUATION.md` are included, but this machine has no MSVC, so **no**
size, cold-start or antivirus measurement exists and none is claimed. The release
pipeline stays on PyInstaller.

### Known limitations

- Registry writes, toast display, real Explorer drag-and-drop and 150%/200% DPI were
  not exercised end-to-end here; registry/UI behavior is covered by unit tests only.
- The readiness score is a local metadata heuristic; it cannot guarantee that a
  platform will skip recompression. HDR/BT.2020 is reported, never retagged.
- Fragmented MP4 is skipped with a warning; offset repair for fragments is absent.
- `notify_done`, `preserve_mtime`, `verify_after`, `backup_original`, `stop_on_error`,
  `extra_ffmpeg_args`, `log_to_file` and `confirm_overwrite` were persisted settings
  with no runtime consumer in v1.0.0. v1.0.1 wires all eight.
- The windowed EXE has no console of its own; a double-click launch discards CLI
  output. Start it from a terminal for CLI mode.

## v0.9.0 - PySide6 UI Cutover (2026-10-25)

FPS Patcher Studio now runs on a native **PySide6/Qt 6** interface. The legacy
Tk/CustomTkinter UI has been removed; Qt is the only UI runtime. The production
frozen build, Windows installer and portable zip below were built from branch
`ui/pyside6` (`976550c`) and smoke-tested on Windows x64.

### Highlights

- **New Qt interface** — Qt Widgets shell with QSS/QPalette theming, shared motion
  helpers and native DWM title-bar/backdrop integration on Windows.
- **Crimson Gamer default** — new installs start on the Crimson Gamer theme preset.
  Existing `settings.json` theme choices are kept.
- **Wide Settings dialog** — two-column **920x640** settings window with search,
  carded sections and the Reset / Cancel / Apply / OK footer. At 125% scaling the
  dialog captures 1150x800 with the same layout.
- **Queue thumbnails** — rows render FFmpeg thumbnails asynchronously and fall back
  to the play glyph when extraction fails.
- **Inline per-item overrides** — the inspector exposes a per-item override card
  (switch, item timescale, item preset, Set Override / Clear) alongside the batch
  preset.
- **Full Forensic parity** — the Qt Forensic dialog covers analysis, repair and
  report export, matching the removed Tk surface.
- **Accessibility and contrast** — accessible names on icon-only and interactive
  controls, visible keyboard focus rings, and WCAG AA contrast checks across all
  seven presets in light and dark modes.
- **Final polish** — Crimson Gamer is the first preset card and the reset default;
  pre-v0.9.0 Obsidian settings migrate to Crimson with a fully opaque window; and
  the Custom target FPS field no longer duplicates the Output timescale.
- **Legacy Tk removed** — `customtkinter`, `tkinterdnd2` and `pywinstyles` are no
  longer dependencies; Tcl/Tk, CustomTkinter and the old data files are excluded
  from the frozen build. The payload contains no `tcl8*`/`tk8*`, `tcl86t.dll`,
  `tk86t.dll` or legacy UI files; `platforms/qwindows.dll` is present.

### Release artifacts (v0.9.0, Windows x64)

| Artifact | Exact size | SHA-256 |
|---|---:|---|
| `FPSPatcherStudio-v0.9.0-Setup.exe` | 88,033,612 B | `dac10374a51d30557f5461f1a7bfb3e3f4b15cc3eb34982444363e325ea8a933` |
| `FPSPatcherStudio-v0.9.0-win64.zip` | 122,847,617 B | `2ab16b0ad9b46782510c368e97f863a8b8b21a4afa9581d8d69cc1803a0684c4` |

One-folder `dist/FPSPatcherStudio/`: **322,912,154 B** (183 files). The zip keeps
the top-level `FPSPatcherStudio/` folder. Checksum sidecars use the
`<lowercase-hash>  <filename>` (sha256sum) format.

Size deltas:

| Measure | v0.9.0 | vs pre-Qt baseline | vs dual-UI build |
|---|---:|---:|---:|
| `dist` | 322,912,154 B | +63,472,232 B (+24.46%) | -12,135,423 B (-3.62%) |
| `Setup.exe` | 88,033,612 B | +15,302,881 B (+21.05%) | -3,386,993 B (-3.69%) |

Baselines: pre-Qt `dist` 259,439,922 B / installer 72,730,731 B; dual-UI `dist`
335,047,577 B / installer 91,420,605 B.

Verification: frozen exe stayed alive for 8 s with isolated `APPDATA` and closed
cleanly; no missing DLL/platform-plugin error. Frozen `--quick-patch` with no
target printed the usage line to stderr and exited **2** without initialising Qt.
Installer built with Inno Setup 7; test suite at cutover: **356 passed**.

### Compatibility

- `FPSPatcherStudio.exe` and `python -m fps_patcher` launch Qt.
- `--ui tk` and `FPS_PATCHER_UI=tk` are **deprecated**: they log a warning and
  launch Qt. Nothing else changes for scripts that pass those flags.
- `--quick-patch` remains headless and does not import Qt.
- Existing patch presets, queue behavior, watch folder, Explorer integration and
  settings files are unchanged.
- The legacy Tk geometry value in `settings.json` is ignored; Qt window geometry is
  stored separately in `QSettings("FPSPatcherStudio", "QtUI")`.

### Known limitations

- Mica/Acrylic is applied to the native frame; central Qt surfaces stay opaque for
  contrast, so the system material is not visible through the client area.
- macOS uses the solid-surface fallback; no `NSVisualEffectView`.
- Real 150%/200% monitor DPI and Explorer drag-and-drop were not exercised
  end-to-end in this environment (offscreen 100%/125% were).
- `_internal/PIL/_imagingtk.cp311-win_amd64.pyd` (14 KB, Pillow's unused ImageTk
  shim) is still collected by PyInstaller. It imports no Tcl/Tk DLLs and is never
  loaded by the Qt app; no Tcl/Tk runtime or data is shipped.
