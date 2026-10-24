# Security Policy — FPS Patcher Studio

The FPS Patcher Studio team takes the security and integrity of our software seriously. This document outlines our supported versions, vulnerability reporting process, binary provenance guarantees, cryptographic verification procedures, and false-positive disclosure policy.

---

## 1. Supported Versions

We provide active security fixes, dependency patches, and vulnerability triage for the following versions:

| Version | Supported | Status / Notes |
|---|---|---|
| **0.7.x** | ✅ Yes | Current stable release branch. Active security maintenance. |
| **0.6.x** | ✅ Yes | Maintained previous release branch. |
| **0.5.x** | ❌ No | Deprecated. Users must upgrade to v0.7.0+ for zero-freeze engine and latest fixes. |
| **< 0.5.x** | ❌ No | Deprecated legacy builds. |

---

## 2. Reporting a Vulnerability

If you discover a potential security vulnerability in FPS Patcher Studio, please report it **responsibly and privately**. Please do not open a public GitHub issue for undisclosed vulnerabilities.

### 2.1. Preferred Reporting Channels

1. **GitHub Security Advisory (Recommended)**:  
   Navigate to [Security Advisories](https://github.com/x1Swimzft/FPS-Patcher-Studio/security/advisories) on GitHub and click **"Report a vulnerability"**. This allows encrypted communication within GitHub's secure infrastructure.
2. **Direct Security Contact**:  
   If you cannot use GitHub Security Advisories, send an email to:  
   **`x1swimzft@gmail.com`** with the subject tag `[SECURITY VULNERABILITY] FPS Patcher Studio`.

### 2.2. What to Include in Your Report

To help us investigate and remediate the issue promptly, please include:
- A clear description of the vulnerability and its potential impact.
- Exact version of FPS Patcher Studio and operating system build tested.
- Step-by-step reproduction instructions or a minimal Proof of Concept (PoC) file (e.g., a specially crafted MP4/MOV container).
- Any observed crash logs, memory dumps, or anomalous behavior.

### 2.3. Response Timelines & SLA

- **Initial Acknowledgment**: Within **48 hours** of report receipt.
- **Triage & Validation**: Within **5 business days**, confirming reproduction and assigning a severity rating (CVSS v3.1).
- **Remediation & Patch**: Target delivery within **14 to 30 days** depending on vulnerability complexity.
- **Coordinated Public Disclosure**: Once a patched release is published, a coordinated CVE / security advisory will be issued with full credit to the reporter.

### 2.4. Safe Harbor Policy

We consider security research conducted in good faith to be authorized. If you make a reasonable effort to avoid privacy violations, data destruction, and service disruption, we will not pursue legal action against you or seek law enforcement intervention.

---

## 3. Binary Provenance & Build Reproducibility

We are committed to providing verifiable, tamper-evident software releases.

1. **Open-Source Codebase**: All code, build configurations, and packaging specifications are publicly visible in our repository:
   - Source root: [`src/fps_patcher/`](src/fps_patcher/)
   - Packaging spec: [`build/fps_patcher.spec`](build/fps_patcher.spec)
   - Installer script: [`build/installer.iss`](build/installer.iss)
   - Release orchestrator: [`build/release.ps1`](build/release.ps1)
2. **Reproducible Builds**: Our build process uses explicit version pinning with Astral `uv` (`uv.lock`) and CPython 3.11. Instructions for reproducing builds from source are provided in [BUILDING.md](BUILDING.md).
3. **Cryptographic Release Manifests**: Every release publishes cryptographic hashes of every distributed installer and portable archive.

---

## 4. Cryptographic Verification Guide

Before executing downloaded binaries, verify their integrity using SHA-256 checksums and digital signature validation.

### 4.1. Verifying SHA-256 Checksums

Compare the hash of your downloaded file against the published release manifest.

#### PowerShell (Windows 10/11):
```powershell
# Verify Setup Installer (v0.7.0)
(Get-FileHash -Path "FPSPatcherStudio-v0.7.0-Setup.exe" -Algorithm SHA256).Hash.ToLower() -eq "f82e527ab980268daae564b3dcd100ff6f06d1ad83ed6d6cde7d91ee83429631"

# Verify Portable ZIP Archive (v0.7.0)
(Get-FileHash -Path "FPSPatcherStudio-v0.7.0-win64.zip" -Algorithm SHA256).Hash.ToLower() -eq "a169b861cdac077d43b39e88591bdc42881b6be6bb26ecb8d38f9fae0a642ef9"
```
*If the result outputs `True`, the file is authentic and unaltered.*

#### Windows Command Prompt (`cmd.exe`):
```cmd
certutil -hashfile FPSPatcherStudio-v0.7.0-Setup.exe SHA256
certutil -hashfile FPSPatcherStudio-v0.7.0-win64.zip SHA256
```

#### Linux / WSL / macOS:
```bash
echo "f82e527ab980268daae564b3dcd100ff6f06d1ad83ed6d6cde7d91ee83429631  FPSPatcherStudio-v0.7.0-Setup.exe" | sha256sum -c -
echo "a169b861cdac077d43b39e88591bdc42881b6be6bb26ecb8d38f9fae0a642ef9  FPSPatcherStudio-v0.7.0-win64.zip" | sha256sum -c -
```

---

### 4.2. Authenticode Digital Signature Verification

Official Windows release binaries are signed using Microsoft Authenticode with a SHA-256 digest and an RFC 3161 timestamp (`http://timestamp.digicert.com`).

#### Inspect via PowerShell:
```powershell
Get-AuthenticodeSignature -FilePath "FPSPatcherStudio-v0.7.0-Setup.exe"
```

#### Understanding Signature Status:
- **Developer Builds / Open-Source Releases**: Release v0.7.0 is signed using an internal project code signing certificate (`CN=FPS Patcher Studio (Dev)`).
- **Self-Signed Status Note**: Because this certificate is generated by the open-source project and is not yet rooted in a commercial Certificate Authority (such as DigiCert or Sectigo), Windows SmartScreen and VirusTotal will note the signature as untrusted root (`invalid-signature`). This indicates an unverified root CA, **not** that the binary is compromised or corrupt.
- Commercial EV Code Signing certificate acquisition is tracked in our release roadmap.

---

## 5. False Positive Disclosure & Transparency

Because FPS Patcher Studio is packaged into standalone Windows executables using PyInstaller and Inno Setup without a commercial Extended Validation (EV) certificate, certain heuristic antivirus engines may flag the newly compiled binaries as suspicious.

- **Verified Facts**: 66+ industry-leading antivirus engines (including Microsoft Defender, Kaspersky, BitDefender, ESET, Sophos, Avast, and CrowdStrike) report our binaries as **100% clean and undetected**.
- **Known Heuristic Detections**: Low-reputation heuristic engines occasionally trigger generic detections on newly compiled PyInstaller bundles.
- **Formal Dispute Dossier**: For full technical details and vendor submission templates, see [docs/FALSE_POSITIVE_DISPUTES.md](docs/FALSE_POSITIVE_DISPUTES.md).

---

## 6. Application Security Posture & Isolation

FPS Patcher Studio is designed according to the principle of least privilege:
- **Standard User Execution**: Requires no administrator rights (`requireAdministrator` is disabled; runs as `asInvoker`).
- **Filesystem Boundaries**: Only accesses media files selected by the user and writes settings/logs strictly inside `%APPDATA%\FPSPatcherStudio\`.
- **Atomic File Writing**: Video patching always writes to temporary files (`.part`) and verifies container integrity before replacing or producing final output files, preventing data loss.
- **Zero Involuntary Telemetry**: No user analytics, video metadata, or tracking payloads are ever collected or transmitted over the internet.
