# Release Notes

## PySide6 UI Cutover (Unreleased)

FPS Patcher Studio now runs on a native **PySide6/Qt 6** interface. The legacy
Tk/CustomTkinter UI has been removed; Qt is the only UI runtime.

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
- **Legacy Tk removed** — `customtkinter`, `tkinterdnd2` and `pywinstyles` are no
  longer dependencies; Tcl/Tk, CustomTkinter and the old data files are excluded
  from the frozen build.

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
- Artifact sizes change with the dependency removal; the release build records the
  measured `dist` and `Setup.exe` bytes rather than quoting an estimate here.
