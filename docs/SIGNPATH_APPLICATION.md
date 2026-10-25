# SignPath Foundation application — FPS Patcher Studio

**Status:** prepared, not submitted.  
**Application page:** <https://signpath.org/apply.html>  
**Terms:** <https://signpath.org/terms.html>  
**Prepared:** 2026-10-25

SignPath must be applied for by the project owner from their own account. The
application requires the owner's identity, GitHub/SignPath MFA, acceptance of the
terms, and manual approval of every future signing request. This document gives
copy-paste answers and the remaining owner-only steps.

## Copy-paste answers

**Project name**

```
FPS Patcher Studio
```

**Repository URL**

```
https://github.com/x1Swimzft/FPS-Patcher-Studio
```

**License**

```
MIT License (OSI-approved). See LICENSE in the repository root.
```

**Download / release URL**

```
https://github.com/x1Swimzft/FPS-Patcher-Studio/releases
```

**Project description**

```
FPS Patcher Studio is a Windows x64 desktop utility for inspecting and editing
ISO-BMFF (MP4/MOV) container timing metadata for video creators. It reads local
media files selected by the user, writes patched output to a user-chosen folder,
and never uploads media. The application does not bypass DRM, authentication, or
platform access controls, and it does not modify the encoded H.264/HEVC/AAC
bitstream during container-only operations.

Artifacts distributed from GitHub Releases:
- FPSPatcherStudio.exe inside FPSPatcherStudio-v<version>-win64.zip
- FPSPatcherStudio-v<version>-Setup.exe (Inno Setup installer)

The project is MIT-licensed, publicly developed, and already publishes Windows
releases. The release pipeline is build/release.ps1: it runs ruff, mypy and
pytest, builds with PyInstaller from the public repository, runs a launch smoke
test, packages the portable ZIP and installer, and generates SHA-256 checksums.
Dependencies are pinned in uv.lock; the target runtime is CPython 3.11.

The request is for SignPath Foundation code signing to reduce Windows SmartScreen
and heuristic antivirus warnings for PyInstaller-packaged open-source releases.
```

**Artifacts to sign**

```
FPSPatcherStudio.exe
FPSPatcherStudio-v<version>-Setup.exe
```

**Code signing policy URL**

```
https://github.com/x1Swimzft/FPS-Patcher-Studio/blob/main/docs/CODE_SIGNING_POLICY.md
```

**Privacy policy URL**

```
https://github.com/x1Swimzft/FPS-Patcher-Studio/blob/main/docs/PRIVACY.md
```

**Contact**

```
x1swimzft@gmail.com
```

## Eligibility check

| SignPath requirement | Project status |
| --- | --- |
| OSI-approved license, no commercial dual license | ✅ MIT (`LICENSE`) |
| Public repository | ✅ GitHub `x1Swimzft/FPS-Patcher-Studio` |
| Already released in the form to sign | ⚠️ Public releases exist (v0.7.0); v0.9.0 is built locally but not yet published. The local v0.9.0 manifest still records the v0.7.0 baseline commit because the source changes are uncommitted. Commit v0.9.0, rebuild, publish the GitHub Release, and only then submit the signing request. |
| Functionality documented | ✅ README and `CHANGELOG.md`; the README download table still points at the public v0.7.0 release, so update it when v0.9.0 is actually published. |
| No malware / unwanted programs | ✅ Local media utility; no telemetry, no DRM circumvention, no credential/security exploitation |
| Maintained | ✅ Active development through v0.9.0 |
| Code signing policy on home page | ✅ `docs/CODE_SIGNING_POLICY.md`; add a README section linking it |
| Privacy policy | ✅ `docs/PRIVACY.md`; disclosed in the installer before installation and covers the optional GitHub update check and FFmpeg download |
| MFA on GitHub and SignPath | ⚠️ Owner must confirm/enable before applying |
| Authors / reviewers / approvers defined | ✅ Documented in `docs/CODE_SIGNING_POLICY.md`; owner must confirm the role assignment |
| Artifact product name/version metadata | ✅ `build/version_info.txt` and `build/fps_patcher.manifest`, synced with `pyproject.toml` and `__version__` |
| Verifiable build from source | ⚠️ Build script and lockfile are public, but release builds are currently local PowerShell. SignPath strongly prefers a trusted CI build system for origin verification. Add a GitHub Actions release build before or after approval. |
| Manual approval per release | ⚠️ Must be configured in SignPath after approval |

## Owner-only steps

These cannot be completed by an agent:

1. Confirm MFA is enabled on the GitHub account and will be enabled on SignPath.
2. Commit the v0.9.0 source changes and rebuild so the release manifest records the
   v0.9.0 commit, then publish the GitHub Release.
3. Open <https://signpath.org/apply.html> and submit the answers above.
4. Accept that the certificate is issued to **SignPath Foundation** and that
   SignPath Foundation is the publisher of signed builds.
5. After approval, create the SignPath project and configure:
   - artifact configuration for `FPSPatcherStudio.exe` and the installer;
   - release-signing policy with manual approval;
   - trusted build system / origin verification;
   - product name and version metadata restrictions.
6. Add the SignPath GitHub Actions integration and submit each release for
   manual approval.

## Integration notes after approval

- Sign the application executable **before** packaging it into the portable ZIP.
- Sign the Inno Setup installer after it is built.
- Do not sign upstream FFmpeg binaries. They may be included as unsigned
  upstream components in the signed package.
- Keep `FileVersion` / `ProductVersion` identical to the release version.
- Verify the signed artifacts with:
  ```powershell
  Get-AuthenticodeSignature .\FPSPatcherStudio.exe
  Get-AuthenticodeSignature .\FPSPatcherStudio-v0.9.0-Setup.exe
  ```
- Publish checksums for the signed artifacts, not the pre-signing builds.

## Risks and positioning

- SignPath accepts projects based on verifiable reputation. A newer project may
  be declined even when the checklist is complete.
- The repository currently uses terms such as “TikTok bypass” in marketing copy.
  Keep the application factual: the app edits local container metadata; it does
  not bypass DRM, access controls, authentication, or platform security. Consider
  toning down “bypass” language on the download page before review.
- The current v0.9.0 artifacts are **unsigned**. Do not claim SignPath signing
  until it is actually granted and a signed build is published.
- A SignPath certificate is not an EV certificate; SmartScreen reputation still
  builds over time.

## Related files

- `docs/CODE_SIGNING_POLICY.md`
- `docs/PRIVACY.md`
- `SECURITY.md`
- `BUILDING.md`
- `build/release.ps1`
