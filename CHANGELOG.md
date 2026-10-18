# Changelog

All notable changes to FPS Patcher Studio are documented in this file.

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

