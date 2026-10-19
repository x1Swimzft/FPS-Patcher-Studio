# AI Codebase Summary — FPS Patcher Studio (v0.2.3+)

> **Purpose**: Master architecture, codebase map, state lifecycle, and operational guide for autonomous AI agents and engineers working on **FPS Patcher Studio**.

---

## 1. Project Overview & Identity
- **Repository**: `fps-patcher-studio`
- **Root Path**: `E:\Project\fps-patcher-studio`
- **Current Version**: `0.3.0`
- **Python Target**: Python 3.11+
- **Primary Domain**: High-precision ISO-BMFF (MP4/MOV) container timing patcher. It modifies video timescales, sample duration tables (`stts`), composition offsets (`ctts`), track/movie headers (`mvhd`, `tkhd`, `mdhd`), and edit lists (`edts`/`elst`) losslessly at the binary atom level **without re-encoding video frames**.
- **User Interface**: CustomTkinter 6.0+ styled with Apple HIG desktop aesthetic, WCAG AA obsidian dark theme, Windows Acrylic/Mica backdrop support, drag-and-drop (`tkinterdnd2`), and localized bilingual support (English & Thai).

---

## 2. Directory & Component Map

```
E:\Project\fps-patcher-studio\
├── build\                          # Build & release packaging configurations
│   ├── fps_patcher.spec            # PyInstaller one-folder windowed spec
│   ├── installer.iss               # Inno Setup 6 installer compilation script
│   └── release.ps1                 # Automation: gates -> pyinstaller -> smoke test -> portable zip
├── dist\FPSPatcherStudio\          # Compiled standalone distribution
│   └── FPSPatcherStudio.exe        # Portable binary
├── release\                        # Packaged release archives (.zip & .exe installers + sha256)
├── src\fps_patcher\                # Source root
│   ├── __init__.py                 # Version (__version__ = "0.2.3")
│   ├── __main__.py                 # Entry point: runs logging setup, config load, and MainWindow
│   ├── config.py                   # User settings persistence (%APPDATA%\FPSPatcherStudio\settings.json)
│   ├── logging_setup.py            # Central logging initialization with rotating file handler
│   ├── app\                        # Application state, orchestration & event system
│   │   ├── __init__.py
│   │   ├── controller.py           # AppController: background worker thread, event dispatch, run loop
│   │   └── queue_model.py          # InputQueue & QueueItem: state machine, selection, persistence
│   ├── core\                       # Binary atom manipulation & container strategies
│   │   ├── __init__.py
│   │   ├── atom_patcher.py         # Low-level binary box parser, writer, container traverser
│   │   ├── bxd_patcher.py          # BXD 5-preset patch engine (PC, Mobile, Hybrid, Clean, Repair)
│   │   ├── diagnostic_logger.py    # Forensic telemetry & structured audit logs
│   │   ├── errors.py               # Exception hierarchy (PatcherError, ValidationError, etc.)
│   │   ├── ffmpeg_locator.py       # Detection for bundled/system ffmpeg & ffprobe binaries
│   │   ├── ffmpeg_runner.py        # FFmpeg process wrapper for fallback probing/copying
│   │   ├── forensic_analyzer.py    # Deep atom-tree, semantic field, byte-span & mdat hash diffing
│   │   ├── models.py               # Core data structures (VideoInfo, PatchSettings, JobProgress, etc.)
│   │   ├── patcher.py              # Strategy dispatcher facade
│   │   ├── prober.py               # Pure-Python zero-dependency MP4/MOV header metadata parser
│   │   ├── strategies.py           # Enumeration & registry of patch algorithms
│   │   ├── v4_patcher.py           # Strict ISO-BMFF V4 forensic patcher with memory-mapped buffer
│   │   └── verifier.py             # Pre/post-patch verification suite (payload hash, chunk offsets)
│   └── ui\                         # CustomTkinter User Interface (Apple HIG Layout)
│       ├── __init__.py
│       ├── main_window.py          # Main application window, 3-column layout, poll loop, shortcuts
│       ├── input_list.py           # File Queue view: cards, selection bar, preview player, drop zone
│       ├── control_panel.py        # Inspector: Target FPS, Timescale, Presets, Overrides, Progress
│       ├── info_panel.py           # Media inspector: metadata, streams, atom hierarchy
│       ├── log_console.py          # Collapsible dark console drawer with filter/search/export
│       ├── settings_window.py      # Modal Settings dialog host
│       ├── settings_tabs\          # Modular settings pages (appearance, patching, output, ffmpeg, etc.)
│       ├── theme.py                # Color tokens, typography, window backdrop styling (Mica/Acrylic)
│       ├── strings.py              # Bilingual localization dictionary (EN & TH)
│       ├── icons.py                # 32x32 light/dark PNG icon asset loader
│       ├── thumbnails.py           # Background thumbnail generator (FFmpeg/Pillow)
│       ├── drop_zone.py            # Visual drag-over indicator
│       └── forensic_window.py      # Side-by-side atom forensic comparison window
└── tests\                          # 128 Automated unit & integration tests
    ├── conftest.py                 # Pytest fixtures, mock video samples, temporary test roots
    ├── test_app.py                 # Application lifecycle, controller initialization
    ├── test_atom_patcher.py        # Low-level atom parsing, unpacking, box replacement
    ├── test_bxd_audio_verify.py    # Audio ghost frames and ISO-BMFF audio verification
    ├── test_bxd_bypass.py          # BXD bypass edge-cases and error handling
    ├── test_bxd_presets_and_repair.py # All 5 BXD presets and 6-step mobile repair
    ├── test_capability_and_verifier.py# Hash checks, chunk bounds, validation gates
    ├── test_core.py                # Core models, prober, strategies
    ├── test_fixture_matrix.py      # Test matrix with multiple container types
    ├── test_integration.py         # End-to-end patch pipeline tests
    ├── test_queue_model.py         # Queue item state machine, snapshots, re-patching resets
    ├── test_queue_selection_patch.py# Queue selection toolbar, Clear All action, re-patching
    ├── test_settings_v2.py         # Settings serialization, persistence, defaults
    ├── test_ui_poll_and_context.py # EventBus polling, Tk thread isolation, context menus
    └── test_v4_forensic.py         # V4 forensic patcher atom integrity
```

---

## 3. Core Architecture & Processing Pipeline

```mermaid
flowchart TD
    UserDrop[User Drops Videos / Files] --> InputList[ui/input_list.py]
    InputList --> Prober[core/prober.py: Pure-Python Prober]
    Prober --> QueueItemReady[QueueItem: Status = Ready]
    QueueItemReady --> MainWindow[ui/main_window.py]
    MainWindow --> ControlPanel[ui/control_panel.py: Target FPS & Strategy Selection]
    ControlPanel --> ControllerStart[app/controller.py: start_patch]
    ControllerStart --> ResetRun[queue_model.py: reset_for_run]
    ResetRun --> WorkerThread[Background Worker Thread]
    WorkerThread --> Dispatcher[core/patcher.py]
    
    subgraph PatchStrategies [Core Patch Strategies]
        Dispatcher --> BXD_PC[bxd-pc: PC Trick, Indeterminate mvhd, Ghosts]
        Dispatcher --> BXD_Mobile[bxd-mobile: ISO-BMFF Compliant, Mobile Safe]
        Dispatcher --> BXD_Hybrid[bxd-hybrid: Valid mvhd + Bounded Audio Tail]
        Dispatcher --> BXD_Clean[bxd-clean: Pure Timescale Patch, Untouched Audio]
        Dispatcher --> BXD_Repair[bxd-repair: Lossless 6-Step Normalizer]
        Dispatcher --> V4_Forensic[v4-forensic: Strict Atom Re-mapper]
        Dispatcher --> Direct_Atom[direct-atom: Lightweight Direct Box Editor]
        Dispatcher --> FFmpeg_Copy[ffmpeg-copy: Container Remux via FFmpeg]
    end
    
    PatchStrategies --> Verifier[core/verifier.py: Chunk offsets, MDAT Hash]
    Verifier --> TempFile[Atomic Output: Write to .tmp -> Rename to Target]
    TempFile --> EventBus[Thread-safe EventBus: Progress & Status Events]
    EventBus --> TkPoll[_poll_events: UI Main Thread Dispatcher]
    TkPoll --> UIUpdate[Update Row Badges, Progress Bar, Console Logs]
```

### 3.1. How Container Timing Patching Works
Traditional video frame interpolation or re-encoding degrades picture quality and takes considerable CPU/GPU time. FPS Patcher Studio:
1. Opens MP4/MOV container binary.
2. Locates the video track (`trak -> mdia -> mdhd`, `stbl -> stts`, `ctts`).
3. Scales the timescale or sample durations (`sample_delta = round(original_delta * (src_fps / target_fps))`).
4. Updates container-level headers (`mvhd`, `tkhd`, `edts`) so player timing matches the target framerate.
5. Keeps `mdat` (video sample payload data) 100% byte-identical.
6. Rewrites file atomically using a `.tmp` file to prevent corrupted partial writes.

### 3.2. BXD Strategy Presets Deep-Dive
| Preset ID | Display Name | Audio Treatment | Standards Compliance | Ideal Target |
| :--- | :--- | :--- | :--- | :--- |
| `bxd-pc` | **Bxd For PC** | Appends ~10x ghost frames & unboxed bytes | Non-standard | Desktop players & PC tricks |
| `bxd-mobile` | **BXD For Mobile** | Re-times audio timescale, strict ISO boxes | **100% ISO-BMFF** | iOS AVPlayer, Android MediaCodec, Mobile apps |
| `bxd-hybrid` | **BXD Hybrid** | Bounded last-sample extension + free box | Valid headers | Mixed desktop/mobile workflows |
| `bxd-clean` | **BXD Clean** | Audio completely untouched | Strict | Direct video-only timescale updates |
| `bxd-repair` | **Repair for Mobile** | 6-step normalization of broken containers | Validated | Fixing broken BXD files for playback |

---

## 4. State Machine & Event Architecture

### 4.1. `QueueItem` State Lifecycle
```
[Unprobed File] ──> pending ──> probing ──> ready ──> running ──> done (Completed)
                                              │                    │
                                              └──> error           └──> (Re-patch triggered)
                                                                           │
                                                                           └──> reset_for_run() ──> ready
```
- **State Transition Details**:
  - `pending`: File added to queue; waiting for probing thread.
  - `probing`: Header is being parsed by `core/prober.py` (extracts resolution, duration, codec, fps).
  - `ready`: Ready for patching.
  - `running`: Currently being processed by the worker thread.
  - `done`: Successfully patched. Output file generated.
  - `error`: Failed during patch or verification. Error message captured in `item.error`.
  - **Re-patching**: When `Start Patch` or `Apply Selected` runs on `done` or `error` items, `InputQueue.reset_for_run(paths)` automatically clears errors, resets progress to `0.0`, clears output path, and restores state to `ready`.

### 4.2. EventBus & Thread Isolation
CustomTkinter and Tkinter are **not thread-safe**. Background threads must never touch UI widgets directly.
- Background worker thread posts events to `AppController._event_queue`.
- UI main thread polls `AppController.poll_events()` every 50ms in `MainWindow._poll_events()`.
- **Event Types**:
  - `LogEvent(message, level)`: Routed to `LogConsole` and logging subsystem.
  - `ProgressEvent(item_index, total_items, percent, status_text)`: Updates progress bar.
  - `StatusEvent(text)`: Pinned footer status indicator.
  - `QueueChangedEvent(action)`: Triggers UI queue re-rendering (`action` in `"added"`, `"removed"`, `"cleared"`, `"reset"`, `"updated"`).

---

## 5. UI Layout Specifications (Apple HIG Desktop Theme)

- **Toolbar (`~52px`)**:
  - Left: App Title and unified Status Badge (`● Ready`, `● Patching`, `● Done`).
  - Right: Quick Actions (Theme toggle Light/Dark, Forensic Analyzer, Settings modal, Output folder shortcut).
- **Left Column: File Queue (`InputList`)**:
  - Header: Add Files (`+ Add Files`), Add Folder (`+ Add Folder`), Selection toolbar (`Select All`, `Clear Selection`, `Clear All`), Counter (`X of Y selected`).
  - Cards: Rounded rectangular cards with thumbnail preview, video badges (FPS, Codec, Resolution), progress bar, status pill, and context menu.
  - Preview Player Strip: Bottom collapsible video preview bar with playback scrub and detail metrics.
- **Right Column: Inspector (`ControlPanel` + `InfoPanel`)**:
  - Top: Inspector Header with file summary.
  - Controls: Target FPS selector, Timescale multiplier, Strategy/Preset combo box, Output mode (`Overwrite existing`, `Auto-rename duplicate`, `Custom folder`).
  - Focused Item Override: Collapsible section allowing per-file custom FPS/strategy overrides.
  - Pinned Footer: Progress percentage, status text, and primary `Start Patch` / `Cancel` button.
- **Drawer: Activity Console (`LogConsole`)**:
  - Collapsible dark (`#141417`) bottom console drawer with real-time logs, level filters (`ALL`, `INFO`, `WARN`, `ERROR`), search query box, clear button, and overflow menu (Export `.log`, Auto-scroll toggle, Font size).

---

## 6. Development, Quality Gates & Release Workflow

### 6.1. Running the Application
- **Direct Development Mode**:
  ```powershell
  cd E:\Project\fps-patcher-studio
  uv run fps-patcher-studio
  ```
- **Batch Launcher**:
  ```powershell
  .\FPS_Patcher_Studio.bat
  ```
- **Direct Compiled Executable**:
  ```powershell
  .\dist\FPSPatcherStudio\FPSPatcherStudio.exe
  ```

### 6.2. Mandatory Quality Gates
All commits and modifications must pass all three gates with zero errors:
```powershell
# 1. Linter
uv run ruff check src tests

# 2. Strict Type Checker (57 source files)
uv run mypy src tests

# 3. Test Suite (128 tests)
uv run pytest -q
```

### 6.3. PyInstaller Build & Packaging
```powershell
# Build standalone folder
uv run --with pyinstaller pyinstaller build/fps_patcher.spec --noconfirm

# Run full automated release pipeline (Quality gates -> Build -> Smoke test -> Zip)
powershell -ExecutionPolicy Bypass -File build\release.ps1
```

---

## 7. Key Files Quick Reference
| File Path | Role |
| :--- | :--- |
| `src/fps_patcher/ui/main_window.py` | Primary GUI controller, HIG window frame, event drain loop |
| `src/fps_patcher/ui/input_list.py` | Queue UI, selection actions, Clear All, drag-and-drop |
| `src/fps_patcher/ui/control_panel.py` | Inspector panel, target FPS, overrides, start patch button |
| `src/fps_patcher/ui/strings.py` | Complete English & Thai string translations |
| `src/fps_patcher/app/controller.py` | Central app business logic, background worker thread |
| `src/fps_patcher/app/queue_model.py` | Queue data structures, snapshot generation, state reset |
| `src/fps_patcher/core/bxd_patcher.py` | 5 BXD presets and lossless mobile repair engine |
| `src/fps_patcher/core/atom_patcher.py` | Low-level binary box parser, unpacker, and writer |
| `src/fps_patcher/core/prober.py` | Pure-Python header metadata parser |
| `src/fps_patcher/core/verifier.py` | Pre- and post-patch payload and chunk offset validation |
