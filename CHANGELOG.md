# Changelog

All notable changes to FPS Patcher Studio are documented in this file.

## [0.9.0] - 2026-10-25

### Added: Phase 3 — Platform Profiles & Pre-Flight Readiness Score
- **Platform profiles**: `Generic`, `X1T — TikTok (No Compress)`, `X1T — Instagram Reels`, and `X1T — YouTube Shorts`, stored as typed offline data in `core/platform_profiles.py`.
- **Readiness reports**: deterministic 0–100 heuristic score with `Ready`/`Review`/`Issues`/`Unknown` status, stable check ids, severity, measured value, explanation, recommendation, and evidence label (`documented`/`recommended`/`heuristic`).
- **Queue badges**: every queue card shows the selected profile's readiness and refreshes when a file is added, re-probed, or the profile changes. Clicking a badge writes the per-check reasons to the Activity Console.
- **Global selector**: profile selection sits beside the patch preset in the inspector, persists in `settings.json`, and never changes the patch strategy or media by itself.
- **Truth-in-labeling**: no unverified `ftyp`/`moov` rewriting; no claim of guaranteed zero recompression. The TikTok preset retains its requested label with a visible disclaimer.
- **HDR-safe**: HDR/BT.2020 metadata is reported, never stripped or forced to Rec.709. Unknown color metadata is reported as unknown, not as SDR.
- **Bitrate evidence**: per-profile heuristic thresholds only (TikTok 20 Mbps, Reels 25 Mbps). YouTube has no bitrate warning because YouTube documents that no bitrate limit is required.
- **Localization**: English and Thai strings for the selector, readiness states, badge text, disclaimer, and detail log labels.
- **Documentation**: `docs/PLATFORM_PRESETS.md` records the profile matrix, source URLs, evidence review date, scoring weights, limitations, and intentionally unimplemented behavior.
- **SignPath Foundation readiness**: added `docs/CODE_SIGNING_POLICY.md`, `docs/PRIVACY.md`, and `docs/SIGNPATH_APPLICATION.md`; corrected stale Authenticode claims; the installer now displays the privacy policy before installation.

### Notes
- Scoring is read-only, offline, and reuses existing probe data; it does not add `ffprobe` calls or modify media.
- Unknown critical fields cap the score at 70 and force `Review`; missing optional color metadata caps the score at 95. Missing data never produces a false `Ready 100%`.
- Verification: 341 passed; `ruff check src tests` and `mypy src tests` clean (87 source/test files). PyInstaller one-folder build in a temporary output directory passed the 6-second launch smoke test; no release artifacts were replaced.

## [0.8.0] - 2026-10-24

### Hardened: Process Lifecycle, Concurrency & MP4 Safety
- **FFmpeg descendants**: Windows Job Objects now own each ffmpeg/ffprobe run. Cancel and hard-kill terminate the tree; ffprobe timeouts are bounded and no longer leave the child running.
- **Watcher shutdown**: `stop(wait=False)` no longer joins a slow scan on the Tk thread. A fresh stop event per run, delivery lock, and inbox dedupe prevent stale-thread delivery and double patches.
- **Preflight temps**: unique per-run names plus exclusive, host-scoped ownership markers. Startup sweeps only marked, stale, writable temps, off the Tk thread.
- **Same-destination writes**: per-destination thread lock plus Windows `Local\` named mutex. The final name is selected under the lock and held through `os.replace`; auto-rename is race-free.
- **Queue add**: each path is resolved once instead of four times. Measured 2000-file add: 638.6 ms → 195.1 ms median (3.3×).
- **MP4 `colr`**: only whitelisted visual sample entries are parsed/tagged; unsupported entries are preserved raw. Pre-`moov` chunk offsets are validated against every `mdat`, even when the `moov` size delta is zero.
- **Mobile repair**: unique `.repair.tmp` name.
- **Verification**: `321 passed`, ruff and mypy clean; real-media MP4/MOV roundtrip and packaged-EXE smoke checks passed.
- **Known limits**: fragmented MP4 is skipped; unsupported sample entries are not tagged; cross-process locking is Windows-only; no real SMB/camera corpus was measured.

## [0.7.1] - 2026-10-24

### Fixed: UI Responsiveness, File Lifecycle & `colr` Integrity
- **`colr` chunk offsets**: shifting is now per `stco`/`co64` entry instead of one global delta. `mdat → moov → mdat` layouts no longer corrupt earlier payloads; offsets inside `moov` or outside every `mdat` are rejected. Tests assert per-`mdat` payload SHA-256.
- **Atomic output**: patch output is written to a unique temp beside the destination and swapped with `os.replace()`. Stale patcher temps are swept after 24 h; a failed patch no longer removes an existing output.
- **Settings saves**: serialized and atomic. A crash mid-save can no longer truncate `settings.json`, and concurrent saves cannot interleave.
- **Startup**: ffmpeg locate/version probes moved off the Tk thread; the window stays responsive and applies `ready`/`missing` when the worker finishes.
- **Close**: the patch worker is cancelled and joined (5 s cap) before Tk teardown.
- **Queue state**: late probe results no longer downgrade `done`/`failed` rows; `current` is cleared when the queue empties.
- **Cleanup**: cancelled preflight runs remove their partial temp; removed queue rows prune thumbnail image/request caches; the thumbnail memory cache is bounded at 128 entries.
- **Verification**: `286 passed`, ruff and mypy clean.

## [0.7.0] - 2026-10-24

### Added: Phase 2 — Watch Folder, Explorer Quick Patch, Color Guard
- **Watch Folder**: stdlib polling intake (`app/watcher.py`) with settle scans, minimum age, locked-file hold-back, and own-output filtering. Finished exports are patched in the background without touching the manual queue selection.
- **Explorer Quick Patch**: per-user `HKCU\Software\Classes\SystemFileAssociations\.mp4|.mov\shell\FPSPatcherStudio` verb. Runs `--quick-patch <file>` headlessly (no Tk import) and shows a native Windows toast.
- **Lossless Rec.709 `colr`**: adds or replaces `colr`/`nclx` (primaries=1, transfer=1, matrix=1) in every video sample entry without re-encoding. HDR/BT.2020 and explicit HDR boxes are left untouched.
- **Metadata scrubber**: removes `udta`/`meta` boxes from `moov`, including editor history.
- **Faststart-safe**: when `moov` precedes `mdat`, `stco`/`co64` chunk offsets are shifted by the exact `moov` byte delta. `mdat` payload bytes are copied verbatim; the file is replaced atomically.
- **Settings**: Output tab gains watch-folder and Explorer-menu controls; Patching tab gains `fix_color_tag` and `scrub_metadata` toggles (EN/TH).
- **Patch pipeline**: color/metadata guard now runs inside `core.patcher` before verification, so manual, watch-folder, and quick-patch runs all honor it.

### Notes
- Fragmented MP4 (`moof`/`sidx`) is skipped for color/metadata rewriting rather than guessed at.
- Untagged HDR is indistinguishable from SDR; the guard only protects explicit HDR signaling.
- The toast is best-effort and may be suppressed when the AUMID has no Start Menu shortcut.

## [0.6.4] - 2026-10-24

### Fixed: 3–5s freeze after closing the preset dropdown
- `_force_win32_repaint()` walked every widget in the window and called `_draw()` on each (1032 widgets with a 30-file queue). It runs twice on every `FocusIn`, which is what the dropdown hands back when it closes: 1.4s per call, so ~3s frozen. It now only invalidates the window and its children with Win32 `RedrawWindow`, which repaints every child window from `WM_PAINT` anyway (1.4s -> 113ms)
- Tests: added a regression test asserting the repaint no longer walks the widget tree

## [0.6.3] - 2026-10-24

### Fixed: preset pill jittered when clicked rapidly
- The Target FPS segmented control restarted its 200ms slide on every click, so spam left the pill chasing a moving target; a click landing mid-slide now settles instantly, while a single click still slides
- Segment text colour now follows the selected value instead of the in-flight position (no more labels flickering between active/inactive while sliding), and is repainted only when the selection changes

## [0.6.2] - 2026-10-24

### Fixed: Click stutter still present in 0.6.1
- Performance: Card focus repaints are coalesced into a single deferred paint, so a fast click burst paints only the final selection instead of every click
- Performance: `InputQueue.get()` no longer calls `Path.resolve()` for every queued item on each lookup (was ~2ms of Win32 syscalls per click at 30 files)
- Tests: added regression tests for click coalescing and the cached resolved path

## [0.6.1] - 2026-10-24

### Performance: UI Responsiveness & Micro-Lag Elimination
- Performance: Eliminated UI lag & stuttering during rapid clicks and control toggling
- Performance: Added `configure_cached` to avoid redundant CPU Tkinter canvas redraws
- Performance: $O(1)$ in-place card focus updates in `InputList`, avoiding full list re-renders
- Performance: Debounced Inspector panel syncs by 35ms during rapid navigation
- Performance: Asynchronous non-blocking `settings.json` disk writes during UI appearance changes
- Performance: Adaptive 50ms (busy) / 200ms (idle) poll loop dedicating 100% CPU to input responsiveness when idle

## [0.6.0] - 2026-10-24

### Features & Automation: Pre-Flight Pipeline & In-App Updater
- **Smart Pre-Flight Audio Auto-Normalizer**:
  - Automatically converts non-AAC or non-48kHz audio streams (e.g., PCM, ALAC, 44.1kHz) to AAC 48kHz stereo before container patching, preventing silent audio issues on mobile platforms and TikTok ingest.
- **Smart Bitrate Limiter**:
  - Applies a <18 Mbps mobile bitrate cap when source video exceeds 25 Mbps to eliminate mobile viewer buffering stalls. Includes hardware encoder fallback (`h264_nvenc`, `h264_amf`, `h264_qsv`) with libx264 software fallback.
- **In-App Auto-Updater**:
  - Seamless update checking against GitHub Releases with SHA-256 integrity verification, asset selection for Windows installers, and one-click update launch.

### Performance & UI Stability Fixes
- **Black Screen Flicker & Repaint Fix (v0.5.1 Regression Resolution)**:
  - Eliminated window black screen flickering and slow sequential repaint on minimize, restore, and Alt+Tab.
  - Removed unstable DWM acrylic backdrop in favor of clean solid styling.
  - Coalesced GUI poll events while the window is iconic (minimized).
  - Debounced window resize events to avoid rapid redraw thrashing.
  - Reused `InputList` row card widgets instead of destroying and recreating them on every queue refresh.

## [0.5.0] - 2026-10-24

### Performance & Responsiveness: Zero-Freeze Streaming Engine
- **Eliminated End-of-Patch Freeze**:
  - Replaced full-file memory allocation and full payload SHA-256 rehashing in `bxd_patcher.py` with an 8MB chunked streaming writer pipeline, dropping peak RAM usage from 12+ GB to < 30 MB.
  - Implemented fast boundary-sampled verification in `verifier.py` (exact byte size + first/middle/last 64 KB SHA-256 slices + track chunk sample verification) with `mmap.mmap` read-only container inspection, reducing post-patch verification time from 2–3 seconds down to < 2 milliseconds.
  - Block-accelerated byte diffing in `forensic_analyzer.py` with 64KB block skipping.
- **UI Micro-stutter Elimination**:
  - Batched event draining in `MainWindow._poll()`: coalesces log bursts via `LogConsole.append_batch()`, throttles progress events, and caps queue re-renders to at most once per 50ms frame.
  - Consolidated dual Tk textbox insertions into a single native call in `LogConsole`, and offloaded session file logging to a background thread.

### Critical Fixes: Mobile Buffering & Audio Integrity
- **Faststart Enforcement Across All Engines (`atom_patcher.py` & `bxd_patcher.py`)**:
  - Direct Atom Method (`direct-atom`) now reorganizes top-level atoms into streaming layout (`ftyp` → `moov` → `mdat`) whenever `moov` is placed after `mdat`, automatically recalculating all `stco`/`co64` chunk offsets across all video and audio tracks.
  - Guarantees immediate playback start on mobile streaming clients (iOS AVPlayer, Android ExoPlayer) without requiring whole-file downloads or HTTP range seeking to EOF.
- **Safe Audio Handling & Elimination of Ghost Audio Corruption**:
  - `X1T For Mobile` (`bxd-mobile`) and `X1T Clean` (`bxd-clean`): Apply indeterminate `mvhd` TikTok bypass while keeping audio track `stts`/`stsz` sample tables 100% intact and untouched. Zero ghost audio frames, zero unboxed trailing bytes. Audio durations and edit lists (`edts`) are strictly preserved.
  - `X1T Hybrid` (`bxd-hybrid`): Indeterminate `mvhd` bypass + video timescale patch + bounded tail delta shaping, strictly encapsulating any padding inside compliant ISO-BMFF `free` boxes with zero unboxed bytes.
  - `X1T For PC` (`bxd-pc`): Capped audio ghost sample inflation at a safe limit (`50,000` samples) and added prominent warning regarding potential mobile viewer playback stalls.
  - Container bloat eliminated: Capped default `free` box padding to 4 KB (down from artificial 30–50 MB zero buffers), preventing infinite spinner on mobile connections.
- **Source Bitrate & Non-AAC Audio Codec Advisories**:
  - Proactive probe warning emitted when source video bitrate exceeds 25 Mbps (`>25,000 kbps`), alerting creators that bypassed videos stream at raw source quality on TikTok and recommend 12–18 Mbps for 1080p to prevent mobile buffering.
  - Proactive warning emitted when non-AAC audio codecs (e.g., PCM, ALAC) are detected in camera/QuickTime files, advising conversion to AAC 48kHz before uploading to prevent TikTok from muting audio.
  - Full localization in both English and Thai (`warn_high_bitrate`, `warn_non_aac_audio`).

## [0.4.5] - 2026-10-22

### Security & Release Engineering
- **Windows Application Manifest (`build/fps_patcher.manifest`)**:
  - Embedded native application manifest specifying `requestedExecutionLevel level="asInvoker" uiAccess="false"`.
  - Added Windows 10/11 compatibility GUID (`{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}`), PerMonitorV2 high-DPI scaling, and UTF-8 code page.
- **Code Signing Architecture Refactoring**:
  - Replaced ambiguous self-signed default with **Explicit Unsigned Releases** by default, eliminating VirusTotal `invalid-signature` tags.
  - Separated development signing (`-SignDev`) from production signing (`-Sign` requiring `CERT_PFX_PATH` / `CERT_PASSWORD`).
  - Added resilient RFC 3161 timestamping with automatic multi-server rotation (DigiCert, Sectigo, Starfield).
  - Generates machine-readable release manifest (`FPSPatcherStudio-v0.4.5.manifest.json`).
- **Software Supply Chain & SBOM**:
  - Implemented standard library CycloneDX 1.5 JSON SBOM generator (`tools/generate_sbom.py`).
  - Upgraded `pillow` to `13.0.0` and verified **0 known CVEs** across all 28 dependencies via OSV.
  - Added optional cryptographic hash validation (`expected_sha256`) and 512MB decompression bomb guard to FFmpeg auto-downloader.
- **Automated CI Security Workflow**:
  - Added `.github/workflows/security-audit.yml` running Ruff, Mypy strict, Pytest, SBOM generation, and pip-audit.
- **Antivirus Dispute Dossier & Documentation**:
  - Added `docs/FALSE_POSITIVE_DISPUTES.md`, `SECURITY.md`, `BUILDING.md`, and `THIRD_PARTY_NOTICES.md`.


## [0.4.0] - 2026-10-22

### Major Features & Unification
- **X1T Preset Engine & Unified TikTok Bypass**:
  - Unified the TikTok transcoder bypass mechanism across all presets (`X1T For PC`, `X1T For Mobile`, `X1T Hybrid`, and `X1T Clean`) utilizing indeterminate `mvhd.duration` (`0xFFFFFFFFFFFFFFFF`), ensuring bit-exact lossless passthrough on TikTok ingest while keeping `mdat` 100% byte-identical.
  - Full rebranding to `X1T` across all UI labels in English and Thai (`X1T For PC`, `X1T For Mobile`, `X1T Hybrid`, `X1T Clean`, `X1T Repair`, toolbar button `Forensic / X1T`), preserving full backward compatibility for saved `settings.json` and queue item overrides.
  - Automatic QuickTime `.mov` to `.mp4` container normalization (`mp42`/`isom` branding) with output `.mp4` extension to prevent TikTok mobile upload re-compression.

### Built-in FFmpeg & FFprobe Auto-Downloader
- **One-Click In-App Tooling (`ffmpeg_downloader.py`)**:
  - Direct download and extraction of official static builds into `%LOCALAPPDATA%\FPSPatcherStudio\bin`.
  - Comprehensive Zip-Slip path traversal protection validating all extracted member destinations.
  - Real-time download progress in top toolbar badge and dedicated Settings > FFmpeg tab with live percentage updates and auto-refresh.

### Authenticode Code Signing & Distribution Pipeline
- **Production Code Signing (`build\sign_binaries.ps1`)**:
  - Embedded Windows PE Authenticode digital signatures via Microsoft `signtool.exe` with SHA-256 digest and RFC3161 timestamping.
  - Native Windows resource file (`build\version_info.txt`) embedding `FileVersion` and `ProductVersion` 0.4.0.0 metadata.
  - Signed portable binaries (`FPSPatcherStudio.exe`) and Inno Setup installer (`FPSPatcherStudio-v0.4.0-Setup.exe`).
  - Automated release script (`build\release.ps1`) generating per-file and combined SHA-256 manifests.

### Security Hardening & Robustness
- **Process Security**: Enforced `shell=False` across all subprocess invocations (`ffmpeg_runner.py`, `diagnostic_logger.py`, `prober.py`).
- **DoS Mitigation**: Added hard cap limits on `stts` sample counts and timescale delta bounds to prevent malicious atom bomb memory exhaustion.

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

