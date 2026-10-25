# Building FPS Patcher Studio from Source

This guide provides complete, step-by-step instructions for building **FPS Patcher Studio** from source on Windows 64-bit, reproducing identical portable ZIP archives, compiling Inno Setup installers, running quality gates, and configuring Authenticode code signing.

---

## 1. Prerequisites & Toolchain

Ensure the following tools are installed on your Windows 10/11 64-bit system:

| Tool | Recommended Version | Purpose | Installation / Download |
|---|---|---|---|
| **Python** | 3.11.x (CPython 64-bit) | Application runtime | [python.org](https://www.python.org/downloads/) |
| **uv** | >= 0.4.0 | Fast Python package and project manager | `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| **Git** | >= 2.40 | Source control | [git-scm.com](https://git-scm.com/) or MinGit |
| **Inno Setup** *(Optional)* | 6.x or 7.x | Compiling Windows installer (`Setup.exe`) | [jrsoftware.org/isdl.php](https://jrsoftware.org/isdl.php) |
| **Windows SDK** *(Optional)* | 10.0 or 11.0 | Authenticode binary signing (`signtool.exe`) | Included in Windows SDK / Visual Studio |
| **FFmpeg** *(Optional)* | 5.x, 6.x, or 7.x | Video thumbnail extraction (can be placed in `bin/`) | [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) |

---

## 2. Environment Setup

Clone the repository and synchronize the Python virtual environment:

```powershell
# 1. Clone repository
git clone https://github.com/x1Swimzft/FPS-Patcher-Studio.git
cd FPS-Patcher-Studio

# 2. Synchronize virtual environment and install all dependencies
uv sync

# 3. Verify the installation by running the app directly
uv run fps-patcher-studio
```

---

## 3. Running Verification & Quality Gates

Before packaging a release, run all automated linting, type-checking, and test suites:

```powershell
# Code style and linting checks
uv run ruff check src tests

# Static type checking (strict mode)
uv run mypy src tests

# Automated test suite (unit and integration tests)
uv run pytest tests -q
```

All quality gates must pass without errors or warnings.

---

## 4. Automated Release Build (Recommended)

The automated script [`build/release.ps1`](build/release.ps1) handles the full end-to-end pipeline:
1. Runs quality gates (`ruff`, `mypy`, `pytest`).
2. Builds the PyInstaller one-folder standalone package (`dist\FPSPatcherStudio\`).
3. Executes a launch smoke test (verifies the executable runs for at least 6 seconds without crashes).
4. Copies licenses, documentation, and first-run guides into the distribution directory.
5. Packages the portable release ZIP archive (`release\FPSPatcherStudio-v<version>-win64.zip`).
6. Detects Inno Setup compiler (`ISCC.exe`) and builds the installer (`release\FPSPatcherStudio-v<version>-Setup.exe`).
7. Generates bit-exact SHA-256 checksum manifests (`FPSPatcherStudio-v<version>.sha256`).

### Basic Release Build:
```powershell
powershell -ExecutionPolicy Bypass -File build\release.ps1
```

### Release Build with Self-Signed Authenticode Signing:
```powershell
powershell -ExecutionPolicy Bypass -File build\release.ps1 -Sign -GenerateSelfSigned
```

### Fast Build (Skipping Pre-Build Gates for Quick Testing):
```powershell
powershell -ExecutionPolicy Bypass -File build\release.ps1 -SkipChecks
```

---

## 5. Manual Step-by-Step Build

If you prefer to execute the build steps individually:

### Step 5.1: Compile Standalone Folder with PyInstaller

Run PyInstaller against the spec file [`build/fps_patcher.spec`](build/fps_patcher.spec):

```powershell
uv run --with pyinstaller pyinstaller build/fps_patcher.spec --noconfirm
```

This generates the portable executable distribution in:
```
dist\FPSPatcherStudio\
├── FPSPatcherStudio.exe
├── _internal\
├── README.md
└── ...
```

### Step 5.2: Smoke Test

Launch the compiled executable to verify there are no missing Qt plugins, DLLs, or bundled assets:
```powershell
$proc = Start-Process -FilePath "dist\FPSPatcherStudio\FPSPatcherStudio.exe" -PassThru
Start-Sleep -Seconds 6
if (-not $proc.HasExited) {
    Write-Host "Smoke test PASSED!" -ForegroundColor Green
    Stop-Process -Id $proc.Id -Force
} else {
    Write-Error "Smoke test FAILED with exit code $($proc.ExitCode)"
}
```

### Step 5.3: Package Portable ZIP Archive

```powershell
New-Item -ItemType Directory -Force -Path "release"
Compress-Archive -Path "dist\FPSPatcherStudio" -DestinationPath "release\FPSPatcherStudio-v0.7.0-win64.zip" -Force
```

### Step 5.4: Compile Inno Setup Installer

Locate `ISCC.exe` (typically in `C:\Program Files\Inno Setup 7\ISCC.exe` or `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`) and compile:

```powershell
& "C:\Program Files\Inno Setup 7\ISCC.exe" /DAppVersion=0.7.0 "build\installer.iss"
```
The installer will be produced at `release\FPSPatcherStudio-v0.7.0-Setup.exe`.

---

## 6. Code Signing & Authenticode Configuration

Code signing helps verify software origin and prevents tampering. FPS Patcher Studio provides [`build/sign_binaries.ps1`](build/sign_binaries.ps1) for Authenticode signing via `signtool.exe`.

### Option A: Production Code Signing (Commercial Certificate)
Set environment variables pointing to your commercial PFX certificate:
```powershell
$env:CERT_PFX_PATH = "C:\Path\To\your_cert.pfx"
$env:CERT_PASSWORD = "YourSecretPassword"

powershell -ExecutionPolicy Bypass -File build\sign_binaries.ps1
```

### Option B: Local Developer Self-Signed Certificate
For local development, testing, and CI verification, generate a 3072-bit self-signed certificate:
```powershell
powershell -ExecutionPolicy Bypass -File build\sign_binaries.ps1 -GenerateSelfSigned
```
*Note: A self-signed certificate provides cryptographic integrity and timestamping, but will display an untrusted publisher warning in Windows SmartScreen until a commercial CA-issued certificate is used.*

---

## 7. Generating Release Manifests & Hashes

Calculate SHA-256 hashes for all generated release artifacts and record them in the standard `sha256sum` format:

```powershell
Get-ChildItem "release" -File | Where-Object { $_.Name -like "FPSPatcherStudio-v0.7.0-*" -and $_.Extension -ne ".sha256" } |
    ForEach-Object { "$((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower())  $($_.Name)" } |
    Set-Content -Path "release\FPSPatcherStudio-v0.7.0.sha256" -Encoding ASCII
```

Verify output:
```powershell
Get-Content "release\FPSPatcherStudio-v0.7.0.sha256"
```

---

## 8. Troubleshooting Build Issues

| Issue | Cause | Resolution |
|---|---|---|
| `ISCC.exe not found` | Inno Setup not installed or not in default path | Install Inno Setup 6 or 7, or pass path directly to `release.ps1`. |
| `signtool.exe not found` | Windows SDK not installed | Install Windows SDK or run without `-Sign` flag. |
| `This application failed to start because no Qt platform plugin could be initialized` | `qwindows.dll` missing from the PyInstaller output | Rebuild with `build/fps_patcher.spec`; confirm `_internal\PySide6\plugins\platforms\qwindows.dll`. |
| `version_info.txt out of sync` | Version in `version_info.txt` does not match `__version__` | Update `build/version_info.txt` to match `src/fps_patcher/__init__.py`. |
