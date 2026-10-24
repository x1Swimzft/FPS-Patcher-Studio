# Clean-Windows Testing Protocol & QA Runbook

FPS Patcher Studio is designed to run out-of-the-box on standard Windows 10 and Windows 11 machines without requiring Python, developer tooling, or administrator privileges.

This document details the rigorous testing protocol for validating release builds on clean Windows installations.

---

## 1. Test Environment Matrix

| Target OS | Build / Version | User Privileges | Architecture | Isolation Method |
| :--- | :--- | :--- | :--- | :--- |
| **Windows Sandbox** | Windows 10 21H2+ / Windows 11 | Standard (Sandbox User) | x64 | Windows Sandbox `.wsb` |
| **Windows 11 Clean VM** | 23H2 / 24H2 Fresh ISO | Standard Non-Admin User | x64 | Hyper-V / VMware Workstation |
| **Windows 10 Clean VM** | 21H2 / 22H2 Fresh ISO | Standard Non-Admin User | x64 | Hyper-V / VirtualBox |

> [!IMPORTANT]
> The test system **must not** have Python, `uv`, Git, or Visual Studio C++ build tools installed in `%PATH%` or machine registry.

---

## 2. Test Artifacts Preparation

Prior to test execution, generate release artifacts using:
```powershell
powershell -ExecutionPolicy Bypass -File build\release.ps1 -Sign -GenerateSelfSigned
```
Ensure the following artifacts are available in `release/`:
1. `FPSPatcherStudio-v<version>-win64.zip` (Portable release)
2. `FPSPatcherStudio-v<version>-Setup.exe` (Inno Setup single-user / system installer)
3. `FPSPatcherStudio-v<version>.sha256` (Integrity checksum manifest)

Test media samples to prepare:
- `sample_60fps.mp4` (H.264/AVC + AAC, standard 60.0 fps, 1080p)
- `sample_120fps.mp4` (HEVC/H.265, 120.0 fps high-framerate, 1080p/4K)
- `sample_broken_moov.mp4` (Truncated or fragmented MP4 for forensic/repair testing)

---

## 3. Test Phase 1: Installation & Permission Boundaries

### 3.1 Non-Admin Inno Setup Installer (`-Setup.exe`)
- [ ] **Execution**: Double-click `FPSPatcherStudio-v<version>-Setup.exe` under a Standard User account.
- [ ] **UAC Prompt Verification**: Verify that **no UAC elevation prompt** (Shield icon) is triggered.
- [ ] **Install Location**: Default installation target must point to `{autopf}\FPS Patcher Studio` (evaluates to `%LOCALAPPDATA%\Programs\FPS Patcher Studio` under non-admin).
- [ ] **Desktop & Start Menu Shortcuts**: Verify shortcuts are created in user Start Menu (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\FPS Patcher Studio`).
- [ ] **Process Termination & Setup Log**: Complete wizard, verify installer exits with code `0` and generates `Setup Log <date>.txt` in `%TEMP%`.

### 3.2 Portable Archive (`.zip`)
- [ ] **Extraction**: Extract `.zip` into a user-owned folder (e.g. `C:\Users\<user>\Desktop\FPSPatcherStudio`).
- [ ] **Zone.Identifier Handling**: Verify user experience when running executable extracted from downloaded archive (Mark-of-the-Web).
- [ ] **Zero Registry Pollution**: Verify extracting and opening the portable version creates no registry keys in `HKLM`.

---

## 4. Test Phase 2: Cold-Start & Runtime Dependencies

### 4.1 Dependency Self-Containment
- [ ] **No System Python**: Confirm `python.exe` is absent from CMD / PowerShell.
- [ ] **Bundled DLLs**: Launch `FPSPatcherStudio.exe`. Verify process loads `python311.dll`, `VCRUNTIME140.dll`, `tcl86t.dll`, and `tk86t.dll` exclusively from `_internal\`.
- [ ] **Security Context**: Open Task Manager or Process Explorer:
  - Verify Integrity Level is **Medium** (Standard User `asInvoker`).
  - Verify `uiAccess` is `false`.
  - Verify DEP (Data Execution Prevention) and ASLR (Address Space Layout Randomization) are active.

### 4.2 Display & Window Manager (DWM) Integration
- [ ] **Per-Monitor V2 DPI Scaling**: Move the window between a 100% DPI monitor and a 125%/150%/200% high-DPI display.
  - Verify fonts and icons render crisply with zero blurry bitmap scaling.
  - Verify bundled Inter fonts (`Inter-Regular.ttf`, `Inter-SemiBold.ttf`) are active.
- [ ] **Mica / Acrylic / Dark Title Bar**: Verify `pywinstyles` applies dark title bar on Windows 10/11 without crashing.
- [ ] **Windows Defender / SmartScreen**:
  - Test initial launch with Windows Defender Real-time Protection enabled.
  - Verify binary is not flagged by generic heuristics (no UPX packing, valid assembly manifest).

---

## 5. Test Phase 3: Interactive Functional Validation

### 5.1 Drag & Drop (TkinterDnD2)
- [ ] **Single File Drag**: Drag `sample_60fps.mp4` from Windows Explorer into the drop zone.
  - Confirm drop target highlights with accent border.
  - Confirm file metadata parses (resolution, duration, fps, codec).
- [ ] **Batch Drag**: Drag 5 video files simultaneously into the queue.
  - Confirm all 5 items appear sequentially without UI freeze.
- [ ] **Invalid File Drag**: Drag `.txt` or `.exe` file into the app.
  - Confirm clean validation rejection message without unhandled traceback.

### 5.2 Patching Workflows
- [ ] **Preset 1: X1T PC (`x1t-pc` / `bxd-pc`)**:
  - Select `sample_60fps.mp4`, apply X1T PC preset.
  - Click "Start Patch".
  - Verify output file created in target output directory.
  - Verify container patches timescale (e.g., 60000 timescale atom adjusted, ghost audio tracks added).
- [ ] **Preset 2: X1T Mobile (`x1t-mobile` / `bxd-mobile`)**:
  - Patch 60fps/120fps video for mobile compatibility.
  - Verify patched video plays in Windows "Movies & TV" (Films & TV) and Windows Media Player.
- [ ] **Preset 3: X1T Hybrid & Clean**:
  - Patch high-framerate 120fps video with X1T Clean (timescale adjusted, audio untouched).
  - Verify audio/video sync remains sample-accurate.
- [ ] **Preset 4: X1T Repair**:
  - Run repair preset on non-standard/damaged container.
  - Verify file is rebuilt or safe error is reported.

### 5.3 FFmpeg Integration & Downloader
- [ ] **Bundled / Portable FFmpeg**: Place `ffmpeg.exe` and `ffprobe.exe` in `bin\` next to executable or `_internal\bin\`.
  - Verify app detects FFmpeg immediately and shows green status indicator.
  - Verify video thumbnail generation works.
- [ ] **Absence Fallback**: Run without FFmpeg binaries.
  - App must not crash. Direct-atom patching must operate with 100% capability.
  - Thumbnail generator falls back to graceful placeholder icon.

---

## 6. Test Phase 4: Persistence & Storage Isolation

### 6.1 Application Data (`%APPDATA%\FPSPatcherStudio`)
- [ ] Verify directory is created on first launch:
  ```powershell
  Test-Path "$env:APPDATA\FPSPatcherStudio"
  ```
- [ ] **Settings Persistence**:
  1. Open Settings modal.
  2. Change Theme (e.g. from Dark to Amber Warm or Obsidian).
  3. Change Language (English -> Thai).
  4. Change Default Output Directory.
  5. Close application.
  6. Relaunch: Confirm all settings, theme, and language persist identically.
- [ ] **Settings JSON Integrity**:
  - Verify `%APPDATA%\FPSPatcherStudio\settings.json` is formatted as valid UTF-8 JSON.
  - Verify atomic write strategy (no zero-byte corruption if process killed during write).
- [ ] **Session Logs**:
  - Verify log files in `%APPDATA%\FPSPatcherStudio\logs\` record events with correct timestamps and log levels.

---

## 7. Test Phase 5: Clean Uninstallation & Teardown

### 7.1 Inno Setup Uninstaller
- [ ] **Launch Uninstaller**: Run `unins000.exe` from `%LOCALAPPDATA%\Programs\FPS Patcher Studio` or Windows Settings > Apps > Installed apps.
- [ ] **No Admin Elevation**: Verify uninstallation proceeds cleanly without UAC prompts.
- [ ] **File Removal**: Verify application executable, `_internal\` folder, fonts, and shortcuts are completely deleted.
- [ ] **Process Safety**: Verify uninstaller detects if app is running and prompts user to close it before deletion.

### 7.2 Portable Cleanup
- [ ] Delete portable folder: Verify no locked files or background lingering processes prevent instant deletion.
- [ ] User data cleanup: Verify `%APPDATA%\FPSPatcherStudio` can be cleared manually by user.

---

## 8. QA Test Sign-Off Checklist

| Test Case ID | Test Description | Expected Result | Pass / Fail | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **TC-WIN-01** | Non-admin setup installer | Installs into `%LOCALAPPDATA%`, no UAC prompt | [ ] Pass | |
| **TC-WIN-02** | Cold start without Python | UI loads in < 2 seconds, no missing DLL dialogs | [ ] Pass | |
| **TC-WIN-03** | Manifest execution level | Runs as `asInvoker` (Medium Integrity) | [ ] Pass | Verified via Process Explorer |
| **TC-WIN-04** | Windows 10/11 DWM theme | Dark title bar active, no visual artifacts | [ ] Pass | |
| **TC-WIN-05** | Per-Monitor V2 High-DPI | Crisp text on 100%, 150%, 200% displays | [ ] Pass | Inter font rendered |
| **TC-WIN-06** | TkinterDnD2 Drag & Drop | Dragging MP4 from Explorer enqueues items | [ ] Pass | |
| **TC-WIN-07** | 60fps & 120fps Patching | Output files playable, timestamps patched | [ ] Pass | Atom patching verified |
| **TC-WIN-08** | Settings persistence | `%APPDATA%\FPSPatcherStudio\settings.json` persistent | [ ] Pass | |
| **TC-WIN-09** | FFmpeg optional status | Core patching works without FFmpeg; thumbnails if present | [ ] Pass | |
| **TC-WIN-10** | Uninstaller removal | Zero leftover binaries or registry dead-links | [ ] Pass | |

---

*Sign-off Date*: ____________________  
*QA Tester / Engineer*: ____________________  
*App Version Tested*: `0.4.0`
