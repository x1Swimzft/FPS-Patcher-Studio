# FPS Patcher Studio

<div align="center">

![Version](https://img.shields.io/badge/version-v1.0.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%2064--bit-0078D6.svg?logo=windows&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Lossless](https://img.shields.io/badge/processing-lossless%20%E2%80%A2%20zero%20re--encode-brightgreen.svg)

**High-precision MP4/MOV container timing patcher with Apple macOS HIG desktop aesthetic and lossless color preservation.**  
*Direct ISO-BMFF atom rewriting • Bit-exact sample preservation • Sub-second processing • X1T Engine*

[📥 Downloads](#-downloads-v100) • [🛡️ Security & Integrity](#️-security-provenance--virustotal-transparency) • [✨ Key Features](#-key-features) • [⚙️ Presets](#️-patching-presets-x1t-engine) • [🔍 Forensic Inspector](#-mp4-forensic-inspector) • [🚀 Getting Started](#-getting-started)

</div>

---

## 📖 Overview

**FPS Patcher Studio** is a specialized desktop engineering utility designed to manipulate ISO-BMFF (`.mp4`, `.mov`) container timing headers directly at the binary atom level. 

Unlike traditional video converters or FFmpeg stream copying, FPS Patcher Studio:
- **Zero Re-encoding**: Never touches the underlying H.264/HEVC video bitstream or AAC audio stream.
- **100% Lossless Quality**: Preserves the original `mdat` payload bit-for-bit with zero compression artifacts or generation loss.
- **Zero-Freeze Streaming Engine**: Employs an 8MB chunked streaming writer and boundary-sampled verification (<2ms) reducing peak memory usage to <30MB even on 10GB+ video files.
- **Faststart Across All Engines**: Enforces progressive streaming layout (`ftyp` → `moov` → `mdat`) across both Direct Atom and X1T engines with recalculated `stco`/`co64` offsets.
- **Watch Folder Auto-Intake**: Monitors creator export folders in the background, debounces active rendering, and auto-queues finished clips.
- **Windows Shell Integration**: One-click "Quick Patch with FPS Patcher Studio" directly from Windows Explorer right-click context menu.
- **Lossless Rec.709 Color Guard**: Detects and injects `colr`/`nclx` color metadata atoms into video tracks so colors remain identical across QuickTime, iOS, Android, and Chromium browsers.
- **X1T Engine & Platform Bypass**: Powered by the **X1T Engine**, enabling TikTok bypass via indeterminate `mvhd` container headers while preserving exact sample tables and track durations for mobile players (iOS AVPlayer, Android ExoPlayer).
- **Mobile Buffering Guard**: Proactively audits source video bitrates (>25 Mbps) and non-AAC audio codecs (e.g. PCM) to prevent infinite buffering spinners and missing audio after TikTok upload.
- **Container Normalization**: Automatically converts QuickTime `.mov` containers to compliant `.mp4` with synthetic ISO-BMFF `ftyp` atoms (`mp42`/`isom`).

---

## 📥 Downloads (v1.0.0)

| Distribution | File | Architecture |
|---|---|---|
| **Installer** | [FPSPatcherStudio-v1.0.0-Setup.exe](https://github.com/x1Swimzft/FPS-Patcher-Studio/releases/download/v1.0.0/FPSPatcherStudio-v1.0.0-Setup.exe) | Windows x64 |
| **Portable** | [FPSPatcherStudio-v1.0.0-win64.zip](https://github.com/x1Swimzft/FPS-Patcher-Studio/releases/download/v1.0.0/FPSPatcherStudio-v1.0.0-win64.zip) | Windows x64 |

The links only resolve after v1.0.0 is published. Until then, build from source
(`build/release.ps1`) or use the artifacts produced by that script in `release/`.
Approximate sizes: installer ~84 MB, portable zip ~117 MB, one-folder build ~323 MB
(189 files). Exact sizes and hashes are in `FPSPatcherStudio-v1.0.0.sha256` and
`FPSPatcherStudio-v1.0.0.manifest.json`, which are generated from the artifacts
themselves and therefore are the authoritative numbers.

---

## 🛡️ Security, Provenance & VirusTotal Transparency

FPS Patcher Studio is open source and built from this repository with
`build/release.ps1` (PyInstaller + Inno Setup). The v1.0.0 artifacts are
**unsigned**: no VirusTotal "clean" claim is made here, and none should be
inferred. Verify the SHA-256 hash before running anything:

```powershell
certutil -hashfile FPSPatcherStudio-v1.0.0-Setup.exe SHA256
Get-Content FPSPatcherStudio-v1.0.0.sha256
```

### Understanding False Positives & Code Signing
- **Heuristic false positives**: PyInstaller embeds a compressed Python archive in a PE wrapper. Machine-learning heuristics can misclassify new, unrated binaries. This risk is reduced by Authenticode signing and download reputation, not by "zero detections" claims.
- **Authenticode signature**: v1.0.0 is unsigned while the project applies for free code signing through SignPath Foundation. Older v0.7.0 builds used a project self-signed developer certificate (`CN=FPS Patcher Studio (Dev)`) and are not trusted by public certificate roots.
- **Formal dispute dossier**: vendor whitelisting disputes and templates are documented in [docs/FALSE_POSITIVE_DISPUTES.md](docs/FALSE_POSITIVE_DISPUTES.md).

### Code signing policy
Free code signing provided by SignPath.io, certificate by SignPath Foundation.
The certificate is issued to SignPath Foundation, not to the maintainer. Releases
are signed only after a manual approval of the signing request; the v1.0.0
artifacts predate that approval and remain unsigned.

| Role | Member |
|---|---|
| **Committer** | [`@x1Swimzft`](https://github.com/x1Swimzft) |
| **Reviewer** | [`@x1Swimzft`](https://github.com/x1Swimzft) |
| **Approver** | [`@x1Swimzft`](https://github.com/x1Swimzft) |

- Signing policy: [docs/CODE_SIGNING_POLICY.md](docs/CODE_SIGNING_POLICY.md)
- SignPath integration and signing process: [docs/CODE_SIGNING_SIGNPATH.md](docs/CODE_SIGNING_SIGNPATH.md)
- Privacy policy: [docs/PRIVACY.md](docs/PRIVACY.md)

### Privacy & network access
No telemetry, analytics, or crash reporting. Media files are processed locally
and never uploaded. The app makes network requests only when (1) the optional
startup update check contacts GitHub release metadata, and (2) you explicitly
request an FFmpeg download, which fetches a BtbN build from GitHub. No other
network access occurs. Full policy: [docs/PRIVACY.md](docs/PRIVACY.md).

### How to Verify Downloaded Binaries
Open PowerShell and verify the SHA-256 hash before running:
```powershell
# Compare each file's hash with the matching line in the published sidecar
Get-FileHash -Path "FPSPatcherStudio-v1.0.0-Setup.exe" -Algorithm SHA256
Get-FileHash -Path "FPSPatcherStudio-v1.0.0-win64.zip" -Algorithm SHA256
Get-Content "FPSPatcherStudio-v1.0.0.sha256"
```

The build also writes `release/FPSPatcherStudio-v1.0.0.sha256`,
`release/FPSPatcherStudio-v1.0.0.manifest.json` and a CycloneDX SBOM at
`release/FPSPatcherStudio-v1.0.0.cdx.json`.

### Security & Compliance Resources
- 🔒 **[SECURITY.md](SECURITY.md)**: Vulnerability disclosure policy, response SLA, and safe harbor.
- 🔏 **[docs/CODE_SIGNING_POLICY.md](docs/CODE_SIGNING_POLICY.md)**: Code signing policy and SignPath Foundation attribution.
- 🔐 **[docs/PRIVACY.md](docs/PRIVACY.md)**: Local data handling and network access disclosure.
- 🏗️ **[BUILDING.md](BUILDING.md)**: Reproducible step-by-step build instructions from source.
- 📜 **[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)**: Licenses for bundled components, Inter font, and FFmpeg LGPL/GPL compliance.
- 📑 **[docs/FALSE_POSITIVE_DISPUTES.md](docs/FALSE_POSITIVE_DISPUTES.md)**: Complete vendor dispute dossier and email templates.

---

## ✨ Key Features

### 🖥️ Qt Desktop Interface & Zero-Flicker Architecture
- **Bundled Inter Typography**: Inter (`Regular`, `Medium`, `SemiBold`, `Bold`) loaded privately at startup through `QFontDatabase.addApplicationFont` with seamless Thai fallback (`Noto Sans Thai`, `Segoe UI Variable`).
- **Semantic Color Palette**: 100% opaque surfaces with Apple HIG semantic colors (`#1D1D1F`/`#D9D9DC` primary text, `#007AFF`/`#0A84FF` system blue, `#34C759`/`#30D158` system green, `#FF9500`/`#FF9F0A` system amber, `#FF3B30`/`#FF453A` system red, and crisp 1px hairline borders).
- **Zero-Flicker Window Restore**: Qt double-buffered rendering with a solid dark surface and native Windows 10/11 dark title bar (`DWMWA_USE_IMMERSIVE_DARK_MODE` + `DWMWA_CAPTION_COLOR`), eliminating black boxes and flashing on Alt-Tab.
- **Vector-Crisp Dual-Tone Icons**: Clean 32x32 @2x (1.5px stroke) Phosphor/Lucide-style PNG icons loaded as `QIcon`/`QPixmap` replacing all emoji/ASCII glyphs.
- **Animated Sliding Pill Controls**: Qt `SegmentedControl` (`60 / 120 / Custom`) with a smooth 200ms cubic ease-out sliding capsule thumb (`1 - (1 - t)**3`) and `reduce_motion` instant snap support.
- **Animated Activity Console Drawer**: Smooth 200ms ease-out expand/collapse drawer (`40px` <-> `210px`) with primary action cluster (`FFmpeg logs`, `Copy`, `Clear`, `Save Log`) and overflow menu.
- **Window Focus-Aware Queue Selection**: Selected queue cards fill solid Accent Blue (`#007AFF`/`#0A84FF`) with white text when window is active, automatically transitioning to macOS Unfocused Grey (`#3A3A3C`/`#D1D1D6`) when window loses OS focus.
- **Keyboard Focus Rings & Accessibility**: 2px System Blue focus border, accessible names on interactive controls, and contrast-checked light/dark palettes.
- **Seven Color Presets**: Crimson Gamer is the default for new installs; light/dark and English/Thai are switchable at runtime.

### ⚡ Batch Processing Queue & Automation
- Drag-and-drop multiple video clips or directories using Qt's native file drop events.
- Queue rows render FFmpeg thumbnails asynchronously.
- Inline per-item overrides (timescale, preset) in the inspector, alongside the batch preset.
- Per-item selection checkboxes: patch only selected clips or the entire batch.
- Real-time probe status, duration, resolution, and FPS detection.
- **Watch Folder Auto-Intake**: Monitors designated creator render directories, automatically staging clips upon export completion.
- **Windows Explorer Shell Integration**: Right-click any video or folder to patch instantly via system context menu.
- Pinned inspector footer: progress bars and action buttons remain pinned so Source Metadata is never pushed below the fold.

### 🛡️ 6-Gate Bit-Exact Verifier & Streaming Engine
Automated pre-patch and post-patch validation covering:
1. `chunk offsets`: Bit-level `stco`/`co64` sample boundary verification and automatic faststart healing.
2. `sample tables`: Time-to-sample (`stts`) and composition offset (`ctts`) validity.
3. `mobile playback`: iOS AVPlayer and Android MediaCodec container compliance.
4. `color guard`: Lossless Rec.709 `colr`/`nclx` parameter preservation.
5. `mdat payload`: Bit-exact SHA-256 hash matching before and after patching.
6. `audio payload`: Safe audio sample preservation with zero ghost frames.

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
- **Color Parameters**: Detailed inspection of `colr`/`nclx` primaries, transfer characteristics, and matrix coefficients.
- **Time Scale & FPS Analysis**: Inspect precise media timescale, duration, sample count, and frame rate calculation.
- **Sample Integrity Proof**: Computes and compares SHA-256 hashes of the raw `mdat` sample payload to guarantee that no video frames or audio samples were altered.
- **A/V Sync Deviation**: Displays delta between video track duration and audio track duration in milliseconds.

---

## 🚀 Getting Started

### Method 1: Using Prebuilt Binary
1. Download `FPSPatcherStudio-v1.0.0-Setup.exe` or the portable `.zip` from [Releases](https://github.com/x1Swimzft/FPS-Patcher-Studio/releases).
2. Launch `FPSPatcherStudio.exe`.
3. Drag & drop `.mp4`, `.mov` or `.m4v` clips into the drop zone (or right-click in Windows Explorer).
4. Select the target preset (default: **X1T For Mobile**) or specify a custom timescale.
5. Click **Start Patch**. Patched files are saved next to the source or in the configured output folder.

### Method 3: Headless CLI
```powershell
FPSPatcherStudio.exe --cli patch "clip.mp4" --preset 60 --output out --json
FPSPatcherStudio.exe --cli probe "clip.mp4" --json
FPSPatcherStudio.exe --cli score "clip.mp4" --profile tiktok --json
```
Run it from cmd/PowerShell: a windowed build attaches to the parent console. Exit codes are
0 (ok), 1 (file failure), 2 (usage) and 130 (cancelled). See `BUILDING.md` §7.

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
# Run the full Qt test suite
uv run pytest -q

# Run static type checking
uv run mypy src tests tools

# Run code style and linter
uv run ruff check src tests
```

### Building Standalone Distributable
To compile the PySide6 PyInstaller one-folder portable package and Inno Setup installer:
```powershell
powershell -ExecutionPolicy Bypass -File build\release.ps1
```
Build artifacts will be placed in `release/`:
- `FPSPatcherStudio-v0.7.0-Setup.exe`
- `FPSPatcherStudio-v0.7.0-win64.zip`

---

## ⚠️ Important Caveat & Platform Disclaimer

- **Timescale vs Real Frame Rate**: Changing the MP4 container timescale re-expresses frame durations in a new container time unit. It does **not** generate new interpolated frames (a 30 fps recording still contains 30 physical frames per second).
- **Platform Ingest Behavior**: Ingest pipelines of platforms like TikTok, YouTube Shorts, or Instagram Reels are proprietary, server-side, and subject to change without notice. Container modifications do not guarantee platform bypass or resolution upgrades.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
