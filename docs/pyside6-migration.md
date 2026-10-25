# PySide6 Migration — Package 0 Audit & Logic/UI Seam

Branch: `ui/pyside6`. Scope: inventory the current Tk/CustomTkinter surface, define the
main-thread seam, and add the `ControllerBridge`. No widgets are ported in this package;
`src/fps_patcher/ui/` and core logic are unchanged.

## Baseline and dependency pins

| Item | Value |
|---|---|
| Baseline installer | `release/FPSPatcherStudio-v0.9.0-Setup.exe` = **72,730,731 bytes** |
| Baseline one-folder dist | `dist/FPSPatcherStudio/` = **259,439,922 bytes** |
| Qt binding | `PySide6==6.12.0` (pyproject) |
| Qt helper | `shiboken6==6.12.0` |
| Test binding | `pytest-qt==4.5.0` |
| Windows packaging | PyInstaller one-folder + Inno Setup (`lzma2`, solid) |

Installed Qt distributions: `pyside6-essentials`, `pyside6-addons`, `pyside6-webengine`,
`pyside6-pdf` (all 6.12.0; wheels ~247 MB downloaded). In this dev environment the
uncompressed PySide6 tree is ~646.7 MB, of which `Qt6WebEngineCore.dll` alone is ~194.1 MB.
**WebEngine and Pdf must be excluded from the frozen build** unless a later widget needs
them; Addons should also be prunable if only Core/Gui/Widgets are imported.

## Layer map

### Pure logic — no change expected

| Module | Notes |
|---|---|
| `core/` (`models`, `patcher`, `prober`, `verifier`, `strategies`, `atom_patcher`, `bxd_patcher`, `colr`, `preflight`, `v4_patcher`, `forensic_analyzer`, `updater`, `ffmpeg_*`, `errors`, `win_job`, `diagnostic_logger`, `platform_profiles`) | Toolkit-free. `models.Event` union is the UI contract. |
| `app/controller.py` | Toolkit-free event producer: `events: queue.Queue`, `emit()`, `drain()`, `busy`, worker threads, cancel/shutdown. No Tk API calls. |
| `app/queue_model.py` | Pure Python `InputQueue`/`QueueItem`; UI must render from it, not duplicate state. |
| `app/watcher.py` | Stdlib polling thread; `on_ready` runs on the watcher thread and currently pushes to a `queue.Queue`. |
| `app/shell_integration.py` | HKCU `winreg`, no UI toolkit. |
| `app/quick_patch.py` | Headless CLI path; must never import `ui`/`ui_qt`. |
| `config.py` | `Settings` dataclass, JSON load/save, validation; async save uses a daemon thread. |
| `logging_setup.py` | Stdlib logging. |
| `ui/strings.py` | Pure translation dictionary; can move to a shared module later. |

### Toolkit-bound UI — to be replaced/ported

| Module | Binding | Current thread hand-off / coupling |
|---|---|---|
| `ui/main_window.py` | `customtkinter`, `tkinterdnd2`, `tkinter` dialogs/menus, `PIL.ImageTk` | `MainWindow(ctk.CTk, TkinterDnD.DnDWrapper)` owns `AppController`. `after(50, _poll)`; `_poll` drains `_watch_inbox`, calls `controller.drain(events.append)`, batches events, then reschedules **50 ms busy / 200 ms idle**. Also creates ffmpeg-init, stale-cleanup, restored-probe and toast threads, and owns watcher lifecycle. |
| `ui/log_console.py` | `customtkinter`, `tkinter.Menu`/`filedialog` | `append()` is callable from workers: it appends to a lock-protected `deque` and returns unless on the main thread. Main thread flushes on a **20 ms** `after` schedule; a **50 ms** `_poll_worker_batch` also flushes. File logging runs in a daemon thread. |
| `ui/input_list.py` | `customtkinter`, `tkinter.Menu`/`filedialog`/`messagebox` | Renders directly from `controller.items`; per-row status/selection/overrides. Thumbnail callback arrives on the thumbnail worker and is wrapped in `after(0, update_ui)` — this is the riskiest existing cross-thread call. |
| `ui/control_panel.py` | `customtkinter`, `tkinter.filedialog` | Callback surface: `on_patch(timescale, strategy)`, `on_cancel`, `on_strategy_change`, `on_override_change(path, ts, strategy)`, `on_profile_change`; `set_state(can_patch, busy)`, `set_batch_progress(...)`. |
| `ui/info_panel.py` | `customtkinter` | Display only: `show_info(VideoInfo, queue_index, queue_total)`, `clear()`. |
| `ui/drop_zone.py` | `customtkinter`, `tkinterdnd2` (`DND_FILES`), `filedialog` | TkDND drop data parsing; `after(300)` success flash. Qt has native `dragEnterEvent`/`dropEvent`; no adapter dependency. |
| `ui/settings_window.py` + `ui/settings_tabs/*` | `customtkinter`, `tkinter` dialogs | Modal `CTkToplevel`; deep-copies `Settings`, each tab `harvest(draft)` writes fields, Apply/Cancel semantics. No controller event traffic. |
| `ui/forensic_window.py` | `customtkinter`, `tkinter` dialogs | Separate `CTkToplevel` for forensic analysis/repair/reports; shares `apply_window_backdrop`. |
| `ui/theme.py` | `customtkinter` (`CTkFont`, `CTkSwitch`, `CTkCheckBox`), ctypes/DWM | Theme tokens, font scale, focus ring, DWM dark titlebar/caption color. `apply_window_backdrop()` is currently **solid surface + DWM titlebar**, not real Mica/Acrylic. `pywinstyles` is declared but not imported anywhere. |
| `ui/animation.py` | `tkinter` `.after` | 60 fps ease-out helper; replace with `QVariantAnimation`/`QPropertyAnimation`. |
| `ui/thumbnails.py` | `PIL` + `threading.Thread` | `request_thumbnail(..., callback)` invokes callback **on the worker thread** (or synchronously on a cache hit); Qt adapter must convert to `QImage`/`QPixmap` and emit a signal. |
| `ui/icons.py` | `customtkinter.CTkImage`, `PIL` | Loads `ui/assets/<name>_{light,dark}.png`; port to `QIcon`/`QPixmap` and `QFontDatabase`. |
| `ui/option_menu.py`, `ui/segmented_control.py` | `customtkinter`, `tkinter` | Custom controls; `segmented_control` uses a Tk `StringVar` + `trace_add`. Equivalent Qt: `QComboBox` / `QButtonGroup` or a small custom widget. |
| `__main__.py` | none directly | Defers `from fps_patcher.ui.main_window import MainWindow` until GUI mode. New entry point must defer `ui_qt` the same way and create `QApplication` before any Qt widget. |

### Toolkit audit result

- **No core or app module imports `tkinter`, `customtkinter`, or `tkinterdnd2`.** The only
  occurrences outside `ui/` are comments/docstrings (`controller.py`, `watcher.py`,
  `core/platform_profiles.py`, `core/__init__.py`, `queue_model.py`). `quick_patch.py`
  explicitly forbids the UI import.
- `PIL` is imported only by `ui/main_window.py`, `ui/icons.py`, `ui/thumbnails.py`.
- The only entry-point dependency is the deferred import in `__main__.py`; switching to
  `ui_qt.main_window` later is a one-line change (plus `QApplication` setup).
- `core.notify` uses PowerShell/WinRT, not Tk; unchanged.
- `app/shell_integration` uses the frozen executable path; unchanged.

## Chosen seam: `ControllerBridge`

`AppController` already owns all worker threads and serializes results through
`controller.events`. That is the seam. We do **not** move work into `QThread`: changing
thread ownership, cancellation, and `_worker` lifecycles would risk behavior for no gain.

### Contract

1. `ControllerBridge(controller, parent=None)` is a `QObject` created on the Qt main
   thread. It holds only `QTimer` + `Signal`s; no widget imports.
2. The constructor starts a single-shot `QTimer(0)`. `start()` is idempotent and also
   recovers if the timer was started before a `QApplication` existed; `stop()` stops it.
3. On each tick the bridge calls `controller.drain(handler, limit=500)`. This runs only on
   the main thread because `drain()` mutates `current`, `ffmpeg`, and `_worker` before
   forwarding each event.
4. Events are re-emitted as `object` signals, preserving order:

   | Event | Signal |
   |---|---|
   | `LogEvent` | `log` |
   | `ProgressEvent` | `progress` |
   | `ProbeDoneEvent` | `probe_done` |
   | `PatchDoneEvent` | `patch_done` |
   | `QueueChangedEvent` | `queue_changed` |
   | `FFmpegDownloadEvent` | `ffmpeg` |
   | `UpdateAvailableEvent` | `update_available` |
   | `UpdateDownloadEvent` | `update_download` |

5. If at least one event was drained, `drained` is emitted after the typed signals. It is
   the natural place for a view to coalesce a queue re-render; handlers must still treat
   each typed signal as the source of truth.
6. The next tick is scheduled at **50 ms while `controller.busy`**, otherwise **200 ms**
   (same cadence as the old `_poll`). `drained` also covers event bursts that arrive while
   the controller is not busy, so no event is stranded.
7. Backpressure is bounded per tick (500 events). The queue itself remains unbounded, as
   today. Progress events should be coalesced by the view; log lines should be appended in
   batches, not one widget call per line.
8. Workers never call `drain()`, never touch widgets, and never call controller actions.
   UI actions (`add_files`, `start_patch`, `cancel`, `start_ffmpeg_download`, update
   download) are initiated from the main thread only.
9. Shutdown: stop the bridge, then `controller.shutdown()` from the main thread. The
   controller remains responsible for joining its patch worker and stopping the watcher.
10. The bridge is transport only. Watcher intake (`FolderWatcher -> _watch_inbox`) is not
    part of this class; the Qt main window will keep draining that queue on its own timer,
    or a later adapter can expose it as another signal.

The bridge implementation lives in `src/fps_patcher/ui_qt/bridge.py`; its pure test is
`tests/test_ui_qt_bridge.py` (no widgets, uses pytest-qt's event loop).

### Thin adapters still needed in later packages

- Queue view: Qt model/view adapter over `controller.items`; refresh on `queue_changed`
  or coalesced `drained`.
- Log sink: replace `LogConsole`'s internal Tk queue with Qt signal delivery; keep the
  file logger and line cap.
- Progress: coalesce latest `progress` into progress bars/labels.
- Dialogs: `QFileDialog`, `QMessageBox`; settings/forensic dialogs reuse `Settings` and
  unchanged core calls.
- Thumbnails: worker result -> `Signal(QImage)` -> `QPixmap` on the main thread.
- Theme/backdrop: QSS/QPalette + native DWM helper; font loading via
  `QFontDatabase.addApplicationFont`.
- Drag/drop and animations: native Qt events and `QVariantAnimation`.
- Entry point: `QApplication` -> Qt main window; keep `--quick-patch` headless.

## Packaging impact

- Current `build/fps_patcher.spec` collects `customtkinter` and `tkinterdnd2` data and
  hidden imports `tkinterdnd2`, `pywinstyles`. A Qt build must add the Qt platform plugin
  (`platforms/qwindows.dll`), style/imageformat plugins, and the Core/Gui/Widgets DLLs.
  PyInstaller's PySide6 hooks normally collect these; verify the one-folder output.
- Prune the Qt tree in the spec: exclude `PySide6.QtWebEngine*`, `PySide6.QtPdf*` and, if
  unused, Qml/Quick/3D/Multimedia/Designer. Remove WebEngine/Pdf wheel payloads from the
  frozen app; keep them out of `hiddenimports`. Re-run the launch smoke test after pruning.
- Do **not** freeze both Tk and Qt if the Qt build replaces the old UI; keeping both bloats
  the installer and keeps tkinterdnd2 data around. Keep old UI source until the Qt UI is
  accepted, but exclude `customtkinter`/`tkinterdnd2` from the new release artifact.
- `dist/` will grow substantially. The baseline above is the comparison point; record the
  new `dist` and `Setup.exe` sizes after the first Qt build instead of estimating.
  Setup uses `lzma2` solid compression, so the installer grows less than the raw dist.
- PySide6 licensing/notices must be reviewed (LGPLv3/GPL/commercial terms) and added to
  `THIRD_PARTY_NOTICES.md` before release. This audit does not make a licensing decision.
- `pyproject.toml` already pins `PySide6==6.12.0`; keep `customtkinter`/`tkinterdnd2` until
  the old UI is removed. `build/release.ps1` gates (ruff/mypy/pytest) and `installer.iss`
  need no structural change; only the spec and size expectations.

## Windows backdrop: Mica/Acrylic vs fallbacks

The current `apply_window_backdrop()` ignores `glass`, `alpha`, `backdrop_mode`, and
`tint_strength`; it paints a solid surface and sets the DWM dark titlebar/caption. The
settings strings `Acrylic`, `Mica`, `Aero`, `Solid` are therefore labels today.

Target behavior:

| Platform | Behavior |
|---|---|
| Windows 11 (build >= 22621) | Set `DWMWA_SYSTEMBACKDROP_TYPE` (38): `2` = Mica, `3` = Acrylic, `4` = Mica Alt if desired. Also set `DWMWA_USE_IMMERSIVE_DARK_MODE` and caption color. Keep the central content surface opaque enough for contrast. |
| Windows 11 older / Windows 10 | No system backdrop API. Fall back to the themed solid surface plus DWM dark titlebar (`DWMWA_USE_IMMERSIVE_DARK_MODE` 20, fallback 19). Optional `SetWindowCompositionAttribute` blur only if it validates; otherwise `Aero`/`Acrylic`/`Mica` all degrade to `Solid`. |
| macOS | No Mica. Solid themed surface and native title bar. An `NSVisualEffectView` is out of scope unless explicitly requested. |
| Linux/other | Solid themed surface. |

Rules: wrap every ctypes/DWM call in `contextlib.suppress(Exception)` and return `False`
on failure; never block startup for a cosmetic effect; use the `glass_mode` setting as a
request, not a guarantee. `pywinstyles` may be removed if the native helper is sufficient,
but do not add it to the frozen Qt build unless actually imported.

## Implementation status (packages 0–9)

### Phase 2/3 completion

| Phase | Commits | Outcome |
|---|---|---|
| Phase 2 — visual parity | `594f7eb`, `0e5bb50`, `aea8e56`, `efbb2a3`, `584fd1d` | Default Crimson preset and shared polish strings/QSS, forensic repair/export parity, wide settings dialog, queue thumbnails + rich empty state + override card, empty-state icon spacing. |
| Phase 3 — integration QA | this commit (`test(ui_qt): wide settings screenshots and integration QA`) | Harness captures the wide settings dialog at 920x640 / 1150x800, full matrix regenerated and dimension/blankness validated, docs synced. |

Resolved parity items:

- Settings dialog is a two-column **920x640** layout with a search field, aligned
  footer (`Reset to Defaults` / `Cancel` / `Apply` / `OK`) and carded sections;
  at 125% it captures **1150x800** with the same layout (right column scrolls).
- Queue rows render FFmpeg thumbnails asynchronously; failures fall back to the
  play glyph. The hero image uses real 2-second generated clips, so thumbnails
  are visible rather than placeholders.
- Empty state is a rich drop card (icon, title, hint, `Add Files`/`Add Folder`,
  extension chips, active-profile summary); the bobbing icon keeps reserved
  space so it never overlaps the title at 100/125%.
- Inspector exposes a per-item override card (switch, item timescale, item
  preset, Set Override / Clear, active/inactive caption).
- Forensic dialog covers repair and report export actions, matching the legacy
  Tk surface.
- Crimson Gamer is the default preset; console and queue retranslate on
  language change.

**Platform baseline:**

- New UI lives in `src/fps_patcher/ui_qt/`; the legacy `src/fps_patcher/ui/` is
  untouched and still launches with `--ui tk`.
- `python -m fps_patcher` / `FPSPatcherStudio.exe` now defaults to Qt;
  `--ui tk` or `FPS_PATCHER_UI=tk` selects the legacy UI.
- `AppController` remains the worker owner. `ControllerBridge` drains its
  `queue.Queue` on the Qt main thread; no worker touches a widget.
- Theme tokens, QSS, QPalette, seven presets, density, SegmentedControl, Switch,
  setup cards, queue model/delegate, console drawer, settings dialog, motion and
  DWM helpers are implemented.
- `pytest -q`: **428 passed**. `ruff check .`: clean. `mypy src/fps_patcher`:
  clean. New Qt tests live in `tests/test_ui_qt_*.py`.
- Screenshot matrix: **113 PNGs** in `images/after-qt/` (7 presets x light/dark
  x en/th = 56 combinations; 56 main + 56 settings at 100/125, plus one
  rich-queue hero at 100%). Main is 1120x760 at 100% and 1400x950 at 125%;
  settings is 920x640 at 100% and 1150x800 at 125%. Latest run: 57/57 at 100%
  and 56/56 at 125%, every image the expected size and non-blank. Reproduce with
  `tools/capture_qt_screens.py`.
- Frozen build (PyInstaller 6.22.3 + PySide6 6.12.0 + Inno Setup 7):
  `dist/FPSPatcherStudio` grew from 259,439,922 to 335,045,829 bytes;
  `Setup.exe` grew from 72,730,731 to 91,420,605 bytes. The frozen qwindows
  build and the legacy `--ui tk` build both started; `--quick-patch` errors
  remain headless.

### Known gaps / limitations

- Mica/Acrylic sets `DWMWA_SYSTEMBACKDROP_TYPE` plus the caption colour, but the
  Qt client surfaces remain opaque, so the system material is mainly visible in
  the native frame. A fully translucent client needs a per-widget alpha design.
- macOS uses the solid surface fallback; no `NSVisualEffectView` implementation.
- Explorer drag-and-drop and Explorer context-menu installation are not
  automatable in this environment. The screenshot harness guards the registry,
  but an earlier capture run may have removed a previously installed HKCU verb;
  re-enable `explorer_menu` in Settings to restore it.
- 100% and 125% were rendered with `QT_SCALE_FACTOR` offscreen; real 125%/150%
  monitor DPI was not exercised.
- Legacy `Settings.geometry` (Tk string) is intentionally ignored; Qt geometry
  lives in `QSettings("FPSPatcherStudio", "QtUI")`.
- The old customtkinter UI and its dependencies remain until removal approval.

## Risks

- **Geometry persistence:** `Settings.geometry` stores a Tk string
  (`"1120x760+..."`). Qt's `saveGeometry()` is an opaque `QByteArray`; do not feed the old
  value into `restoreGeometry()`. Add a Qt-specific key or parse/ignore the legacy value.
- **DPI awareness:** `__main__.py` currently calls `SetProcessDpiAwareness(1)` before
  importing Tk. Qt 6 expects to manage per-monitor DPI itself. Decide in the Qt entry point
  (remove the legacy call or set the appropriate Qt attribute) and test at 100/150/200%.
- **Cross-thread thumbnails:** the existing callback is invoked on a daemon worker and
  calls Tk `after(0)`. Qt must deliver image data through a signal; never construct
  `QPixmap` off the GUI thread.
- **Event loss/ordering:** the bridge preserves order, but batching/coalescing in the view
  can drop intermediate progress/log entries if done carelessly. Keep `queue_changed`
  idempotent and render from `controller.items`, not from event payloads alone.
- **Blocking calls:** `messagebox`-style dialogs and update-installer launch currently run
  inside the poll/event handler. Qt equivalents are modal too; keep them after a batch
  completes and avoid invoking them while a worker is emitting at high rate.
- **Fonts/Unicode:** `theme.py` loads bundled fonts through Win32 GDI (`AddFontResourceExW`)
  on import. Qt needs `QFontDatabase.addApplicationFont`; verify Thai and monospace
  rendering, including high-DPI scaling.
- **Single toolkit per process:** Tk and Qt cannot both be initialized usefully in one
  process. The Qt entry point must not import `fps_patcher.ui` (including `ui/strings.py`
  via a package-level side effect). Keep the deferred import discipline.
- **Pruning may break Qt imports:** excluding WebEngine/Pdf/Qml is safe only if no Qt
  module imports them transitively. Validate with a clean-machine launch, not just a dev
  venv. Antivirus/SmartScreen behavior may change with the added Qt DLLs.
- **Tests without a display:** the bridge test has no widgets and only needs an event loop,
  but pytest-qt still creates a `QApplication`; headless CI should set
  `QT_QPA_PLATFORM=offscreen` (or the test can fall back to `QCoreApplication`).
