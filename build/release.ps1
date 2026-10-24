<#
.SYNOPSIS
  Build the downloadable Windows app (portable zip and installer) for FPS Patcher Studio.
.DESCRIPTION
  1. ruff + mypy + pytest gates (abort on failure; skip with -SkipChecks)
  2. PyInstaller one-folder windowed build
  3. Code signing:
     - Default: EXPLICIT UNSIGNED RELEASE (safe from VirusTotal 'invalid signature' flags).
     - -SignDev: Local development self-signed cert (untrusted).
     - -Sign: Production Authenticode signing (requires CERT_PFX_PATH and CERT_PASSWORD).
  4. Launch smoke test (exe must stay alive for a few seconds)
  5. release/FPSPatcherStudio-v<version>-win64.zip + .sha256 (+ Setup.exe and manifests)
  6. Structured JSON release manifest (release/FPSPatcherStudio-v<version>.manifest.json)
  Run from project root:  powershell -ExecutionPolicy Bypass -File build\release.ps1
.PARAMETER SkipChecks
  Skip ruff, mypy, and pytest gates.
.PARAMETER Sign
  Sign the exe and installer with production certificate (env CERT_PFX_PATH / CERT_PASSWORD).
.PARAMETER SignDev
  Sign with local dev certificate (build\dev_signing.pfx; untrusted).
.PARAMETER GenerateSelfSigned
  Backward-compatible alias for -SignDev.
#>
param(
    [switch]$SkipChecks,
    [switch]$Sign,
    [switch]$SignDev,
    [switch]$GenerateSelfSigned
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ($Sign -and ($SignDev -or $GenerateSelfSigned)) {
    throw "Conflicting parameters: specify -Sign for production signing OR -SignDev for local development signing, not both."
}

$isDevSigning = $SignDev -or $GenerateSelfSigned
$isProdSigning = $Sign

if ($isProdSigning) {
    if (-not $env:CERT_PFX_PATH -or -not $env:CERT_PASSWORD) {
        throw "Production signing requested (-Sign), but CERT_PFX_PATH or CERT_PASSWORD environment variable is not configured. For development signing, use -SignDev."
    }
    if (-not (Test-Path $env:CERT_PFX_PATH)) {
        throw "Production signing requested (-Sign), but certificate file not found: $env:CERT_PFX_PATH"
    }
    $releaseSignatureStatus = "production-signed (Authenticode)"
} elseif ($isDevSigning) {
    $releaseSignatureStatus = "dev-signed (untrusted self-signed)"
} else {
    $releaseSignatureStatus = "unsigned"
}

$statusColor = if ($isProdSigning) { "Green" } elseif ($isDevSigning) { "Yellow" } else { "Magenta" }
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "FPS Patcher Studio Release Pipeline" -ForegroundColor Cyan
Write-Host "Signature Mode: $releaseSignatureStatus" -ForegroundColor $statusColor
Write-Host "==========================================================" -ForegroundColor Cyan

function Step($name, [scriptblock]$cmd) {
    Write-Host "== $name" -ForegroundColor Cyan
    & $cmd
    if ($LASTEXITCODE -ne 0) { throw "$name failed (exit $LASTEXITCODE)" }
}

$version = (Select-String -Path "src\fps_patcher\__init__.py" -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
if (-not (Select-String -Path "build\version_info.txt" -SimpleMatch "'FileVersion', '$version.0'" -Quiet)) {
    throw "build\version_info.txt is out of sync with __version__ $version"
}

# Ensure git is on PATH if MinGit exists in known location
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue) -and (Test-Path "C:\Users\Dataria\AppData\Local\Programs\MinGit\cmd\git.exe")) {
    $env:PATH = "C:\Users\Dataria\AppData\Local\Programs\MinGit\cmd;$env:PATH"
}

$signScript = Join-Path $PSScriptRoot "sign_binaries.ps1"

if (-not $SkipChecks) {
    Step "ruff"   { uv run ruff check src tests tools }
    Step "mypy"   { uv run mypy src tests tools }
    Step "pytest" { uv run pytest -q }
}

Step "pyinstaller" { uv run --with pyinstaller pyinstaller build/fps_patcher.spec --noconfirm }

$appDir = Join-Path $root "dist\FPSPatcherStudio"
$exe = Join-Path $appDir "FPSPatcherStudio.exe"
if (-not (Test-Path $exe)) { throw "Build output missing: $exe" }

if ($isProdSigning) {
    Step "sign exe (production)" { powershell -NoProfile -ExecutionPolicy Bypass -File $signScript -Path $exe }
} elseif ($isDevSigning) {
    Step "sign exe (development)" { powershell -NoProfile -ExecutionPolicy Bypass -File $signScript -Path $exe -SignDev }
} else {
    Write-Host "== release is explicitly unsigned: skipping code signing" -ForegroundColor Yellow
}

# Smoke test: exe must still be running after 6 s (no instant crash)
Write-Host "== launch smoke test" -ForegroundColor Cyan
$proc = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 6
$alive = -not $proc.HasExited
if ($alive) { Stop-Process -Id $proc.Id -Force } else { throw "Smoke test failed: exe exited with code $($proc.ExitCode)" }

# Ship docs + first-run notes inside the app folder
foreach ($f in "README.md", "CHANGELOG.md", "SECURITY.md", "BUILDING.md", "THIRD_PARTY_NOTICES.md") { if (Test-Path $f) { Copy-Item $f $appDir -Force } }

$signatureNote = switch ($releaseSignatureStatus) {
    "production-signed (Authenticode)" { "  - Binary signature: Production Authenticode verified." }
    "dev-signed (untrusted self-signed)" { "  - Windows SmartScreen may warn: signed with untrusted developer test certificate." }
    default { "  - Windows SmartScreen may warn: the exe is unsigned." }
}

@"
FPS Patcher Studio v$version (Windows 64-bit, portable)

Run:   FPSPatcherStudio.exe   (no install needed; delete the folder to remove)
Data:  %APPDATA%\FPSPatcherStudio  (settings.json, queue.json, logs)

Presets (v$version):
  - X1T For PC (x1t-pc / bxd-pc): Full PC TikTok bypass (indeterminate mvhd, 10x audio ghosts, trailing bytes).
  - X1T For Mobile (x1t-mobile / bxd-mobile): TikTok bypass (indeterminate mvhd) + ISO-BMFF compliant container for iOS / Android.
  - X1T Hybrid (x1t-hybrid / bxd-hybrid): TikTok bypass + bounded last-sample tail extension + free box.
  - X1T Clean (x1t-clean / bxd-clean): Pure video timescale patch with TikTok bypass (audio untouched).
  - X1T Repair: Lossless repair for broken non-standard containers.

FFmpeg is OPTIONAL (used for video thumbnails).
  - Put ffmpeg.exe + ffprobe.exe in a 'bin' folder next to FPSPatcherStudio.exe,
    set the folder in Settings > FFmpeg, or have them on PATH.

Notes:
  - Nothing here is verified to change TikTok or any platform's output resolution.
$signatureNote
"@ | Set-Content -Path (Join-Path $appDir "READ_ME_FIRST.txt") -Encoding UTF8

$releaseDir = Join-Path $root "release"
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
$zip = Join-Path $releaseDir "FPSPatcherStudio-v$version-win64.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $appDir -DestinationPath $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path -Leaf $zip)" | Set-Content -Path "$zip.sha256" -Encoding ASCII

# Optional installer (needs Inno Setup: per-user or system install)
$iscc = @(
    (Get-Command iscc.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

$setup = Join-Path $releaseDir "FPSPatcherStudio-v$version-Setup.exe"
if ($iscc) {
    $isccArgs = @("/DAppVersion=$version")
    if ($isProdSigning) {
        $cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `$q$signScript`$q -Path `$f"
        $isccArgs += @("/DSignEnabled", "/Sfpssign=$cmd")
    } elseif ($isDevSigning) {
        $cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `$q$signScript`$q -SignDev -Path `$f"
        $isccArgs += @("/DSignEnabled", "/Sfpssign=$cmd")
    }
    Step "inno setup" { & $iscc @isccArgs "build\installer.iss" | Out-Null }
    $setupHash = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()
    "$setupHash  $(Split-Path -Leaf $setup)" | Set-Content -Path "$setup.sha256" -Encoding ASCII
} else {
    Write-Host "Inno Setup not found: skipping installer (zip only)." -ForegroundColor Yellow
}

# Backward-compatible combined SHA-256 manifest (sha256sum format)
$manifestSha = Join-Path $releaseDir "FPSPatcherStudio-v$version.sha256"
Get-ChildItem $releaseDir -File | Where-Object { $_.Name -like "FPSPatcherStudio-v$version-*" -and $_.Extension -ne ".sha256" -and $_.Extension -ne ".json" } |
    ForEach-Object { "$((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower())  $($_.Name)" } |
    Set-Content -Path $manifestSha -Encoding ASCII
Write-Host "sha256 manifest: $manifestSha"

# Structured JSON Release Manifest
function Get-ArtifactSignatureStatus([string]$filePath, [string]$defaultStatus) {
    if (-not (Test-Path $filePath)) { return $defaultStatus }
    $ext = [System.IO.Path]::GetExtension($filePath).ToLower()
    if ($ext -in @(".exe", ".dll")) {
        $sig = Get-AuthenticodeSignature $filePath
        if ($sig.Status -eq "Valid") {
            return "production-signed (Authenticode)"
        } elseif ($sig.SignerCertificate -ne $null) {
            return "dev-signed (untrusted self-signed)"
        } else {
            return "unsigned"
        }
    }
    return $defaultStatus
}

# Resolve Git commit SHA
$gitSha = $null
if (Get-Command git.exe -ErrorAction SilentlyContinue) {
    try {
        $sha = (git rev-parse HEAD 2>&1).Trim()
        if ($LASTEXITCODE -eq 0 -and $sha.Length -eq 40) { $gitSha = $sha }
    } catch {}
}
if (-not $gitSha) {
    $headFile = Join-Path $root ".git\HEAD"
    if (Test-Path $headFile) {
        $head = (Get-Content $headFile -Raw).Trim()
        if ($head -match '^ref:\s*(.+)$') {
            $refFile = Join-Path (Join-Path $root ".git") $matches[1]
            if (Test-Path $refFile) {
                $gitSha = (Get-Content $refFile -Raw).Trim()
            }
        } elseif ($head.Length -eq 40) {
            $gitSha = $head
        }
    }
}
if (-not $gitSha) { $gitSha = "unknown" }

# Tool versions
$pyVer = try { ((uv run python --version 2>&1).Trim() -replace '^Python\s*', '') } catch { "unknown" }
$pyinstallerVer = try { (uv run --with pyinstaller pyinstaller --version 2>&1).Trim() } catch { "unknown" }
$isccVer = if ($iscc) { try { (& $iscc --version 2>&1).Trim() } catch { "unknown" } } else { $null }

$signtoolCmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
$signtoolPath = if ($signtoolCmd) { $signtoolCmd.Source } else { "$env:LOCALAPPDATA\Microsoft\WindowsApps\signtool.exe" }
$signtoolVer = if (Test-Path $signtoolPath) { (Get-Item $signtoolPath).VersionInfo.ProductVersion } else { $null }

# Artifacts list
$artifactFiles = @()
if (Test-Path $zip) { $artifactFiles += (Get-Item $zip) }
if (Test-Path $setup) { $artifactFiles += (Get-Item $setup) }

$artifacts = @()
foreach ($af in $artifactFiles) {
    $afHash = (Get-FileHash $af.FullName -Algorithm SHA256).Hash.ToLower()
    $afSig = Get-ArtifactSignatureStatus -filePath $af.FullName -defaultStatus $releaseSignatureStatus
    $artifacts += [ordered]@{
        filename         = $af.Name
        size_bytes       = $af.Length
        sha256           = $afHash
        signature_status = $afSig
    }
}

# SBOM detection
$sbomCandidates = @(
    (Join-Path $releaseDir "FPSPatcherStudio-v$version.spdx.json"),
    (Join-Path $releaseDir "FPSPatcherStudio-v$version.cdx.json"),
    (Join-Path $releaseDir "FPSPatcherStudio-v$version.sbom.json"),
    (Join-Path $root "sbom.json")
)
$sbomFound = ($sbomCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1)
$sbomRelPath = if ($sbomFound) { Split-Path -Leaf $sbomFound } else { $null }

$jsonManifestPath = Join-Path $releaseDir "FPSPatcherStudio-v$version.manifest.json"
$manifestObj = [ordered]@{
    manifest_version    = "1.0.0"
    app_name            = "FPS Patcher Studio"
    version             = $version
    git_commit          = $gitSha
    build_timestamp_utc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    signature_mode      = $releaseSignatureStatus
    tools               = [ordered]@{
        python      = $pyVer
        pyinstaller = $pyinstallerVer
        inno_setup  = $isccVer
        signtool    = $signtoolVer
    }
    artifacts           = $artifacts
    sbom_path           = $sbomRelPath
}

$manifestJson = $manifestObj | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($jsonManifestPath, $manifestJson, [System.Text.Encoding]::UTF8)
Write-Host "json manifest:   $jsonManifestPath"

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "== RELEASE BUILD COMPLETE" -ForegroundColor Green
Write-Host "Version:          v$version"
Write-Host "Signature Status: $releaseSignatureStatus"
Write-Host ("Zip:              $zip ({0:N1} MB)" -f ((Get-Item $zip).Length / 1MB))
if (Test-Path $setup) {
    Write-Host ("Setup:            $setup ({0:N1} MB)" -f ((Get-Item $setup).Length / 1MB))
}
Write-Host "SHA256 Manifest:  $manifestSha"
Write-Host "JSON Manifest:    $jsonManifestPath"
Write-Host "==========================================================" -ForegroundColor Green
