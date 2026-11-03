# Handoff & Product Roadmap — FPS Patcher Studio (`v0.5.1` ➔ `v1.2.1`)

**Generated**: 2026-10-24  
**Repository**: `https://github.com/x1Swimzft/FPS-Patcher-Studio`  
**Workspace**: `E:\Project\fps-patcher-studio`  
**Current Base Version**: `v1.2.1` (2026-11-03)

> **Status at v1.2.1:** Qt (PySide6) is the only UI; the Tk/CustomTkinter UI is
> gone. Phase 1 shipped in v0.6.0 and still lives in `core/preflight.py`,
> `core/patcher.py` and `core/updater.py` — no rewrite is needed. Phase 2 (watch
> folder, Explorer verb, Rec.709 color guard, metadata scrub) and Phase 3
> (platform profiles + readiness) are delivered, and the headless CLI (4.2) is
> live. Nuitka (4.1) was evaluated but **not adopted**: see
> `docs/NUITKA_EVALUATION.md` for the checklist and why no build was measured in
> this environment. The v1.2.0 release is published but **unsigned**; v1.2.1 is
> source-only and has not been built or tagged. The v0.5.1
> Tk analysis below is kept as history and no longer describes the code.

---

## 🗄️ Historical (`v0.5.1`): หน้าจอดำแล้วค่อยๆ วาดทีละเมนูเวลาพับจอ (Minimize / Restore / Alt+Tab)

> **History only.** This section describes the removed Tk/CustomTkinter UI and is
> kept for the record. It no longer matches `src/fps_patcher/ui_qt/`; do not use
> these file paths or fixes as current guidance.

### 1. วิเคราะห์สาเหตุ (Root Cause Analysis)
จากภาพหน้าจอที่เกิดอาการพื้นหลังดำสนิท เห็นแค่แถบสีน้ำเงินบางส่วนแล้วค่อยๆ วาด Widget ทีละชิ้นเมื่อพับจอไปมา เกิดจากจุดอ่อนของ **Tkinter / CustomTkinter บน Windows 10/11 (DWM)** ร่วมกับโค้ดใน `src/fps_patcher/ui/theme.py` และ `src/fps_patcher/ui/main_window.py` ดังนี้:

1. **Windows DWM Backdrop (Mica / Acrylic) ชนกับ Single-Threaded GDI ของ Tkinter (`ui/theme.py`)**:
   - เมื่อเปิดใช้ `DWMWA_SYSTEMBACKDROP_TYPE` (Acrylic/Mica) หรือตั้งค่าความโปร่งใส/สีพื้นหลังผ่าน `ctypes.windll.dwmapi` เวลาพับจอ (Minimize) Windows DWM จะล้าง Surface Buffer ทิ้ง พอเปิดกลับขึ้นมา (Restore / `<Map>`) DWM จะระบายพื้นหลังเป็นสีดำ (`#000000`) ก่อน แล้วรอให้ Tkinter วาด `<Canvas>` ทับทีละตัว
2. **การเรียก `.configure()` หรือ `render()` ซ้ำๆ ใน `<Configure>` Event (`ui/main_window.py` & `ui/input_list.py`)**:
   - เวลาพับจอหรือขยายจอ Tkinter จะยิง `<Configure>` และ `<Map>` รัวๆ ถ้ามีโค้ดที่ไปสั่งคำนวณขนาดการ์ดหรือสั่ง ре-render `CTkScrollableFrame` ในจังหวะที่หน้าต่างกำลัง Restore จะทำให้ Main Thread บล็อกการ Repaint ของ Windows จนเห็นเป็นจอดำค้างแล้วค่อยๆ ขึ้นทีละปุ่ม
3. **ไม่ได้ใช้ `WS_EX_COMPOSITED` (Double-Buffered Window Style) บน Windows**:
   - โดยปกติหน้าต่าง `tk.Tk` บน Windows ไม่ได้เปิดใช้ Hardware Double-Buffering (`WS_EX_COMPOSITED = 0x02000000`) ของ Win32 API ทำให้เวลาหน้าต่างมี `CTkFrame` และ `CTkButton` ซ้อนกันหลายชั้น (Nested Canvases) Windows จะวาดทีละเลเยอร์ต่อหน้าต่อตาผู้ใช้ (Sequential Redraw Flicker)

---

### 2. Prompt สำหรับสั่งให้ Antigravity (AGY) + `gemini-3.8-flash` แก้ปัญหาจอดำเวลาพับจอ

ก๊อปปี้บล็อกด้านล่างนี้ไปวางให้ **AGY** แก้ได้ทันทีครับ:

```text
# Task: Fix Black Screen & Slow Sequential Widget Redraw on Minimize/Restore/Alt+Tab (Windows DWM + CustomTkinter)

## Problem Description
When minimizing, restoring, maximizing, or Alt-Tabbing back to `FPS Patcher Studio`, the window turns completely black with a few blue highlight bars and then slowly repaints widgets one by one (sequential canvas flicker).

## Root Causes to Address
1. **Win32 Double-Buffering Missing**: Standard `ctk.CTk` (Tkinter) top-level windows on Windows paint child windows/canvases sequentially via GDI unless `WS_EX_COMPOSITED` (`0x02000000`) or proper DWM cloak/repaint handling is used, OR DWM Acrylic/Mica backdrop in `src/fps_patcher/ui/theme.py` clears the surface to black (`#000000`) on unmap/map transitions.
2. **`<Configure>` / `<Map>` Storm & Redundant Re-renders**: Restoring or resizing the window triggers multiple `<Configure>` events that force heavy layout recalculations in `MainWindow`, `InputList` (`CTkScrollableFrame`), and `ControlPanel` while the window is unmapping/mapping.
3. **Background Polling While Minimized**: `MainWindow._poll()` continues updating UI widgets while the window is iconic (`state() == "iconic"`), invalidating off-screen Tk canvases so restoration triggers a massive backlog of dirty widget redraws.

---

## Multi-Agent Execution Plan (Delegate Sub-tasks to `gemini-3.8-flash`)

### Subagent 1 (`gemini-3.8-flash`) — Inspect `theme.py`, `main_window.py`, and `input_list.py`
1. Inspect `src/fps_patcher/ui/theme.py` for any `ctypes.windll.dwmapi` (`DwmSetWindowAttribute`, Mica/Acrylic backdrop, dark titlebar) or window attribute calls.
2. Inspect `src/fps_patcher/ui/main_window.py` and `src/fps_patcher/ui/input_list.py` for `<Configure>`, `<Map>`, `<Unmap>`, `update_idletasks()`, and card rendering logic.

### Lead Agent — Implement Zero-Flicker Window Restore & Repaint Optimization
1. **Fix DWM Backdrop & Enable Win32 Double-Buffered Compositing (`src/fps_patcher/ui/theme.py` & `main_window.py`)**:
   - In `theme.py`, remove or disable translucent Mica/Acrylic `DWMWA_SYSTEMBACKDROP_TYPE` overrides that cause black surface clearing on minimize/restore; keep ONLY `DWMWA_USE_IMMERSIVE_DARK_MODE` (attribute 20) for the native dark title bar, and set an explicit solid root window background (`self.configure(fg_color=...)` and native Tk `bg`) matching the theme surface color so the base window buffer is never `#000000` black.
   - Apply Win32 `WS_EX_COMPOSITED` (`0x02000000`) extended window style (or DWM cloak-during-restore / `update_idletasks()` flush on `<Map>`) carefully on Windows (`sys.platform == "win32"`), testing that `CTkScrollableFrame` and mouse wheel scrolling remain 100% responsive.
2. **Pause UI Widget Mutations While Minimized (`src/fps_patcher/ui/main_window.py`)**:
   - Track window iconic/minimized state via `<Unmap>` and `<Map>` (or `self.state() == "iconic"`).
   - While minimized, `_poll()` should still drain the controller queue into internal state/log buffers, **but defer Tkinter widget `.configure()` / canvas redraws until `<Map>` (restore)**, then perform a single coalesced `update_idletasks()` refresh on restore.
3. **Debounce `<Configure>` Resize Events & Diff-Only `InputList.render()` (`src/fps_patcher/ui/input_list.py`)**:
   - Ensure `<Configure>` handlers ignore position-only moves (only react when `(event.width, event.height)` actually changes) and debounce resize handlers by `80ms`.
   - Ensure `InputList.render()` reuses existing row card widgets in-place instead of `.destroy()`-ing and recreating all cards when the queue length/paths haven't changed.

### Subagent 2 (`gemini-3.8-flash`) — Verification, Tests & Rebuild
1. Add/update UI lifecycle tests in `tests/test_ui_poll_and_context.py` verifying that minimize/restore state transitions and `_poll()` do not raise `TclError` or drop events.
2. Run all mandatory quality gates:
   - `uv run ruff check src tests`
   - `uv run mypy src tests`
   - `uv run pytest -q`
3. Rebuild the standalone executable:
   - `uv run --with pyinstaller pyinstaller build/fps_patcher.spec --noconfirm`
```

---

## 🗺️ Master Product Roadmap by Phase (Handoff Reference)

บันทึกแผนงานสำหรับพัฒนาต่อเนื่องในอนาคต แบ่งเป็น 5 เฟสชัดเจน:

### Phase 1: `v0.6.0` — Smart Pre-Flight & One-Click Auto-Fix
**สถานะ**: ✅ ส่งมอบแล้วตั้งแต่ `v0.6.0` และยังใช้งานอยู่ใน `v1.2.0` — **ไม่ต้อง rewrite**
ของเดิมเป็นเพียงเอกสารแผน; โค้ดจริงคือ `src/fps_patcher/core/preflight.py`,
`src/fps_patcher/core/patcher.py` และ `src/fps_patcher/core/updater.py`

**เป้าหมาย**: แก้ปัญหาผู้ใช้ตั้งค่าไฟล์ต้นฉบับมาผิด (เช่น เสียงเป็น PCM จาก `.mov` หรือ Bitrate สูงเกินจนมือถือหมุน) ให้แอปซ่อมให้อัตโนมัติ

- **1.1 Smart Audio Auto-Normalizer (`src/fps_patcher/core/preflight.py`, เรียกจาก `core/patcher.py`)**:
  - หากตรวจพบแทร็กเสียงที่ไม่ใช่ `AAC-LC 48000Hz Stereo` (เช่น `pcm_s16le`, `alac`, `mp3`) ให้รัน FFmpeg แปลงเฉพาะเสียง (`-c:v copy -c:a aac -ar 48000 -ac 2 -b:a 192k`) อัตโนมัติก่อนทำ X1T Patch
- **1.2 Smart Bitrate Limiter (`src/fps_patcher/core/preflight.py`)**:
  - ตั้งเป้าได้ด้วย `bitrate_target_mbps` (1-24 Mbps, ค่าเริ่มต้น 16) และ cap เฉพาะเมื่อต้นฉบับสูงกว่าเป้า; ต้นฉบับที่ต่ำกว่าหรือเท่ากับเป้ายัง copy แบบ lossless
  - ใช้ `h264_nvenc` / `h264_amf` / `h264_qsv` ก่อน แล้ว fallback เป็น `libx264`; v1.1.0 เพิ่ม `-hwaccel d3d11va` พร้อม fallback สำหรับต้นฉบับ AV1 ที่บิตเรตสูง
- **1.3 In-App Auto-Updater (`src/fps_patcher/core/updater.py`)**:
  - เช็กเวอร์ชันล่าสุดผ่าน GitHub Releases API (`https://api.github.com/repos/x1Swimzft/FPS-Patcher-Studio/releases/latest`)
  - แสดงปุ่มอัปเดตบน Toolbar เมื่อมีเวอร์ชันใหม่ และตั้งแต่ v1.2.0 จะเปิด dialog อัตโนมัติเมื่อเริ่มโปรแกรม โดยยังถามยืนยันก่อนดาวน์โหลด/ติดตั้ง
- **1.4 Save Roadmap Handoff to Project Docs**:
  - บันทึกไฟล์นี้ไว้ที่ `docs/ROADMAP.md` ในโปรเจกต์ (เสร็จแล้ว)

---

### Phase 2: `v0.7.0` — Zero-Click Creator Automation & Color Guard
**สถานะ**: ✅ ส่งมอบแล้ว — ดูรายละเอียดและข้อควรระวังที่ [`docs/handoff/phase2.md`](handoff/phase2.md)

**เป้าหมาย**: ลดขั้นตอนการลากไฟล์เข้าโปรแกรมให้เหลือ 0 คลิก และแก้ปัญหาสีคลิปดรอป/มืดลงเวลาลง TikTok

- **2.1 Watch Folder Mode (`src/fps_patcher/app/watcher.py`)**:
  - ระบบเฝ้าดูโฟลเดอร์ Export (เช่น โฟลเดอร์ขาออกของ CapCut / Premiere / DaVinci)
  - เมื่อเรนเดอร์คลิปเสร็จ แอปจะแพตช์ X1T ให้ในพื้นหลังทันที พร้อมเด้ง Windows Toast Notification
- **2.2 Windows Explorer Right-Click Context Menu**:
  - เพิ่มคำสั่งคลิกขวาบนไฟล์ `.mp4` / `.mov` / `.m4v` -> `"⚡ Quick Patch with X1T"` (ลงทะเบียนใน `HKCU\Software\Classes\SystemFileAssociations\.mp4\shell`)
- **2.3 Lossless Color Space (`colr` BT.709) Patcher & Metadata Scrubber**:
  - แพตช์กล่อง `colr` (`nclx` Primaries=1, Transfer=1, Matrix=1) เป็นมาตรฐาน Rec.709 แบบไม่ต้องเรนเดอร์ใหม่ แก้ปัญหาสีเพี้ยนหรือมืดลงบน TikTok
  - ล้างกล่อง `udta` / `meta` เพื่อลบประวัติซอฟต์แวร์ตัดต่อออกจากไฟล์

---

### Phase 3: `v0.9.0` — Multi-Platform Profiles & Pre-Flight Readiness Score
**เป้าหมาย**: ขยายการรองรับจาก TikTok ไปยังแพลตฟอร์มวิดีโอสั้นอื่นๆ

> Delivered in v0.9.0 as read-only platform profiles and readiness scoring. No
> unverified `ftyp`/`moov` rewrites or platform-specific binary transforms were added.
>
> Acceptance completed on the Qt UI in v0.10.0 (badge tooltip + click-to-console,
> watcher ignores pre-existing files, `.m4v` verb, updater 404 handling).

- **3.1 Platform-Specific X1T Presets**:
  - `X1T — TikTok (No Compress)`
  - `X1T — Instagram Reels`
  - `X1T — YouTube Shorts`
- **3.2 Visual Readiness Badge**:
  - แสดงคะแนนความพร้อมบนการ์ดวิดีโอในคิว เช่น `TikTok Ready 100%`, `TikTok Review 88%`, หรือ `TikTok Issues 40%`
  - คลิกที่ป้ายเพื่อดูเหตุผลรายข้อใน Activity Console

---

### Phase 4: `v1.0.0` — Native C++ Compilation (Nuitka) & Headless CLI
**สถานะ**: ✅ CLI ส่งมอบแล้ว · ⚠️ Nuitka ประเมินแล้วแต่ยังไม่เปลี่ยน pipeline (ไม่มี MSVC ในเครื่องที่วัด)

- **4.1 Nuitka C++ Compilation Pipeline**:
  - เพิ่ม `build/build_nuitka.ps1` แบบแยกส่วน (dry-run โดยค่าเริ่มต้น, ไม่แตะ PyInstaller/`uv.lock`/`release/`) พร้อมคู่มือใน `docs/NUITKA_EVALUATION.md`
  - **ยังไม่เปิดใช้**: ยังไม่มี MSVC ในเครื่องนี้ จึงไม่มีตัวเลขขนาด/เวลาเปิดโปรแกรม/VirusTotal ที่วัดจริง และไม่มีการอ้าง 0/70 — การแก้ปัญหา false positive ที่แท้จริงคือ Authenticode signing
- **4.2 Full CLI Interface**:
  - `FPSPatcherStudio.exe --cli patch|probe|score` พร้อม `--json`, exit codes 0/1/2/130, ไม่ import Qt, และต่อ console ของ parent ได้ใน frozen windowed build

---

### Phase 5: Post-`v1.2.0` — Release Hardening & Signing
**สถานะ**: 🔄 บางส่วนเสร็จแล้ว · รอ manual QA และ SignPath

- **5.1 SBOM automation — ✅ เสร็จแล้ว**:
  - `build/release.ps1` มี step `sbom` เรียก `tools/generate_sbom.py` และเขียน `release/FPSPatcherStudio-v<version>.cdx.json` ก่อนสร้าง checksum manifest เพื่อให้ JSON manifest บันทึก `sbom_path`
  - `.github/workflows/release.yml` ก็รัน `tools/generate_sbom.py` ก่อน `build/release.ps1` และอัปโหลด `release/*.cdx.json` เป็น artifact
  - SBOM ของ `v1.2.0` ถูกแนบย้อนหลังเข้า GitHub Release แล้ว (2026-11-03, `FPSPatcherStudio-v1.2.0.cdx.json`) และ checksum ตรงกับไฟล์ที่อัปโหลด
- **5.2 Manual QA sign-off สำหรับ `v1.2.0` — ⏳ ยังไม่ได้ตรวจ**:
  - ใช้ `docs/handoff/manual-test-v1.0.1.md` รวม section 9 “v1.2.0 additions (not executed)” ซึ่งครอบคลุม bitrate pill, Inspector Bitrate, ช่วง 1-24 Mbps, พฤติกรรม auto-cap และ startup update prompt
  - `v1.2.1` เพิ่ม section 10 “v1.2.1 additions (not executed)” ครอบคลุม Quick Patch/watch-folder timescale, `mask_diagnostic_paths` และการตรวจถ้อยคำ Tk — ยังไม่มีใครรัน
  - ห้ามลง PASS จาก code inspection; ต้องมีคนรันจริงและบันทึกผล/artifact/SHA-256 ใน sign-off table
- **5.3 SignPath code signing — ⛔ ยังไม่เปิดใช้ (blocked)**:
  - `v1.2.0` ที่เผยแพร่ยังเป็น **unsigned**; Windows SmartScreen อาจขึ้น “Unknown publisher”
  - ต้องรอ owner สมัคร/ได้รับอนุมัติ SignPath, สร้าง project และตั้งค่า `SIGNPATH_ENABLED=true`, `SIGNPATH_ORG_ID` และ secret `SIGNPATH_API_TOKEN` ตาม `docs/CODE_SIGNING_SIGNPATH.md`
  - ห้ามเขียนเอกสารหรือประกาศว่า signed จนกว่า workflow จะสร้าง artifact ที่มีลายเซ็นจริงและตรวจด้วย `Get-AuthenticodeSignature` แล้ว
