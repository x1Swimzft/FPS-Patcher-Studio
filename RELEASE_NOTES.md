# Release Notes

## v0.9.0 - PySide6 UI Cutover (2026-10-25)

FPS Patcher Studio now runs on a native **PySide6/Qt 6** interface. The legacy
Tk/CustomTkinter UI has been removed; Qt is the only UI runtime. The production
frozen build, Windows installer and portable zip below were built from branch
`ui/pyside6` (`67be740`) and smoke-tested on Windows x64.

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
