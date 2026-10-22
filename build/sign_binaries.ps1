<#
.SYNOPSIS
  Authenticode-sign FPS Patcher Studio binaries with signtool.exe.
.DESCRIPTION
  Default targets: dist\FPSPatcherStudio\FPSPatcherStudio.exe and release\*-Setup.exe.
  Certificate: env CERT_PFX_PATH + CERT_PASSWORD (production), or -GenerateSelfSigned to
  create a local developer .pfx (build\dev_signing.pfx; NOT trusted by SmartScreen).
  Signs with SHA-256 file digest + RFC3161 timestamp. If signtool.exe is missing or no
  certificate is configured, warns and exits 0 (build continues unsigned).
  Examples:
    powershell -File build\sign_binaries.ps1
    powershell -File build\sign_binaries.ps1 -GenerateSelfSigned
    powershell -File build\sign_binaries.ps1 -Path release\FPSPatcherStudio-v0.3.5-Setup.exe
#>
param(
    [string[]]$Path,
    [switch]$GenerateSelfSigned,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Find-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $kits = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (Test-Path $kits) {
        return Get-ChildItem $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\' } |
            Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
    }
    return $null
}

$signtool = Find-SignTool
if (-not $signtool) {
    Write-Warning "signtool.exe not found (install Windows SDK). Skipping signing."
    exit 0
}

if (-not $Path) {
    $Path = @(Join-Path $root "dist\FPSPatcherStudio\FPSPatcherStudio.exe")
    $Path += @(Get-ChildItem (Join-Path $root "release") -Filter "*-Setup.exe" -ErrorAction SilentlyContinue |
        ForEach-Object FullName)
}

$selfSigned = $false
if (-not $env:CERT_PFX_PATH) {
    if (-not $GenerateSelfSigned) {
        Write-Warning "CERT_PFX_PATH not set (use -GenerateSelfSigned for a dev cert). Skipping signing."
        exit 0
    }
    $pfx = Join-Path $PSScriptRoot "dev_signing.pfx"
    if (-not $env:CERT_PASSWORD) {
        # Throwaway dev-only password; the self-signed cert is untrusted and gitignored (*.pfx).
        $env:CERT_PASSWORD = "fps-dev-signing"
    }
    if (-not (Test-Path $pfx)) {
        Write-Host "== generating self-signed dev certificate" -ForegroundColor Cyan
        $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=FPS Patcher Studio (Dev)" `
            -HashAlgorithm SHA256 -KeyLength 3072 -CertStoreLocation "Cert:\CurrentUser\My" `
            -NotAfter (Get-Date).AddYears(2)
        $secure = ConvertTo-SecureString $env:CERT_PASSWORD -AsPlainText -Force
        Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $secure | Out-Null
        Remove-Item "Cert:\CurrentUser\My\$($cert.Thumbprint)" -Force
    }
    $env:CERT_PFX_PATH = $pfx
    $selfSigned = $true
}
if (-not (Test-Path $env:CERT_PFX_PATH)) { throw "CERT_PFX_PATH not found: $env:CERT_PFX_PATH" }
if (-not $env:CERT_PASSWORD) { throw "CERT_PASSWORD is required with CERT_PFX_PATH." }

foreach ($file in $Path) {
    $file = $file.Trim('"')
    if (-not (Test-Path $file)) { Write-Warning "Not found, skipped: $file"; continue }
    Write-Host "== signing $file" -ForegroundColor Cyan
    & $signtool sign /f $env:CERT_PFX_PATH /p $env:CERT_PASSWORD /fd SHA256 /tr $TimestampUrl /td SHA256 `
        /d "FPS Patcher Studio" $file
    if ($LASTEXITCODE -ne 0) { throw "signtool sign failed for $file (exit $LASTEXITCODE)" }
    if (-not $selfSigned) {
        & $signtool verify /pa $file
        if ($LASTEXITCODE -ne 0) { throw "signtool verify failed for $file (exit $LASTEXITCODE)" }
    }
}
if ($selfSigned) {
    Write-Warning "Self-signed dev certificate: SmartScreen/AV will NOT trust it. Use a real certificate for release."
}
