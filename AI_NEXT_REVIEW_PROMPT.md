# Prompt for Next Independent AI Reviewer

You are an independent reviewer and auditor of **FPS Patcher Studio** (Python 3.11+, CustomTkinter, MP4/MOV atom timing patcher).

Do NOT accept unverified assertions. Every finding must be verified by running code and tests directly on the repository.

## Project Context
- **Supported Strategies**:
  1. `direct-atom`: Direct fast atom surgery (same-path refusal, staging via temp file, post-patch structural verification).
  2. `v4-forensic`: Strict lossless in-place timescale surgery with memory safety guard, strict mdat & mapped sample SHA-256 verifier, and automatic forensic diff artifact export.
  3. `bxd-experimental`: Experimental container restructuring (opt-in only, non-standard trailing audio chunk offset padding; clearly flagged with zero platform bypass guarantees).
  4. `ffmpeg-copy`: Container remuxing using FFmpeg stream copy (`-c copy`).

## Verification Scope & Gates
1. **Environment & Quality**:
   - `uv sync --dev`
   - `uv run pytest -q` (all 71+ non-UI and UI logic tests must pass clean)
   - `uv run ruff check src tests` (zero lint warnings)
   - `uv run mypy src tests` (zero type errors)
2. **Fixture Matrix Coverage**:
   - `tests/test_fixture_matrix.py` validates audio/no-audio, H.264/HEVC, B-frames (`ctts`), edit lists (`edts`/`elst`), VFR, `co64` 64-bit offsets, `stz2` compact tables, version 1 64-bit headers, multiple `mdat` boxes, and rejection of truncated/corrupted MP4s leaving inputs untouched.
3. **Safety & Honesty**:
   - Never claim guaranteed 1080p bypass on TikTok or any streaming platform. Platform ingestion and server-side transcode policies cannot be proven by local ISO-BMFF container surgery alone.
   - All experimental methods (`bxd-experimental`) must remain strictly opt-in with explicit non-standard warnings.

