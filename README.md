# FPS Patcher Studio

<div align="center">

![Version](https://img.shields.io/badge/version-v0.3.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%2064--bit-0078D6.svg?logo=windows&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Lossless](https://img.shields.io/badge/processing-lossless%20%E2%80%A2%20zero%20re--encode-brightgreen.svg)

**High-precision MP4/MOV container timing patcher with modern macOS HIG aesthetic and Windows DWM Acrylic/Mica backdrop.**  
*Direct ISO-BMFF atom rewriting • Bit-exact sample preservation • Sub-second processing • X1T Engine*

[📥 Downloads](#-downloads-v030) • [✨ Key Features](#-key-features) • [⚙️ Presets](#️-patching-presets-x1t-engine) • [🔍 Forensic Inspector](#-mp4-forensic-inspector) • [🚀 Getting Started](#-getting-started)

</div>

---

## 📖 Overview

**FPS Patcher Studio** is a specialized desktop engineering utility designed to manipulate ISO-BMFF (`.mp4`, `.mov`) container timing headers directly at the binary atom level. 

Unlike traditional video converters or FFmpeg stream copying, FPS Patcher Studio:
- **Zero Re-encoding**: Never touches the underlying H.264/HEVC video bitstream or AAC audio stream.
- **100% Lossless Quality**: Preserves the original `mdat` payload bit-for-bit with zero compression artifacts or generation loss.
- **Blazing Fast**: Patches multi-gigabyte video files in milliseconds by rewriting header atoms (`moov`, `mvhd`, `tkhd`, `mdhd`, `stts`, `ctts`, `edts/elst`) directly on disk.
- **X1T Engine & Platform Bypass**: Powered by the **X1T Engine**, enabling TikTok bypass via indeterminate `mvhd` container headers while preserving exact sample tables and track durations for mobile players (iOS AVPlayer, Android MediaCodec).
- **Container Normalization**: Automatically converts QuickTime `.mov` containers to compliant `.mp4` with synthetic ISO-BMFF `ftyp` atoms (`mp42`/`isom`).

---

## 📥 Downloads (v0.3.0)

| Distribution | File | Architecture | Description |
|---|---|---|---|
| **Installer** | [FPSPatcherStudio-v0.3.0-Setup.exe](https://github.com/x1Swimzft/FPS-Patcher-Studio/releases/download/v0.3.0/FPSPatcherStudio-v0.3.0-Setup.exe) | Windows x64 | Standard Inno Setup installer with desktop shortcut & uninstaller |
| **Portable** | [FPSPatcherStudio-v0.3.0-win64.zip](https://github.com/x1Swimzft/FPS-Patcher-Studio/releases/download/v0.3.0/FPSPatcherStudio-v0.3.0-win64.zip) | Windows x64 | Standalone zip — extract and run `FPSPatcherStudio.exe` |

---

## ✨ Key Features

### 🖥️ Apple macOS HIG Desktop Interface (Phase 1 & Phase 2)
- **Bundled Inter Typography**: Inter (`Regular`, `Medium`, `SemiBold`, `Bold`) loaded privately at startup via Win32 GDI with seamless Thai fallback (`Noto Sans Thai`, `Segoe UI Variable`).
- **Semantic Color Palette**: 100% opaque surfaces with Apple HIG semantic colors (`#1D1D1F`/`#D9D9DC` primary text, `#007AFF`/`#0A84FF` system blue, `#34C759`/`#30D158` system green, `#FF9500`/`#FF9F0A` system amber, `#FF3B30`/`#FF453A` system red, and crisp 1px hairline borders).
- **Windows DWM Title Bar Sync**: Native Windows 10/11 title bar matches toolbar theme via Win32 DWM APIs (`DWMWA_USE_IMMERSIVE_DARK_MODE = 20` + `DWMWA_CAPTION_COLOR = 35`).
- **Vector-Crisp Dual-Tone Icons**: Clean 32x32 @2x (1.5px stroke) Phosphor/Lucide-style PNG icons loaded dynamically via `CTkImage` replacing all emoji/ASCII glyphs.
- **Animated Sliding Pill Controls**: Custom `MacSegmentedControl` (`60 / 120 / Custom`) with smooth 200ms cubic ease-out sliding capsule thumb (`1 - (1 - t)**3`) and `reduce_motion` instant snap support.
- **Animated Activity Console Drawer**: Smooth 200ms ease-out expand/collapse drawer (`40px` <-> `210px`) with primary action cluster (`FFmpeg logs`, `Copy`, `Clear`, `Save Log`) and overflow menu.
- **Window Focus-Aware Queue Selection**: Selected queue cards fill solid Accent Blue (`#007AFF`/`#0A84FF`) with white text when window is active, automatically transitioning to macOS Unfocused Grey (`#3A3A3C`/`#D1D1D6`) when window loses OS focus.
- **Keyboard Focus Rings**: 2px System Blue highlight border on `<FocusIn>` / `<FocusOut>` across all interactive controls.

### ⚡ Batch Processing Queue
- Drag-and-drop multiple video clips or directories (`tkinterdnd2`).
- Per-item selection checkboxes: patch only selected clips or the entire batch.
- Real-time probe status, duration, resolution, and FPS detection.
- Pinned inspector footer: progress bars and action buttons remain pinned so Source Metadata (`InfoPanel`) is never pushed below the fold.

### 🛡️ 6-Gate Bit-Exact Verifier
Automated pre-patch and post-patch validation covering:
1. `chunk offsets`: Bit-level stco/co64 sample boundary verification.
2. `sample tables`: Time-to-sample (`stts`) and composition offset (`ctts`) validity.
3. `mobile playback`: iOS AVPlayer and Android MediaCodec container compliance.
4. `mdat payload`: Bit-exact SHA-256 hash matching before and after patching.
5. `video payload`: Frame payload integrity verification.
6. `audio payload`: Audio sample stream preservation.

---

## ⚙️ Patching Presets (X1T Engine)

| Preset | Target Platform | Audio Treatment | Container Structure | Mobile Compatibility | TikTok Bypass |
|---|---|---|---|---|---|
| **X1T For Mobile** *(Default)* | iOS / Android / Web | Original untouched | Valid `moov`, sample tables inside `mdat` | ✅ High (Native AVPlayer / MediaCodec) | ✅ Indeterminate `mvhd` |
| **X1T Hybrid** | PC & Mobile | Bounded tail extension (`<=200ms`) | Valid `moov`, synchronized `tkhd` duration | 🟡 Medium | ✅ Indeterminate `mvhd` |
| **X1T Clean** | Universal / Standard | Pure timing update | Clean `moov` faststart rewrite | ✅ High | ✅ Indeterminate `mvhd` |
| **X1T For PC** *(Legacy)* | PC players only | 10x ghost samples | Indeterminate `mvhd`, trailing bytes | ❌ Low (Fails on mobile decoders) | ✅ Indeterminate `mvhd` |

- **X1T Repair**: One-click lossless repair for corrupted or legacy patched clips (recalculates edit lists, strips ghost samples, repairs chunk offsets).

---

## 🔍 MP4 Forensic Inspector

Open the **Forensic** window to inspect deep container metadata before and after patching:
- **Atom Hierarchy Tree**: Interactive inspection of `ftyp`, `moov` (`mvhd`, `trak`, `mdia`, `minf`, `stbl`), `mdat`, and trailing boxes.
- **Time Scale & FPS Analysis**: Inspect precise media timescale, duration, sample count, and frame rate calculation.
- **Sample Integrity Proof**: Computes and compares SHA-256 hashes of the raw `mdat` sample payload to guarantee that no video frames or audio samples were altered.
- **A/V Sync Deviation**: Displays delta between video track duration and audio track duration in milliseconds.

---

## 🚀 Getting Started

### Method 1: Using Prebuilt Binary
1. Download `FPSPatcherStudio-v0.3.0-Setup.exe` or portable `.zip` from [Releases](https://github.com/x1Swimzft/FPS-Patcher-Studio/releases).
2. Launch `FPSPatcherStudio.exe`.
3. Drag & drop `.mp4` or `.mov` clips into the drop zone.
4. Select desired Target Preset (default: **X1T For Mobile**) or specify a custom timescale.
5. Click **Start Patch**. Patched files will be saved instantly.

### Method 2: Running from Source
Requires [Python 3.11+](https://www.python.org/) and [uv](https://docs.astral.sh/uv/):

```powershell
# Clone repository
git clone https://github.com/x1Swimzft/FPS-Patcher-Studio.git
cd FPS-Patcher-Studio

# Install dependencies and sync virtualenv
uv sync

# Run application
uv run fps-patcher-studio
```

---

## 🛠️ Development & Testing

Run quality gates:
```powershell
# Run unit & integration test suite (187 tests)
uv run pytest -q

# Run static type checking
uv run mypy src tests

# Run code style and linter
uv run ruff check src tests
```

### Building Standalone Distributable
To compile PyInstaller one-folder portable package and Inno Setup installer:
```powershell
powershell -ExecutionPolicy Bypass -File build\release.ps1
```
Build artifacts will be placed in `release/`:
- `FPSPatcherStudio-v0.3.0-Setup.exe`
- `FPSPatcherStudio-v0.3.0-win64.zip`

---

## ⚠️ Important Caveat & Platform Disclaimer

- **Timescale vs Real Frame Rate**: Changing the MP4 container timescale re-expresses frame durations in a new container time unit. It does **not** generate new interpolated frames (a 30 fps recording still contains 30 physical frames per second).
- **Platform Ingest Behavior**: Ingest pipelines of platforms like TikTok, YouTube Shorts, or Instagram Reels are proprietary, server-side, and subject to change without notice. Container modifications do not guarantee platform bypass or resolution upgrades.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
