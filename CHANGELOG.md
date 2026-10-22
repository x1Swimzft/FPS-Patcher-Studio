# Changelog

All notable changes to FPS Patcher Studio are documented in this file.

## [0.3.5] - 2026-10-21

### Features & Enhancements
- **Midnight App Icon**: Introduced high-contrast Midnight application icon featuring high-voltage zap with precision FPS gauge across taskbar, title bar, and installer branding.
- **Binary Code Signing & Version Resources**: Added native Windows version info resource (`version_info.txt`) and automated Signtool certificate signing (`build\sign_binaries.ps1`) for PyInstaller executables and Inno Setup installers.
- **FFmpeg Auto-Locator & Downloader**: Enhanced embedded FFmpeg binary resolution with graceful fallback and dedicated downloader support for thumbnail and probe features.
- **Atom Patcher Hardening**: Added zero-length run validation for `stts` and timescale delta bounds checking in MP4 atom stream rewriting.

## [0.3.0] - 2026-10-19

### Major Features & Rebranding
- **Unified TikTok Transcoder Bypass (`X1T Engine`)**:
  - All X1T presets (`X1T For PC`, `X1T For Mobile`, `X1T Hybrid`, and `X1T Clean`) now apply indeterminate `mvhd.duration` (`0xFFFFFFFFFFFFFFFF`), forcing TikTok's ingest parser to skip re-encoding and passthrough `mdat` losslessly.
  - Preserved 100% mobile playback compatibility for `X1T For Mobile`, `X1T Hybrid`, and `X1T Clean` by synchronizing `tkhd`/`mdhd` track timing without out-of-bounds chunks.
- **Full Brand Evolution (`BXD` → `X1T`)**:
  - Rebranded all user-facing names across UI components, control panels, settings tabs, and bilingual dictionaries (English and Thai):
    - `Bxd For PC` → `X1T For PC`
    - `Bxd For Mobile` → `X1T For Mobile`
    - `Bxd Hybrid` → `X1T Hybrid`
    - `Bxd Clean` → `X1T Clean`
    - `Repair for Mobile` → `X1T Repair`
    - Toolbar button `Forensic / BXD` → `Forensic / X1T`
  - Maintained full backward compatibility for existing saved settings and queue overrides with internal aliases (`bxd-*` ↔ `x1t-*`).
- **`.mov` → `.mp4` Container Normalization**:
  - Automatically normalizes QuickTime `.mov` inputs (`qt  ` brand / missing `ftyp`) to standard MP4 branding (`mp42` / `isom`) and forces `.mp4` output extension when patched with X1T presets.
- **Top Toolbar Jitter Fix**:
  - Eliminated high-frequency button redraw and hover flicker on the top queue toolbar by implementing state caching and change guards in `InputList.set_state()`, `ControlPanel.set_state()`, and `MainWindow._refresh_state()`.
- **Queue Usability**:
  - Added dedicated `Clear All` button in the queue header toolbar.
  - Enabled re-patching completed (`Done`) and failed (`Error`) queue items without needing to re-import files.

## [0.2.3] - 2026-10-19

### Fixed & Polished
- **Opaque Surface Rendering (No Transparency Bleed)**: Prevented `pywinstyles` Win32 color-key (`-transparentcolor`) and whole-window alpha from punching holes through the File Queue, Inspector, and Activity Console surfaces when Acrylic/Mica backdrop is enabled.
- **Pinned Inspector Progress & Collapsible Override**: Moved `File Progress` and `Batch Progress` bars into the pinned inspector footer directly above `Start Patch`, and made `Focused Item Override` a compact 1-line bar that expands on click or when an item override is set.
- **Bundled High-DPI Toolbar & Console Icons**: Added 32×32 light/dark RGBA PNG icons (`forensic`, `folder`, `sun`, `moon`, `more`, `settings`) via `CTkImage` to eliminate missing/tiny glyph rendering on Windows.
- **Restored Queue Auto-Probing (`Pending → Probing → Ready`)**: Automatically probes restored/pending queue items on startup so resolution, duration, FPS metadata, and green `Ready` status badges populate immediately.
- **Header & Console Bar Polish**: Removed duplicate app title from toolbar (kept in native OS title bar with `v0.2.3` badge in toolbar), fixed singular `"1 line"` vs `"N lines"` badge formatting, and streamlined the console header to `FFmpeg logs`, `Copy`, `Clear`, `Save Log`, and the overflow menu (`•••`).

## [0.2.2-beta] - 2026-10-18

### UI & UX Redesign (Apple HIG Desktop Layout)
- **Unified Toolbar (`~52px`)**: Title + dynamic `v0.2.2-beta` badge, clickable 3-state FFmpeg status pill (`Checking` / `Ready` / `Not found`), `Forensic / BXD`, `Output Folder`, `Settings`, and `Light` / `Dark` / `System` appearance toggle.
- **File Queue & Preview Strip**: Rounded 16px file cards with background-loaded thumbnails, `W×H · MM:SS · FPS` metadata, 7-state status pills, `O(changed)` row-signature rendering for 100+ files, toggleable `Preview Player` strip (`▶ Play`), and bottom bar with `{selected} of {total} selected` + `Apply Selected`.
- **Right Inspector (`~340px`)**: Segmented `Target FPS` (`60 FPS` / `120 FPS` / `Custom`), 2-column `Timescale` + `Preset` grid, conditional amber warning callout for `Bxd For PC`, **Focused Item Override** card (`Set Override` / `Clear`), `Output` path entry with vertically stacked checkboxes, `%` progress bars, `Source Metadata` (`InfoPanel`), and pinned bottom `Start Patch` / `Cancel` footer.
- **Collapsible Activity Console Drawer**: Dark terminal (`#141417`) drawer (`~40px` collapsed, `~210px` expanded) with chevron toggle, line counter badge, `FFmpeg logs` switch, `Copy` (`Copied` flash), `Clear`, `Save Log` (diagnostic export), `Open Logs Folder`, `Repair for Mobile`, level-colored tags (`INFO`, `OK`, `WARN`, `ERROR`, `CMD`, `DIM`, `DEBUG`), and thread-safe batched logging.

## [0.2.1-beta] - 2026-10-18

### Fixed
- **Queue Selection**: Only patch selected items when clicking Start Patch (`only_selected=True` filtering in queue runner).
- **Post-Patch Hang**: Fixed application freezing at 100% on patch completion by implementing missing `set_context_files()` in `LogConsole` and adding resilient `try...finally` poll loop rescheduling.
- **Worker State Reset**: Controller immediately resets `_worker` state upon draining `PatchDoneEvent` to prevent race condition in busy checks.
- **Select All Toggle**: Dynamic button label toggle between "Select All" and "Deselect All" based on queue selection state.

## [0.2.0] - 2026-10-09

### UI & Aesthetics
- **Modern Translucent "Glass" Design**:
  - Implemented real Windows 10/11 DWM backdrop blur (`Acrylic` / `Mica`) via `pywinstyles` and `ctypes` DwmSetWindowAttribute fallback.
  - Added persistent `glass` boolean and `window_alpha` settings in `Settings` (default `0.96`, toggleable via the header bar).
  - Designed semi-translucent layered surface palette (`#0A0D14` window bg, `#12161F` glass card surface, `#232A38` hairline borders, `#3B82F6` vibrant blue accent).
- **Central Theme Architecture (`src/fps_patcher/ui/theme.py`)**:
  - Centralized all color tokens, radii, padding, typography, and DWM window backdrop logic.
  - Eliminated hardcoded hex color strings across all widget files.
  - Full support for both Dark mode (primary glass) and Light mode.
- **Component Polish**:
  - **Header Bar**: Branded accent logo dot, pill-shaped status badges, and ghost actions with consistent 46px height.
  - **Drop Zone**: Dashed accent border, soft hero iconography, interactive drag-over hover tint, and active loaded-file status pill.
  - **Metadata Info Panel**: Structured uppercase letter-spaced section headers, two-column key-value alignment, and copy-on-click metadata labels.
  - **Activity Console**: Fixed-width mono typography (`Cascadia Mono` / `Consolas`), color-coded log tags (`OK`, `WARN`, `ERROR`), and muted timestamp tags.
  - **Target & Control Panel**: Full-width strategy dropdown, segmented FPS preset pill selector, and path ellipsis.
  - **Action Row & Layout**: Elevated "⚡ START PATCH" primary action button (44px height) with prominent accent contrast, resolving vertical clipping issues on default 1000x720 window geometry.
- **Forensic Window Refactor**:
  - Integrated with `theme.py` design tokens and window backdrop blur.
  - Polished status chips for Container Structure, Payload Integrity, Re-encode Check, and TikTok 1080p status.

