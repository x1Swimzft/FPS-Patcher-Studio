# Code signing with SignPath (setup and application guide)

Canonical guide for signing FPS Patcher Studio v1.0.0 Windows release artifacts
with SignPath Foundation through the GitHub trusted build system.

- Workflow: [`.github/workflows/release.yml`](../.github/workflows/release.yml)
- Artifact configuration: [`build/signpath-artifact-configuration.xml`](../build/signpath-artifact-configuration.xml)
- Policy: [`docs/CODE_SIGNING_POLICY.md`](CODE_SIGNING_POLICY.md)

**Status:** v1.0.0 is unsigned. Signing turns on only after the SignPath project
exists and the repository variables/secret below are set.

## 1. What gets signed

| Artifact | Path inside the uploaded artifact ZIP | Signed |
| --- | --- | --- |
| Inno Setup installer | `FPSPatcherStudio-v1.0.0-Setup.exe` | yes |
| Portable app | `FPSPatcherStudio-v1.0.0-win64.zip` → `FPSPatcherStudio/FPSPatcherStudio.exe` | yes |
| Checksums, SBOM, manifest | `*.sha256`, `*.cdx.json`, `*.manifest.json` | no (not binaries) |

`actions/upload-artifact@v4` stores the uploaded files in a ZIP, so the root
element of the artifact configuration is `<zip-file>`. Content of
[`build/signpath-artifact-configuration.xml`](../build/signpath-artifact-configuration.xml)
(leading comment omitted):

```xml
<?xml version="1.0" encoding="utf-8"?>
<artifact-configuration xmlns="http://signpath.io/artifact-configuration/v1">
  <zip-file>
    <pe-file path="FPSPatcherStudio-*-Setup.exe" product-name="FPS Patcher Studio">
      <authenticode-sign/>
    </pe-file>
    <zip-file path="FPSPatcherStudio-*-win64.zip">
      <pe-file path="FPSPatcherStudio/FPSPatcherStudio.exe" product-name="FPS Patcher Studio">
        <authenticode-sign/>
      </pe-file>
    </zip-file>
  </zip-file>
</artifact-configuration>
```

Notes:

- SignPath defaults `max-matches` to 1, so each wildcard must match exactly one
  file. A stale extra `*-Setup.exe` or `*-win64.zip` in `release/` fails the run.
- `product-name` is a metadata restriction: both binaries declare
  `ProductName=FPS Patcher Studio` (`build/version_info.txt`,
  `VersionInfoProductName` in `build/installer.iss`).
- Path separators inside a ZIP may be `/` or `\`; matching is case-insensitive.

## 2. SignPath application answers (v1.0.0)

Submit at <https://signpath.org/apply>. Copy-paste values:

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

**Release / download URL**

```
https://github.com/x1Swimzft/FPS-Patcher-Studio/releases
```

**Project description**

```
FPS Patcher Studio is an MIT-licensed Windows x64 desktop utility for inspecting
and editing ISO-BMFF (MP4/MOV) container timing metadata for video creators. It
reads local media files selected by the user, writes patched output to a
user-chosen folder, and never uploads media. It does not bypass DRM,
authentication, or platform access controls, and it does not modify the encoded
H.264/HEVC/AAC bitstream during container-only operations.

Artifacts distributed from GitHub Releases (v1.0.0):
- FPSPatcherStudio-v1.0.0-Setup.exe (Inno Setup installer)
- FPSPatcherStudio/FPSPatcherStudio.exe inside FPSPatcherStudio-v1.0.0-win64.zip
  (portable build)

Builds are produced from the public repository by GitHub Actions
(.github/workflows/release.yml) on windows-latest: uv sync --frozen, pytest,
PyInstaller (build/fps_patcher.spec), FFmpeg bundling, then
build/release.ps1 which packages the ZIP and installer and writes SHA-256
checksums, a CycloneDX 1.5 SBOM and a JSON manifest. Dependencies are pinned in
uv.lock; the target runtime is CPython 3.11.

The request is for SignPath Foundation code signing to reduce Windows SmartScreen
and heuristic antivirus warnings for PyInstaller-packaged open-source releases.
```

**Artifacts to sign**

```
FPSPatcherStudio-v1.0.0-Setup.exe
FPSPatcherStudio/FPSPatcherStudio.exe (inside FPSPatcherStudio-v1.0.0-win64.zip)
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
x1Swimzft (GitHub) — x1swimzft@gmail.com
```

## 3. GitHub configuration

SignPath project settings (created by the owner after approval):

| Setting | Value |
| --- | --- |
| Project slug | `fps-patcher-studio` |
| Signing policy slug | `release-signing-policy` (manual approval) |
| Artifact configuration slug | `release-files` (contents of `build/signpath-artifact-configuration.xml`) |
| Trusted build system | GitHub.com, linked to the project |

Repository → Settings → Secrets and variables → Actions:

| Kind | Name | Value |
| --- | --- | --- |
| Variable | `SIGNPATH_ENABLED` | `true` to submit signing requests; unset/`false` builds unsigned |
| Variable | `SIGNPATH_ORG_ID` | SignPath organization ID |
| Variable | `BUNDLE_FFMPEG` | Optional. `false` skips the FFmpeg download/bundle; the default is to bundle it |
| Secret | `SIGNPATH_API_TOKEN` | API token of a SignPath user with submitter permission |

Do not put the token in a variable; it is a secret.

## 4. What the workflow does

Unsigned (`SIGNPATH_ENABLED` unset or not `true`):

1. `uv sync --frozen`, `uv run pytest -q`.
2. Installs Inno Setup via Chocolatey and puts `ISCC.exe` on `PATH` (the job
   fails if it is not found).
3. Bundles `ffmpeg.exe` + `ffprobe.exe` from the BtbN GPL build into `bin/`
   (unless `BUNDLE_FFMPEG=false`).
4. Generates `release/FPSPatcherStudio-v1.0.0.cdx.json` *before* the build, so
   `release.ps1` records `sbom_path` in the JSON manifest.
5. Runs `build/release.ps1 -SkipChecks` (pytest already ran; ruff/mypy run in
   `security-audit.yml`).
6. Uploads `fps-patcher-studio-unsigned-release` with the Setup EXE, portable
   ZIP, `.sha256` sidecars, `.cdx.json` and manifest JSON.

Signed (same as above, plus):

7. Submits the uploaded artifact to SignPath and waits for the manual approval.
8. Removes the pre-signing `.sha256` files and `*.manifest.json` from the signed
   output, then uploads the remaining files as
   `fps-patcher-studio-signed-release`. Recompute checksums after download and
   publish only those.

No GitHub Release is created automatically and nothing is published by the
workflow.

## 5. Owner-only steps

An agent cannot do these:

1. Enable MFA on the GitHub account and on SignPath.
2. Publish the v1.0.0 GitHub Release (the workflow only uploads artifacts).
3. Trigger the release workflow once and confirm the unsigned artifacts are
   produced.
4. Submit the application at <https://signpath.org/apply> with the answers above.
5. Accept that the certificate is issued to **SignPath Foundation**, so SignPath
   Foundation is the publisher of signed builds.
6. Install the [SignPath GitHub App](https://github.com/apps/signpath) and add the
   GitHub.com trusted build system to the SignPath organization, then link it to
   the project.
7. Create the project, artifact configuration (`release-files`) and signing policy
   (`release-signing-policy`), and set the variables/secret from section 3.
8. Approve every signing request manually.

## 6. Limitations

- **The app copy inside the installer is not deep-signed.** The initial
  configuration signs `Setup.exe` and the app in the portable ZIP. Inno Setup
  embeds an unsigned copy of `FPSPatcherStudio.exe`, so extracting the app from
  the installer yields an unsigned executable. Installing through the signed
  installer still validates the package signature.
- **Checksums and the manifest are generated before signing.** `release.ps1`
  writes `*.sha256` and `*.manifest.json` (including `signature_mode:
  "unsigned"`) before SignPath runs. The workflow removes those files from the
  signed output before upload. Recompute checksums from the signed binaries and
  publish only those.
- **Follow-up: two-stage build.** To cover both limitations, sign
  `FPSPatcherStudio.exe` in a first signing request, unzip the signed app back
  into `dist/`, rebuild the ZIP and installer, then submit only the installer and
  ZIP in a second request. That requires a second artifact configuration and a
  workflow change; it is not part of this initial setup.
- **Version metadata is not enforced yet.** `product-name` is restricted, but
  `product-version` needs a `version` parameter passed with the signing request.
  Add it once the release flow is stable.
- **Action version.** The workflow pins
  `signpath/github-action-submit-signing-request@v1`; upstream documentation
  currently shows `@v3`. Confirm the inputs behave as expected (or upgrade the
  major version) before enabling signing.
- **Review risk.** SignPath accepts projects on verifiable reputation and may
  decline a new project even when every item above is complete. Keep release and
  README wording factual: the app edits local container metadata and does not
  bypass DRM or platform security.

## 7. Verifying signed artifacts

After downloading the signed artifact:

```powershell
Get-AuthenticodeSignature .\FPSPatcherStudio-v1.0.0-Setup.exe | Format-List *
Expand-Archive .\FPSPatcherStudio-v1.0.0-win64.zip .\verify
Get-AuthenticodeSignature .\verify\FPSPatcherStudio\FPSPatcherStudio.exe | Format-List *
```

A valid SignPath Foundation signature has status `Valid` and a signer subject
containing `SignPath Foundation`.

## 8. References

- SignPath Foundation conditions and terms: <https://signpath.org/terms>
- SignPath OSS application: <https://signpath.org/apply>
- GitHub trusted build system: <https://docs.signpath.io/trusted-build-systems/github>
- Artifact configuration syntax: <https://docs.signpath.io/artifact-configuration/syntax>
- Action repository: <https://github.com/SignPath/github-action-submit-signing-request>
