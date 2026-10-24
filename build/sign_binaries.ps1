<#
.SYNOPSIS
  Authenticode-sign FPS Patcher Studio binaries with signtool.exe.
.DESCRIPTION
  Default targets: dist\FPSPatcherStudio\FPSPatcherStudio.exe and release\*-Setup.exe.
  Modes:
    - Production: default when called without -SignDev. Requires env CERT_PFX_PATH + CERT_PASSWORD.
    - Development: -SignDev (or -Dev / -GenerateSelfSigned) uses local build\dev_signing.pfx (untrusted).
  Signs with SHA-256 file digest and resilient RFC3161 timestamping with server fallbacks.
  Fails immediately if signtool is missing, certificate is invalid, or signing/timestamping fails.
#>
param(
    [string[]]$Path,
    [switch]$SignDev,
    [switch]$Dev,
    [switch]$GenerateSelfSigned,
    [string[]]$TimestampUrls = @(
        "http://timestamp.digicert.com",
        "http://timestamp.sectigo.com",
        "http://tsa.starfieldtech.com"
    ),
    [string]$TimestampUrl
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if ($TimestampUrl) {
    $TimestampUrls = @($TimestampUrl) + ($TimestampUrls | Where-Object { $_ -ne $TimestampUrl })
}

function Find-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $localApps = "$env:LOCALAPPDATA\Microsoft\WindowsApps\signtool.exe"
    if (Test-Path $localApps) { return $localApps }
    $toolsPath = Join-Path $PSScriptRoot "tools\signtool\signtool.exe"
    if (Test-Path $toolsPath) { return $toolsPath }
    $kits = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (Test-Path $kits) {
        $found = Get-ChildItem $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\' } |
            Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
        if ($found) { return $found }
    }
    $kits64 = "$env:ProgramFiles\Windows Kits\10\bin"
    if (Test-Path $kits64) {
        $found = Get-ChildItem $kits64 -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\' } |
            Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
        if ($found) { return $found }
    }
    return $null
}

$signtool = Find-SignTool
if (-not $signtool) {
    throw "signtool.exe not found on system. Install Windows SDK or ensure signtool.exe is on PATH. Signing aborted."
}

$isDev = $SignDev -or $Dev -or $GenerateSelfSigned

if ($isDev) {
    Write-Host "== Code Signing Mode: dev-signed (untrusted self-signed)" -ForegroundColor Yellow
    $pfx = Join-Path $PSScriptRoot "dev_signing.pfx"
    $certPassword = if ($env:CERT_PASSWORD) { $env:CERT_PASSWORD } else { "fps-dev-signing" }
    if (-not (Test-Path $pfx)) {
        Write-Host "== generating self-signed dev certificate: $pfx" -ForegroundColor Cyan
        $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=FPS Patcher Studio (Dev)" `
            -HashAlgorithm SHA256 -KeyLength 3072 -CertStoreLocation "Cert:\CurrentUser\My" `
            -NotAfter (Get-Date).AddYears(2)
        $secure = ConvertTo-SecureString $certPassword -AsPlainText -Force
        Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $secure | Out-Null
        Remove-Item "Cert:\CurrentUser\My\$($cert.Thumbprint)" -Force
    }
    $certPfxPath = $pfx
    Write-Warning "Binaries signed with this local certificate are NOT trusted by Windows SmartScreen or VirusTotal."
} else {
    Write-Host "== Code Signing Mode: production-signed (Authenticode)" -ForegroundColor Green
    if (-not $env:CERT_PFX_PATH) {
        throw "Production code signing requested, but CERT_PFX_PATH environment variable is not set. For dev signing, pass -SignDev."
    }
    if (-not (Test-Path $env:CERT_PFX_PATH)) {
        throw "Production certificate file not found: $env:CERT_PFX_PATH"
    }
    if (-not $env:CERT_PASSWORD) {
        throw "Production code signing requested, but CERT_PASSWORD environment variable is not set."
    }
    $certPfxPath = $env:CERT_PFX_PATH
    $certPassword = $env:CERT_PASSWORD
}

if (-not $Path) {
    $Path = @(Join-Path $root "dist\FPSPatcherStudio\FPSPatcherStudio.exe")
    $Path += @(Get-ChildItem (Join-Path $root "release") -Filter "*-Setup.exe" -ErrorAction SilentlyContinue |
        ForEach-Object FullName)
}

if (-not $Path -or $Path.Count -eq 0) {
    throw "No target binaries specified or found to sign."
}

foreach ($file in $Path) {
    $file = $file.Trim('"')
    if (-not (Test-Path $file)) {
        throw "Cannot sign missing file: $file"
    }

    Write-Host "== signing $file" -ForegroundColor Cyan
    $signed = $false
    $lastError = ""

    foreach ($ts in $TimestampUrls) {
        Write-Host "   Timestamp server: $ts" -ForegroundColor DarkGray
        $procOutput = & $signtool sign /f $certPfxPath /p $certPassword /fd SHA256 /tr $ts /td SHA256 /d "FPS Patcher Studio" $file 2>&1
        if ($LASTEXITCODE -eq 0) {
            $signed = $true
            Write-Host "   Signed and timestamped successfully via $ts" -ForegroundColor Green
            break
        } else {
            $lastError = ($procOutput | Out-String).Trim()
            Write-Warning "   Timestamp server $ts failed (code $LASTEXITCODE). Trying next fallback..."
        }
    }

    if (-not $signed) {
        throw "Signing failed for $file. All timestamp servers exhausted. Last error: $lastError"
    }

    if (-not $isDev) {
        Write-Host "== verifying production signature for $file" -ForegroundColor Cyan
        $verifyOutput = & $signtool verify /pa $file 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "signtool verify /pa failed for $file (exit $LASTEXITCODE): $(($verifyOutput | Out-String).Trim())"
        }
        Write-Host "   Verified production Authenticode signature on $file" -ForegroundColor Green
    } else {
        $sig = Get-AuthenticodeSignature $file
        if (-not $sig -or -not $sig.SignerCertificate) {
            throw "Verification failed: $file does not contain a valid signature block."
        }
        Write-Host "   Verified self-signed certificate on $file [Thumbprint: $($sig.SignerCertificate.Thumbprint)]" -ForegroundColor Yellow
    }
}
