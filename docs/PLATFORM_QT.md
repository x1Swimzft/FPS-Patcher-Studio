# Qt Platform Notes — Windows / macOS

Scope: the PySide6 (`ui_qt`) shell on branch `ui/pyside6`, now the only UI. Core
patching, `--quick-patch`, queue persistence and shell integration are
toolkit-independent and unchanged.

## Entry points

| Invocation | Toolkit | Notes |
|---|---|---|
| `FPSPatcherStudio.exe` | Qt (`ui_qt.app.run(Settings.load())`) | Default. |
| `FPSPatcherStudio.exe --ui qt` | Qt | Explicit selection; `--ui` is removed from `argv` first. |
| `FPSPatcherStudio.exe --ui tk` | Qt | Deprecated: logs a warning and launches Qt. |
| `FPS_PATCHER_UI=tk` | Qt | Deprecated alias; `--ui` overrides the environment variable. |
| `FPSPatcherStudio.exe --quick-patch <video>` | Headless | No Qt import; unchanged. |

Qt 6 manages per-monitor DPI itself, so the entry point does **not** call
`SetProcessDpiAwareness`. The Windows AppUserModelID call remains.

## Backdrop: Mica / Acrylic / fallback

`ui_qt/theme.py::apply_backdrop` is cosmetic, best-effort and never blocks startup.
Every ctypes/DWM call is wrapped and returns `False` on failure.

| Platform | Behaviour |
|---|---|
| Windows 11 build >= 22621 | `DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE)` with the `glass_mode` setting: `Mica` = 2, `Acrylic`/`Aero` = 3, `Mica Alt` = 4, `Solid` = 1. Title bar dark mode (`DWMWA_USE_IMMERSIVE_DARK_MODE` 20, fallback 19) and caption colour (`DWMWA_CAPTION_COLOR` 35, derived from `toolbar_bg`) are applied on every theme change and on `showEvent`. |
| Windows 10 / Windows 11 < 22621 | No system backdrop API; `apply_backdrop` returns `False` immediately. The QSS surface is fully opaque and the DWM title bar is still themed. `Mica`/`Acrylic`/`Aero` degrade to `Solid`. |
| macOS | No Mica. Opaque themed surface plus the native title bar; `apply_backdrop` returns `False` (the DWM code is guarded by `sys.platform`/Windows build). No `NSVisualEffectView`. |
| Linux / other | Opaque themed surface; no backdrop attempt. |

The central queue/inspector surfaces stay opaque for contrast even when a system
backdrop is active. The setting is a request, not a guarantee.

## DPI and scaling

- Qt 6 handles per-monitor DPI on Windows 10/11; do not set process DPI awareness
  before Qt starts.
- Fonts are loaded through `QFontDatabase.addApplicationFont` from
  `ui/assets/fonts`; icons are 32x32 RGBA PNGs loaded as `QPixmap`/`QIcon`, so Qt
  scales them per screen.
- Layout sizes are logical pixels (`theme.py`): window 1120x760, min 920x640,
  toolbar 52, inspector 340. Verify at 100 %, 125 %, 150 % and 200 % and with
  monitors at different scales.
- Thai strings need the extra line height; check both languages at 125 %.
- The legacy geometry string in `Settings.geometry` is Tk format and is not fed
  to `restoreGeometry()`; Qt geometry is stored separately in
  `QSettings("FPSPatcherStudio", "QtUI")`.

## Qt plugins in the frozen build

`build/fps_patcher.spec` keeps only the plugins the widgets shell needs:

| Plugin type | Files |
|---|---|
| `platforms` | `qwindows.dll`, `qoffscreen.dll`, `qminimal.dll` |
| `styles` | `qmodernwindowsstyle.dll` (`qwindowsvistastyle.dll` on older Qt) |
| `imageformats` | `qgif`, `qico`, `qjpeg`, `qsvg`, `qtiff`, `qwebp` |

PyInstaller's PySide6 hooks collect plugins for `QtGui`/`QtWidgets`; the spec
then prunes the rest (for example `imageformats/qpdf.dll` from WebEngine) and
re-adds any wanted DLL the hook skipped. Hidden imports and `collect_data_files`
for PySide6 as a whole are deliberately **not** used.

Excluded because no widget imports them: `QtWebEngine*`, `QtPdf*`, `QtQml`,
`QtQuick*`, `QtQuick3D`, `Qt3D*`, `QtMultimedia*`, `QtDesigner`,
`QtNetworkAuth`, `QtCharts`, `QtGraphs`, `QtBluetooth`, `QtNfc`, `QtPositioning`,
`QtSensors`, `QtTextToSpeech`, `QtScxml`, `QtTest`. Add an exclude only after a
widget actually imports that module; otherwise the plugin/DLL keeps shipping.

Versions: PySide6 `6.12.0` and PyInstaller `6.22.x` are the validated pair. Older
PyInstaller releases may not recognize the Qt 6.12 plugin layout; keep
`uv run --with pyinstaller` current. Build command:

```powershell
uv run --with pyinstaller pyinstaller build/fps_patcher.spec --noconfirm
```

`build/release.ps1` needs no dependency changes: it already runs that command,
then the 6 s launch smoke test, then Inno Setup (`installer.iss` copies
`dist\FPSPatcherStudio\*`, so a one-folder build needs no script changes).
`build/fps_patcher.spec` no longer collects `customtkinter`/`tkinterdnd2` data or
hidden imports; `tkinter`, `_tkinter`, `customtkinter`, `tkinterdnd2` and
`pywinstyles` are explicit `excludes`. `ui/assets` (Qt icons/fonts) stays bundled.

## Frozen artifact sizes (v0.9.0)

Built from `ui/pyside6` (`67be740`) on 2026-10-25 with PySide6 6.12.0,
PyInstaller 6.22.3 and Inno Setup 7.1.0:

| Artifact | Exact size | SHA-256 |
|---|---:|---|
| `dist/FPSPatcherStudio/` (183 files) | 322,912,154 B | n/a (directory) |
| `release/FPSPatcherStudio-v0.9.0-Setup.exe` | 88,033,612 B | `dac10374a51d30557f5461f1a7bfb3e3f4b15cc3eb34982444363e325ea8a933` |
| `release/FPSPatcherStudio-v0.9.0-win64.zip` | 122,847,617 B | `2ab16b0ad9b46782510c368e97f863a8b8b21a4afa9581d8d69cc1803a0684c4` |

Size comparison:

| Measure | v0.9.0 | Pre-Qt baseline | Dual-UI build |
|---|---:|---:|---:|
| `dist` | 322,912,154 B | 259,439,922 B (+63,472,232 / +24.46%) | 335,047,577 B (-12,135,423 / -3.62%) |
| `Setup.exe` | 88,033,612 B | 72,730,731 B (+15,302,881 / +21.05%) | 91,420,605 B (-3,386,993 / -3.69%) |

Payload audit: no `tcl8*`, `tk8*`, `tcl86t.dll`, `tk86t.dll`, `customtkinter`,
`tkinterdnd2` or `pywinstyles` files; `platforms/qwindows.dll` is present.
`PIL/_imagingtk.cp311-win_amd64.pyd` (14 KB) is an unused Pillow shim that
imports no Tcl/Tk DLLs.

### Checking a frozen build

```powershell
Get-ChildItem dist\FPSPatcherStudio\_internal\PySide6\plugins -Recurse -File
$env:QT_QPA_PLATFORM = "offscreen"   # headless launch, qoffscreen must exist
Start-Process dist\FPSPatcherStudio\FPSPatcherStudio.exe
Start-Sleep -Seconds 8
Get-Process FPSPatcherStudio
```

A missing `qwindows.dll` fails with "could not find or load the Qt platform
plugin windows"; a missing `qmodernwindowsstyle.dll` normally still starts with a
fallback style but logs a warning.

## Frozen drag-and-drop check

Drag-and-drop is implemented natively in `ui_qt/queue_view.py` (`setAcceptDrops`,
`dragEnterEvent`, `dragMoveEvent`, `dropEvent`, `collect_urls`). It uses Qt's
file URL MIME data; TkinterDnD2 and Tcl/Tk are no longer shipped.

Explorer drag-and-drop cannot be automated from this environment (it needs an
interactive desktop session and a real Explorer drag source). Manual check on a
frozen one-folder build:

1. Launch `dist\FPSPatcherStudio\FPSPatcherStudio.exe`.
2. Drag one MP4 and one MOV from Explorer onto the queue card.
3. Confirm the drop card highlights, both rows appear, and files are accepted.
4. Repeat while a patch is running: the drop must be ignored (busy guard).
5. Repeat with a folder: folder drops are not supported; the drop is rejected.

## Known gaps

- Mica/Acrylic is unverified on real Windows 11 hardware here; this session ran
  on a Windows build without a visual desktop check. `qoffscreen` proves startup,
  not the visual result.
- Installer / `dist` sizes are recorded in the v0.9.0 table above. Re-measure them
  on later builds; `lzma2` solid compression means installer growth does not track
  raw `dist` growth linearly.
- `--ui tk` is deprecated and launches Qt; Tcl/Tk is not part of the frozen build.
- macOS backdrop and macOS frozen launch are untested on this Windows machine.
- The settings window still accepts the legacy Tk geometry key; it is ignored by
  Qt rather than migrated.
- Accessible-name/keyboard parity is implemented per widget but has not had a
  full screen-reader pass.
- Qt LGPL obligations: the one-folder layout keeps Qt DLLs replaceable; do not
  switch to one-file or static Qt without a licensing review.
