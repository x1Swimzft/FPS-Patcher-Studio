# Release Notes

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
  and redirected to a file).
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
  `extra_ffmpeg_args`, `log_to_file` and `confirm_overwrite` are persisted settings
  with no runtime consumer on the Qt line. They are documented here rather than
  silently claimed to work.
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
