# FPS Patcher Studio — Future Product Roadmap & Architectural Handoff (v0.6.0 → v1.0.0)

> **Document Status**: Active Engineering Specification  
> **Target Version Horizon**: v0.6.0 – v1.0.0  
> **Current Baseline**: v0.5.0 (Zero-Freeze 8MB Streaming Engine, Mobile Faststart, Safe Audio Preservation)

---

## Executive Summary

FPS Patcher Studio enables high-framerate and high-bitrate video creators to bypass platform transcoding compression while preserving 100% bit-exact media payloads. As of v0.5.0, core ISO-BMFF box manipulation (`mvhd`, `moov`-before-`mdat` faststart, timescale rewriting, and sample table integrity) is fully stabilized, operating with zero GUI freezes and sub-30MB RAM usage.

This document serves as the architectural blueprint and operational handoff for subsequent release milestones spanning **v0.6.0 through v1.0.0**.

---

## Phase 1 (`v0.6.0`): Smart Guard & Auto-Fix Pipeline

**Theme**: Proactive media compatibility and seamless distribution.

### 1.1 Audio Auto-Transcoding Guard (`AAC-LC 48kHz`)
- **Problem**: Non-AAC audio streams (such as PCM/WAV in QuickTime `.mov`, AC-3, EAC-3, or Opus) frequently fail playback on mobile players (ExoPlayer on Android, AVPlayer on iOS) when TikTok bypasses server transcoding.
- **Architecture**:
  - Integrate an automated pre-flight audio inspector into `src/fps_patcher/core/prober.py`.
  - When non-AAC audio or non-standard sample rates are detected, offer or auto-invoke FFmpeg stream-copy remux:
    ```bash
    ffmpeg -i input.mov -c:v copy -c:a aac -b:a 320k -ar 48000 output.mp4
    ```
  - Preserve 100% video bit-exactness (`-c:v copy`) while guaranteeing universally decodable audio.

### 1.2 GPU NVENC Smart Bitrate Limiter (>25 Mbps Guard)
- **Problem**: Videos exceeding 25–30 Mbps often induce client-side network buffering and throttling on cellular networks despite progressive faststart ordering.
- **Architecture**:
  - Detect high-bitrate streams in `prober.py`.
  - Provide an optional one-click hardware-accelerated target bitrate normalization using NVENC (`h264_nvenc` / `hevc_nvenc`) with CQ/VBR caps while keeping high-fidelity visual quality.

### 1.3 In-App Auto-Updater via GitHub Releases
- **Problem**: Users running portable ZIP or standalone EXE builds lack automated update notifications.
- **Architecture**:
  - Implement a lightweight, background GitHub Release checker against `https://api.github.com/repos/x1Swimzft/FPS-Patcher-Studio/releases/latest`.
  - Parse semver tags (`v0.6.0+`), verify SHA-256 release asset signatures against local builds, and display a non-intrusive update badge in the main window toolbar with release notes and one-click download.

---

## Phase 2 (`v0.7.0`): Zero-Click Creator Workflow

**Theme**: Seamless desktop shell integration and automated batch intake.

### 2.1 Watch Folder & System Tray Daemon
- **Architecture**:
  - Leverage `watchdog` to monitor a user-configured export directory (e.g., DaVinci Resolve or Adobe Premiere render folder).
  - Automatically detect completed file writes (`.mp4`, `.mov`), queue them with preset default settings, patch via background worker, and move/save to target output.
  - Minimize to Windows System Tray (`pystray`) with toast notification on batch completion.

### 2.2 Windows Shell Right-Click Context Menu Integration
- **Architecture**:
  - Register lightweight HKCU registry keys:
    ```text
    HKEY_CURRENT_USER\Software\Classes\*\shell\FPSPatcherStudio
    @="Quick Patch with X1T"
    "Icon"="<install_dir>\\FPSPatcherStudio.exe,0"
    HKEY_CURRENT_USER\Software\Classes\*\shell\FPSPatcherStudio\command
    @="\"<install_dir>\\FPSPatcherStudio.exe\" --quick-patch \"%1\""
    ```
  - Enable instant, single-click video patching directly from Windows File Explorer without opening the full UI.

### 2.3 `colr` Atom (BT.709) Tagging & Metadata Sanitizer
- **Architecture**:
  - Guarantee accurate color gamut rendering on mobile OLED displays by ensuring a valid `colr` atom with primaries index `1` (BT.709), transfer `1` (BT.709), and matrix `1` (BT.709).
  - Strip tracking metadata, personal EXIF/location tags, and proprietary editor tags from `moov.udta` before distribution.

---

## Phase 3 (`v0.8.0`): Multi-Platform Presets & Pre-Flight Score

**Theme**: Multi-network expansion and real-time validation scoring.

### 3.1 Dedicated Multi-Platform Profiles
- **Instagram Reels Preset**:
  - Calibrated for Meta CDN ingest parameters (safe frame boundary, standard `stss` keyframe layout, maximum audio bitrate compatibility).
- **YouTube Shorts Preset**:
  - Optimized for VP9/AV1 auto-upgrade trigger on 60 FPS vertical video streams.

### 3.2 Visual Pre-Flight Readiness Score (0–100)
- **Architecture**:
  - Render an interactive gauge/badge on each queue item card:
    - **Faststart (`moov` before `mdat`)**: +25 pts
    - **Standard AAC 48kHz Audio**: +25 pts
    - **Bitrate (<20 Mbps)**: +25 pts
    - **Timescale Alignment (60,000 / 60 FPS)**: +25 pts
  - Immediate visual feedback on whether a video is 100% ready for zero-transcode mobile playback.

---

## Phase 4 (`v1.0.0`): Native Engine Compilation & Headless CLI

**Theme**: Industrial-grade distribution, zero false positives, and automation API.

### 4.1 Native C++ Compilation via Nuitka
- **Architecture**:
  - Migrate release artifact pipeline from PyInstaller to Nuitka with MSVC C++ compiler:
    ```powershell
    nuitka --standalone --windows-console-mode=disable --enable-plugin=tk-inter fps_patcher
    ```
  - Eliminate temporary runtime extraction (`_MEIxxxxxx`), resulting in:
    - **0/70 False Positives on VirusTotal**
    - **3x Faster Cold Startup** (<0.4 seconds)
    - Full binary Authenticode code signing with internal C++ symbol protection.

### 4.2 Headless CLI & Local IPC / REST API
- **Architecture**:
  - Implement a CLI sub-command mode (`fps-patcher --cli --preset bxd-mobile --input video.mp4 --output patched.mp4`).
  - Provide an optional local lightweight REST/WebSocket daemon on `localhost` for external scripts, video editing plugins (DaVinci Resolve Lua/Python scripts), and rendering pipelines.

---

## Release Milestone Summary Matrix

| Milestone | Target Scope | Key Deliverables | Risk Level |
|---|---|---|---|
| **v0.6.0** | Smart Guard & Auto-Fix | AAC Auto-Transcode, NVENC 25Mbps Limiter, GitHub Auto-Updater | Low |
| **v0.7.0** | Creator Workflow | Watch Folder, Explorer Context Menu, `colr` BT.709 Tagging | Medium |
| **v0.8.0** | Multi-Platform & Scoring | IG Reels / YT Shorts Presets, 0–100 Pre-Flight Badge | Low |
| **v1.0.0** | Native Engine & CLI | Nuitka C++ Native Build (0/70 VT), Headless CLI, Resolve Plugin Hook | Medium |
