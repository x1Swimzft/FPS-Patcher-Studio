# FPS Patcher Studio

A Windows desktop app and headless CLI for patching video container timing and producing TikTok-ready MPEG-TS presets.

- **MP4/MOV patches are lossless.** The container atoms are rewritten; the encoded samples are not touched.
- **TikTok TS presets match the reference upload.** `X1T Remux` copies an existing H.264 video bitstream and re-encodes only audio; `X1T 60fps` and `X1T 1080p` are lossy H.264/AAC re-encodes for other sources.
- **Auto-update is on by default.** The app checks GitHub Releases on startup and asks before downloading.
- **No telemetry. No media uploads.** Files stay on your PC.

[Download v2.0.4](https://github.com/x1Swimzft/FPS-Patcher-Studio/releases/tag/v2.0.4) · [Website](https://x1t-web.vercel.app/) · [Release notes](https://github.com/x1Swimzft/FPS-Patcher-Studio/releases) · [Privacy](docs/PRIVACY.md)

## Presets

| Preset | Use for | Video | Audio | Container |
| --- | --- | --- | --- | --- |
| **X1T Remux** (default) | An already-H.264 1080p60 source | **Copied unchanged** | AAC 128k, 48 kHz stereo | MPEG-TS, `.mp4` extension |
| **X1T 60fps** | AV1, HEVC, or arbitrary sources | H.264 Main/CAVLC re-encode, source resolution, 60 fps | AAC 128k, 48 kHz stereo | MPEG-TS, `.mp4` extension |
| **X1T 1080p** | 1080p60 deliverables | H.264 Main/CAVLC re-encode, letterboxed to 1920x1080, 60 fps | AAC 128k, 48 kHz stereo | MPEG-TS, `.mp4` extension |

`X1T Remux` preserves the source H.264 bitstream — including its encoder SEI and bitrate — so a matching source reproduces the reference video MD5 exactly. The two re-encode presets cannot match that bitstream by design.

`X1T 60fps` and `X1T 1080p` require Windows Media Foundation (`h264_mf`). `X1T Remux` does not re-encode video and works with any H.264 source. If you give `X1T Remux` an AV1/HEVC file, it stops with a clear message to choose `X1T 1080p`.

The four original X1T presets (`X1T For PC`, `X1T For Mobile`, `X1T Hybrid`, `X1T Clean`) remain available to saved settings and the CLI via `--strategy bxd-pc`, `bxd-mobile`, `bxd-hybrid`, and `bxd-clean`, but are hidden from the pickers. They are lossless ISO-BMFF container patches.

TikTok upload behaviour is not guaranteed. Matching the reference fingerprint does not prove that TikTok will skip re-encoding.

## Install

Windows 10/11 x64. Pick one:

- **Installer:** `FPSPatcherStudio-v2.0.4-Setup.exe`
- **Portable:** `FPSPatcherStudio-v2.0.4-win64.zip` — extract the whole folder, then run `FPSPatcherStudio.exe`

The builds are **unsigned**, so Windows SmartScreen may warn. Verify the SHA-256 against the release checksum before running.

FFmpeg and FFprobe are bundled in the release. FFmpeg auto-download is disabled by default.

## GUI quick start

1. Launch `FPSPatcherStudio.exe` (or `uv run fps-patcher-studio` from source).
2. Drop `.mp4`, `.mov`, or `.m4v` files on the window, or use **Add Files**.
3. Choose the target FPS and a preset. **X1T Remux** is the default for an H.264 source.
4. Press **Start Patch**.
5. Set the output folder in **Settings → Output** if you do not want files beside the source.

The queue supports per-item overrides for preset, timescale, and platform profile. The Inspector shows source/output bitrate and readiness checks. The Watch Folder processes new files as they appear.

For `X1T Remux`, use the H.264 source; for AV1/HEVC, choose `X1T 60fps` or `X1T 1080p`. The target FPS only affects the `_ts<timescale>` filename for the TS presets; the stream itself is always 60 fps.

## CLI

```powershell
# Lossless video remux + AAC audio, matching the reference
fps-patcher-studio --cli patch "clip.mp4" --preset 60 --strategy tiktok-ts-remux --output out

# Lossy re-encode for AV1/HEVC or arbitrary sources
fps-patcher-studio --cli patch "clip.mp4" --preset 60 --strategy tiktok-ts-1080 --output out

# Batch, JSON output
fps-patcher-studio --cli patch "a.mp4" "b.mov" --preset 60 --strategy tiktok-ts --output out --json

# Inspect metadata and readiness
fps-patcher-studio --cli probe "clip.mp4"
fps-patcher-studio --cli score "clip.mp4" --profile tiktok --json

# Job history and rollback
fps-patcher-studio --cli history
fps-patcher-studio --cli undo --last
```

`--preset` accepts `60` or `120` (or `--timescale` for a custom value). `--overwrite` replaces an existing output; the default is to add a ` (n)` suffix. A replaced output is backed up as `.bak` when backups are enabled. `--strategy` accepts `tiktok-ts`, `tiktok-ts-1080`, `tiktok-ts-remux`, and the legacy X1T keys.

Preflight switches such as `--normalize-audio`, `--cap-bitrate`, and `--fix-vfr` are skipped for the TS presets: `X1T Remux` normalises audio itself, and the re-encode presets already set the audio and frame rate. `--tag-bt709` and `--scrub-metadata` are also skipped for TS with a `[COLOR] skipped: not ISO-BMFF` log.

## Auto-update

- **Check on startup:** enabled by default. The app requests the latest release from `https://api.github.com/repos/x1Swimzft/FPS-Patcher-Studio/releases/latest`.
- **Download:** only after you accept the update. The asset is fetched from GitHub and verified with SHA-256.
- **Unsigned builds:** when the release publishes a SHA-256, the app warns and installs the unsigned installer only after that checksum matches. If no checksum is published, Authenticode verification is required.
- **Disable:** turn off **Check for updates on startup** in Settings.
- **FFmpeg:** auto-download stays opt-in behind `FPS_PATCHER_ALLOW_NETWORK=1`; the updater does not depend on that override.

No telemetry, analytics, or media uploads. See [docs/PRIVACY.md](docs/PRIVACY.md).

## What gets verified

For MP4/MOV output:

- atom structure and trailing data
- chunk offsets and sample tables
- playback metadata and mobile compatibility
- optional Rec.709 colour tag and metadata scrub
- sampled SHA-256 of the `mdat` payload and per-track samples

For MPEG-TS presets:

- first byte `0x47`
- H.264 output
- 60 fps for the re-encode presets (source frame rate for remux)
- exactly 1920x1080 for `X1T 1080p`
- duration within tolerance of the source

## Build from source

Python 3.11+ and [uv](https://docs.astral.sh/uv/):

```powershell
uv sync
uv run fps-patcher-studio
```

Quality gates:

```powershell
uv run ruff check src tests tools
uv run mypy src tests tools
uv run pytest -q
```

Release build (PyInstaller one-folder + portable ZIP; Inno Setup 6/7 adds the installer):

```powershell
powershell -ExecutionPolicy Bypass -File build\release.ps1
```

The script writes `dist\FPSPatcherStudio\`, the portable ZIP, checksums, SBOM, and release manifest to `release\`. See [BUILDING.md](BUILDING.md) for the full release and signing flow.

## Project layout

- `src/fps_patcher/core/` — probing, patching, strategies, preflight, verification, updater
- `src/fps_patcher/app/` — controller, queue, watcher, quick patch
- `src/fps_patcher/ui_qt/` — PySide6 desktop UI
- `tests/` — pytest suite, including real FFmpeg encode/remux checks
- `build/` — PyInstaller spec, Inno Setup script, release script

## License

MIT. Third-party components and licenses are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
