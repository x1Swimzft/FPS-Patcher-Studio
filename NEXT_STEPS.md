# Next Steps

Priority order for continuing FPS Patcher Studio.

## 1. Run native Windows validation

Use a clean Windows Python 3.11+ environment instead of the archived `.venv` copied from another OS/Python build.

```powershell
uv sync --dev
uv run pytest -q
uv run ruff check src tests
uv run mypy
```

Record exact command output and Python/FFmpeg versions. Do not mark lint/type checking PASS unless the commands actually ran successfully.

## 2. Test V4 against representative files

Build a fixture set that includes: audio/no-audio, H.264/HEVC, `stco`/`co64`, `stsz`/`stz2`, B-frames/`ctts`, edit lists, VFR, long duration/version-1 headers, multiple `mdat` boxes, and corrupted/truncated samples. V4 should reject unsupported layouts cleanly and preserve the input.

For each file, record:

- `ffprobe` before/after JSON
- forensic `before.json`, `after.json`, `diff.json`
- strict validator result
- SHA-256 for full media payload and mapped audio/video samples
- playback/audio-sync result

## 3. Isolate experimental BXD behind an explicit warning

Keep `bxd-experimental` opt-in. Before using its output, require a real original/output pair and inspect all root atoms, trailing data, sample tables, chunk offsets, audio/video payload hashes, and playback behavior. Do not hide a non-standard/invalid result behind a generic success badge.

## 4. Finish UI QA

On Windows 10/11, test Acrylic/Mica, alpha/transparency toggle, dark/light modes, high DPI, resizing, large logs, and contrast/readability. Test fallback visuals on a non-Windows platform if cross-platform support is intended.

## 5. Improve build hygiene

Keep `.venv`, caches, `dist`, Python bytecode, and local generated files out of source ZIPs. Build the executable only after tests and dependency/license review pass.

## 6. Controlled platform experiment (optional)

Only after local file checks pass, compare upload renditions under controlled conditions. This can study platform behavior but cannot be proven by local parsing. Avoid claims such as “guaranteed 1080p bypass.”
