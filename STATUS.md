# FPS Patcher Studio — Implementation Status

Updated: 2026-10-09

## Implemented in the current project

- Four explicit strategy IDs: `direct-atom`, `v4-forensic`, `bxd-experimental`, and `ffmpeg-copy`; legacy aliases are centralized.
- Direct strategies can be invoked without configured FFmpeg. FFmpeg-copy still requires FFmpeg; probing has an internal fallback.
- Central CustomTkinter theme and Windows backdrop integration (Acrylic/Mica where supported), with a visual fallback elsewhere.
- MP4/MOV forensic analyzer for atom-tree, semantic-field, byte-span, and payload comparison.
- V4 direct timing patch path; fragmented MP4 is explicitly rejected.
- Strict verifier for atom parsing, static sample-table consistency, chunk offsets/extent, `mdat` payload hash, and video/audio sample payload hash when available.
- Forensic comparison now treats missing/incomplete hashes as UNKNOWN/CHECK instead of an unchanged PASS.
- Multi-`mdat` payloads are hashed as one ordered concatenation. Sample hashes are computed only when all mapped samples fit wholly inside declared `mdat` payload ranges.
- Added regression tests for false `stco` strings in payload data, bad offset ranges, sample-table count mismatch, hash-unavailable results, and multi-`mdat` hashing.
- BXD comments and logs no longer promise a 1080p bypass or universal losslessness; its non-standard behavior remains an explicit warning.
- BXD refuses identical input/output paths, malformed/trailing input bytes, multiple `mdat` boxes, duplicate required boxes, and unsupported root atoms; preserves FFmpeg `free` boxes and writes to a temporary file before replacing output.
- Added this status file, `NEXT_STEPS.md`, and `AI_NEXT_REVIEW_PROMPT.md`.

## Latest tests run

Environment: Windows 11 Desktop (Python 3.11, CustomTkinter, tkinterdnd2).

1. `uv run pytest -q`: **80 passed** (all core, forensic, patcher, queue model, settings, contrast tests).
2. `uv run ruff check src tests`: **0 errors (clean)**.
3. `uv run mypy src tests`: **0 errors (clean, strict mode across 51 source files)**.
4. `uv run --with pyinstaller pyinstaller build/fps_patcher.spec --noconfirm`: **Build succeeded (`dist/FPSPatcherStudio/FPSPatcherStudio.exe` generated)**.

## Implemented Architecture & UI Features

- **Queue Model & UI (Target Design)**: `InputList` widget with multi-file append, folder recursive drop, background thumbnail extraction, status badges, resolution/FPS badges, per-item overrides, and selection toolbar.
- **Queue Persistence**: `queue.json` in user AppData folder with auto-prune on missing files.
- **Lock-skipping Safety**: Removing or clearing queue while busy skips the currently patching file without aborting the batch.
- **Glass & Contrast (WCAG AA)**: Obsidian dark palette tuned to >= 4.5:1 contrast ratio; backdrop defaults to Solid (or >= 0.98 alpha) to prevent see-through text distraction.
- **Modular Settings Window**: Split into `src/fps_patcher/ui/settings_tabs/` (`appearance.py`, `output.py`, `patching.py`, `ffmpeg.py`, `console.py`, `behavior.py`, `about.py`).

## Not run / not verified

- TikTok upload rendition/resolution behavior remains **NOT VERIFIED**. Local container atom timing patch cannot guarantee external platform transcode behavior.
- BXD non-standard trailing bytes behavior remains opt-in and experimental.
- The verifier is defensive, not a complete ISO-BMFF conformance suite. Fragmented MP4 (`moof`/`trun`) and every vendor-specific atom/table combination are not fully validated.

## Known risks

1. `bxd-experimental` may deliberately append unboxed trailing bytes and may not produce a standards-conforming MP4. Do not use it for important files without independently validating compatibility.
2. V4 reads the full input file into memory; very large files can require substantial RAM.
3. `direct-atom` is a separate basic strategy; do not assume it has every strict validation gate present in V4.
4. The visual glass effect is Windows-specific at the OS backdrop level. Other platforms get the app's styled surface fallback, not identical native blur.
5. Hash comparison proves byte equality only for byte ranges the analyzer successfully maps. An unavailable hash is unknown, never evidence of equality.
