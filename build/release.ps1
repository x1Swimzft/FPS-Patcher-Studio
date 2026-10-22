<#
.SYNOPSIS
  Build the downloadable Windows app (portable zip) for FPS Patcher Studio.
.DESCRIPTION
  1. ruff + mypy + pytest gates (abort on failure; skip with -SkipChecks)
  2. PyInstaller one-folder windowed build
  3. Optional Authenticode signing (-Sign; see build\sign_binaries.ps1)
  4. Launch smoke test (exe must stay alive for a few seconds)
  5. release/FPSPatcherStudio-v<version>-win64.zip + .sha256 (+ Setup.exe and combined manifest)
  Run from project root:  powershell -ExecutionPolicy Bypass -File build\release.ps1
.PARAMETER Sign
  Sign the exe and installer (env CERT_PFX_PATH / CERT_PASSWORD). Unsigned with a warning if signtool is missing.
.PARAMETER GenerateSelfSigned
  With -Sign: create/use a local dev certificate when no production cert is configured (untrusted).
#>
param([switch]$SkipChecks, [switch]$Sign, [switch]$GenerateSelfSigned)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($name, [scriptblock]$cmd) {
    Write-Host "== $name" -ForegroundColor Cyan
    & $cmd
    if ($LASTEXITCODE -ne 0) { throw "$name failed (exit $LASTEXITCODE)" }
}

$version = (Select-String -Path "src\fps_patcher\__init__.py" -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
if (-not (Select-String -Path "build\version_info.txt" -SimpleMatch "'FileVersion', '$version.0'" -Quiet)) {
    throw "build\version_info.txt is out of sync with __version__ $version"
}

$signScript = Join-Path $PSScriptRoot "sign_binaries.ps1"
$signArgs = @()
if ($GenerateSelfSigned) { $signArgs += "-GenerateSelfSigned" }

if (-not $SkipChecks) {
    Step "ruff"   { uv run ruff check src tests }
    Step "mypy"   { uv run mypy src tests }
    Step "pytest" { uv run pytest -q }
}

Step "pyinstaller" { uv run --with pyinstaller pyinstaller build/fps_patcher.spec --noconfirm }

$appDir = Join-Path $root "dist\FPSPatcherStudio"
$exe = Join-Path $appDir "FPSPatcherStudio.exe"
if (-not (Test-Path $exe)) { throw "Build output missing: $exe" }

if ($Sign) {
    Step "sign exe" { powershell -NoProfile -ExecutionPolicy Bypass -File $signScript -Path $exe @signArgs }
}

# Smoke test: exe must still be running after 6 s (no instant crash)
Write-Host "== launch smoke test" -ForegroundColor Cyan
$proc = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 6
$alive = -not $proc.HasExited
if ($alive) { Stop-Process -Id $proc.Id -Force } else { throw "Smoke test failed: exe exited with code $($proc.ExitCode)" }

# Ship docs + first-run notes inside the app folder
foreach ($f in "README.md", "CHANGELOG.md") { if (Test-Path $f) { Copy-Item $f $appDir -Force } }
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
  - Windows SmartScreen may warn: the exe is unsigned.
"@ | Set-Content -Path (Join-Path $appDir "READ_ME_FIRST.txt") -Encoding UTF8

$releaseDir = Join-Path $root "release"
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
$zip = Join-Path $releaseDir "FPSPatcherStudio-v$version-win64.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $appDir -DestinationPath $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path -Leaf $zip)" | Set-Content -Path "$zip.sha256" -Encoding ASCII

# Optional installer (needs Inno Setup 6: per-user or system install)
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
$setup = Join-Path $releaseDir "FPSPatcherStudio-v$version-Setup.exe"
if ($iscc) {
    $isccArgs = @("/DAppVersion=$version")
    if ($Sign) {
        $cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `$q$signScript`$q $($signArgs -join ' ') -Path `$f"
        $isccArgs += @("/DSignEnabled", "/Sfpssign=$cmd")
    }
    Step "inno setup" { & $iscc @isccArgs "build\installer.iss" | Out-Null }
    $setupHash = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()
    "$setupHash  $(Split-Path -Leaf $setup)" | Set-Content -Path "$setup.sha256" -Encoding ASCII
} else {
    Write-Host "Inno Setup not found: skipping installer (zip only)." -ForegroundColor Yellow
}

# Combined SHA-256 manifest (sha256sum format) for every shipped artifact
$manifest = Join-Path $releaseDir "FPSPatcherStudio-v$version.sha256"
Get-ChildItem $releaseDir -File | Where-Object { $_.Name -like "FPSPatcherStudio-v$version-*" -and $_.Extension -ne ".sha256" } |
    ForEach-Object { "$((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower())  $($_.Name)" } |
    Set-Content -Path $manifest -Encoding ASCII
Write-Host "manifest: $manifest"

Write-Host "== DONE" -ForegroundColor Green
Write-Host "zip:    $zip"
Write-Host ("size:   {0:N1} MB" -f ((Get-Item $zip).Length / 1MB))
Write-Host "sha256: $hash"
