# Software Supply Chain & Dependency Audit Report

**Project**: `fps-patcher-studio` v0.9.0  
**Audit Date**: 2026-10-25 06:23:07 UTC  
**Tool**: `tools/generate_sbom.py` (CycloneDX 1.5 Specification)  
**SBOM Artifact**: [`release/FPSPatcherStudio-v0.9.0.cdx.json`](../release/FPSPatcherStudio-v0.9.0.cdx.json)  

---

## 1. Executive Summary

- **Total Resolved Packages**: **30** (2 runtime, 6 direct dev, 22 transitive) in `uv.lock`, excluding the root project.
- **Vulnerability Status**: **0 Known CVEs** across all dependencies (verified OSV).
- **Key Remediation**: Upgraded `pillow` to `13.0.0` (resolving 28 historical GHSA CVEs) and added `pillow>=13.0.0` to `project.dependencies` to ensure runtime safety.
- **Cryptographic Integrity**: 100% of packages pinned with SHA-256 hashes in `uv.lock`.
- **Bundled Binaries & Assets**: Verified zero bundled binary executables/DLLs in `src/`. FFmpeg downloader features HTTPS TLS verification, strict Zip Slip immunity, zip-bomb decompression protection (512MB limit), and optional SHA-256 integrity.

---

## 2. Direct Runtime Dependencies

These packages are required to run the FPS Patcher Studio desktop application:

| Package | Version | Declared Spec | License | Purpose / Security Notes |
| :--- | :--- | :--- | :--- | :--- |
| `pillow` | `13.0.0` | `pillow>=13.0.0` | HPND / Historical | Imaging library for icons, thumbs, preview decoding |
| `pyside6` | `6.12.0` | `pyside6==6.12.0` | Unknown | Desktop UI runtime dependency |

---

## 3. Direct Development Dependencies

These packages are used for building, linting, typechecking, and testing:

| Package | Version | Declared Spec | License | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `cairosvg` | `2.9.1` | `cairosvg>=2.9.1` | LGPL-3.0 | SVG icon rasterizer to PNG / high-DPI icons |
| `mypy` | `2.4.0` | `mypy>=2.4.0` | MIT | Static type checker for Python |
| `pytest` | `9.1.1` | `pytest>=9.1.1` | MIT | Unit and integration test runner |
| `pytest-mock` | `3.16.0` | `pytest-mock>=3.16.0` | MIT | Thin wrapper around the mock package for pytest |
| `pytest-qt` | `4.5.0` | `pytest-qt==4.5.0` | Unknown | Dev dependency |
| `ruff` | `0.16.10` | `ruff>=0.16.10` | MIT / Apache-2.0 | Fast Rust-based Python linter and formatter |

---

## 4. Transitive Dependencies

The following 22 transitive dependencies are pulled by direct runtime and dev packages:

| Package | Version | Direct Parent | License |
| :--- | :--- | :--- | :--- |
| `ast-serialize` | `0.12.1` | `mypy` | MIT |
| `cairocffi` | `1.7.1` | `cairosvg` | BSD-3-Clause |
| `cffi` | `2.1.1` | `cairocffi` | MIT |
| `colorama` | `0.4.6` | `pytest` | BSD-3-Clause |
| `cssselect2` | `0.10.1` | `cairosvg` | BSD-3-Clause |
| `defusedxml` | `0.7.1` | `cairosvg` | Python-2.0 |
| `iniconfig` | `2.3.1` | `pytest` | MIT |
| `librt` | `0.16.0` | `mypy` | MIT |
| `mypy-extensions` | `1.1.0` | `mypy` | MIT |
| `packaging` | `26.3` | `pytest` | Apache-2.0 |
| `pathspec` | `1.1.1` | `mypy` | MPL-2.0 |
| `pluggy` | `1.6.0` | `pytest`, `pytest-qt` | MIT |
| `pycparser` | `3.11` | `cffi` | BSD-3-Clause |
| `pygments` | `2.21.0` | `pytest` | BSD-2-Clause |
| `pyside6-addons` | `6.12.0` | `pyside6`, `pyside6-webengine` | Unknown |
| `pyside6-essentials` | `6.12.0` | `pyside6`, `pyside6-addons`, `pyside6-pdf` | Unknown |
| `pyside6-pdf` | `6.12.0.140` | `pyside6` | Unknown |
| `pyside6-webengine` | `6.12.0.140` | `pyside6` | Unknown |
| `shiboken6` | `6.12.0` | `pyside6-essentials` | Unknown |
| `tinycss2` | `1.5.1` | `cairosvg`, `cssselect2` | BSD-3-Clause |
| `typing-extensions` | `4.16.0` | `mypy`, `pytest-qt` | Python-2.0 |
| `webencodings` | `0.6.1` | `cssselect2`, `tinycss2` | BSD-3-Clause |

---

## 5. Bundled Binaries & Assets Security Audit

### 5.1 External Binaries & Downloader (`src/fps_patcher/core/ffmpeg_downloader.py`)
- **Source URL**: `https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip`.
- **Transport Security**: Enforced HTTPS; non-HTTPS URLs rejected with `FFmpegDownloadError`. Standard system TLS certificate validation enabled.
- **Zip Slip Immunity**: Output filenames are strictly constrained to a fixed allowlist (`('ffmpeg.exe', 'ffprobe.exe')`). Directory paths, relative path traversal (`../`), and decoy paths inside the archive are discarded.
- **Decompression Bomb Protection**: Member file size is capped at 512MB (`MAX_MEMBER_BYTES`), and streaming chunk count is verified during decompression.
- **Execution Verification**: Binaries are smoke-tested via `--version` subprocess calls before atomic installation into `%LOCALAPPDATA%\FPSPatcherStudio\bin\`.
- **Cryptographic SHA-256 Verification**: Supported via `expected_sha256` parameter in `download_ffmpeg()` for pinned releases and automated audits.

### 5.2 UI Assets (`src/fps_patcher/ui/assets/`)
- **Fonts**: `Inter-Bold.ttf`, `Inter-Medium.ttf`, `Inter-Regular.ttf`, `Inter-SemiBold.ttf` (Licensed under SIL Open Font License 1.1).
- **Icons**: High-precision PNG/SVG icon sets for dark and light modes. Zero active executable scripts, macros, or binary blobs.
- **No Bundled DLLs**: The repository codebase bundles zero binary `.dll` or `.exe` files in `src/`. Binaries are gitignored.

---

## 6. Supply Chain Integrity & Automated CI Verification

- **Lockfile Verification**: `uv.lock` is committed with SHA-256 distribution hashes.
- **Automated Security Workflow**: `.github/workflows/security-audit.yml` runs:
  1. `ruff check src tests` (Linter & code quality rules)
  2. `mypy src tests` (Strict static type checker)
  3. `pytest -q` (Full 356-test suite regression verification)
  4. `python tools/generate_sbom.py` (CycloneDX SBOM generation & lockfile audit)
  5. `pip-audit` / OSV vulnerability scanning against pinned lockfile.

---

> **Count note (2026-10-25):** `tools/generate_sbom.py` writes the executive-summary
> and transitive-count strings as static text. They were corrected here to match
> `uv.lock` (30 packages: 2 runtime, 6 dev, 22 transitive) and the 356-test suite.
> Update the generator template when the dependency set or test count changes, or
> the next regeneration will restore the stale numbers.

*Report generated automatically by FPS Patcher Studio Security Toolchain.*
