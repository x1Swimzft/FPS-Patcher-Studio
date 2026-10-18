# FPS Patcher Studio

<div align="center">

![Version](https://img.shields.io/badge/version-v0.2.1--beta-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%2064--bit-0078D6.svg?logo=windows&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Lossless](https://img.shields.io/badge/processing-lossless%20%E2%80%A2%20zero%20re--encode-brightgreen.svg)

**High-precision MP4/MOV container timing patcher with modern Windows translucent glass UI.**  
*Direct ISO-BMFF atom rewriting • Bit-exact sample preservation • Sub-second processing*

[📥 Downloads](#-downloads-v021-beta) • [✨ Key Features](#-key-features) • [⚙️ Presets](#️-patching-presets) • [🔍 Forensic Inspector](#-mp4-forensic-inspector) • [🚀 Getting Started](#-getting-started)

</div>

---

## 📖 Overview

**FPS Patcher Studio** is a specialized desktop engineering utility designed to manipulate ISO-BMFF (`.mp4`, `.mov`) container timing headers directly at the binary atom level. 

Unlike traditional video converters or FFmpeg stream copying, FPS Patcher Studio:
- **Zero Re-encoding**: Never touches the underlying H.264/HEVC video bitstream or AAC audio stream.
- **100% Lossless Quality**: Preserves the original `mdat` payload bit-for-bit with zero compression artifacts or generation loss.
- **Blazing Fast**: Patches multi-gigabyte video files in milliseconds by rewriting header atoms (`moov`, `mvhd`, `tkhd`, `mdhd`, `stts`, `ctts`, `edts/elst`) directly on disk.
- **Cross-Platform Compatibility**: Offers targeted presets engineered for both modern mobile hardware decoders (iOS AVPlayer, Android MediaCodec) and PC video players.

---

## 📥 Downloads (v0.2.1-beta)

| Distribution | File | Architecture | Description |
|---|---|---|---|
| **Installer** | [FPSPatcherStudio-v0.2.1-beta-Setup.exe](https://github.com/x1Swimzft/FPS-Patcher-Studio/releases/download/v0.2.1-beta/FPSPatcherStudio-v0.2.1-beta-Setup.exe) | Windows x64 | Standard installer with desktop shortcut & uninstaller |
| **Portable** | [FPSPatcherStudio-v0.2.1-beta-win64.zip](https://github.com/x1Swimzft/FPS-Patcher-Studio/releases/download/v0.2.1-beta/FPSPatcherStudio-v0.2.1-beta-win64.zip) | Windows x64 | Standalone zip — extract and run `FPSPatcherStudio.exe` |

---

## ✨ Key Features

- **Translucent Glass Interface**: Built with modern Windows 10/11 DWM Acrylic / Mica backdrop blur, custom dark glass surfaces, and responsive layout.
- **Batch Processing Queue**:
  - Drag-and-drop multiple video clips or directories.
  - Per-item selection checkboxes: patch only selected clips or the entire batch.
  - Smart `Select All` / `Deselect All` toggle button.
  - Real-time probe status, duration, and FPS detection.
- **Lossless Preset Engine**:
  - **BXD Mobile (`bxd-mobile`)** *(Default)*: Full ISO-BMFF compliant container timing reconstruction, standard `free` box padding, mobile hardware decoder compatible.
  - **BXD Hybrid (`bxd-hybrid`)**: Bounded last-sample audio tail extension (`<= 200ms`) with valid chunk offsets and container padding.
  - **BXD Clean (`bxd-clean`)**: Clean header rewrite (`faststart`) with pristine timescale recalculations.
  - **BXD PC (`bxd-pc`)**: Legacy experimental PC trick mode with indeterminate duration and audio ghost inflation.
- **Mobile Repair Utility**: One-click lossless repair for corrupted or legacy BXD-patched clips (recalculates edit lists, strips ghost samples, repairs chunk offsets).
- **MP4 Forensic Analyzer**: Deep atom tree viewer, payload verification (`mdat` SHA-256 validation), AV sync analysis, and platform compliance checks.
- **Diagnostic Logging**: Automated log rotation (`%APPDATA%\FPSPatcherStudio\logs\`), sensitive local path masking, and one-click diagnostic bundle export.

---

## ⚙️ Patching Presets

| Preset | Target Platform | Audio Treatment | Container Structure | Mobile Compatibility |
|---|---|---|---|---|
| **BXD Mobile** *(Default)* | iOS / Android / Web | Original untouched | Valid `moov`, `free` padding box | ✅ High (Native AVPlayer / MediaCodec) |
| **BXD Hybrid** | PC & Mobile | Bounded tail extension (`<=200ms`) | Valid `moov`, valid chunk offsets | 🟡 Medium |
| **BXD Clean** | Universal / Standard | Pure timing update | Clean `moov` faststart rewrite | ✅ High |
| **BXD PC** *(Legacy)* | PC players only | 10x ghost samples | Indeterminate `mvhd`, trailing bytes | ❌ Low (Fails on mobile decoders) |

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
1. Download `FPSPatcherStudio-v0.2.1-beta-Setup.exe` or portable `.zip` from [Releases](https://github.com/x1Swimzft/FPS-Patcher-Studio/releases).
2. Launch `FPSPatcherStudio.exe`.
3. Drag & drop `.mp4` or `.mov` clips into the drop zone.
4. Select desired Target Preset (default: **BXD Mobile**) or specify a custom timescale.
5. Click **⚡ START PATCH**. Patched files will be saved instantly.

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
# Run unit & integration test suite (109 tests)
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
- `FPSPatcherStudio-v0.2.1-beta-Setup.exe`
- `FPSPatcherStudio-v0.2.1-beta-win64.zip`

---

## ⚠️ Important Caveat & Platform Disclaimer

- **Timescale vs Real Frame Rate**: Changing the MP4 container timescale re-expresses frame durations in a new container time unit. It does **not** generate new interpolated frames (a 30 fps recording still contains 30 physical frames per second).
- **Platform Ingest Behavior**: Ingest pipelines of platforms like TikTok, YouTube Shorts, or Instagram Reels are proprietary, server-side, and subject to change without notice. Container modifications do not guarantee platform bypass or resolution upgrades.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
