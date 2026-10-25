# Code signing policy

**Free code signing provided by SignPath.io, certificate by SignPath Foundation.**

This policy applies to official Windows release artifacts published from
[`x1Swimzft/FPS-Patcher-Studio`](https://github.com/x1Swimzft/FPS-Patcher-Studio).

## Signing scope

Signed artifacts:

- `FPSPatcherStudio.exe` (the application executable inside the portable ZIP)
- `FPSPatcherStudio-v<version>-Setup.exe` (Inno Setup installer)

The portable ZIP and checksum/manifest files are distribution containers, not
separately signed binaries.

## Team roles

| Role | Member |
| --- | --- |
| Authors / committers | [`@x1Swimzft`](https://github.com/x1Swimzft) (repository owner) |
| Reviewers | [`@x1Swimzft`](https://github.com/x1Swimzft); non-committer changes require review by a committer |
| Approvers | [`@x1Swimzft`](https://github.com/x1Swimzft); every signing request is approved manually |

All project members must use multi-factor authentication for both GitHub and
SignPath access. The project owner must confirm that MFA is enabled before a
SignPath application is submitted.

## Build provenance

- Source code, build scripts, PyInstaller spec, and Inno Setup script are public.
- Python dependencies are pinned in `uv.lock`; the build targets CPython 3.11.
- The release pipeline is `build/release.ps1`:
  1. runs `ruff`, `mypy`, and `pytest`;
  2. builds the one-folder PyInstaller application;
  3. runs a launch smoke test;
  4. packages the portable ZIP and Inno Setup installer;
  5. generates SHA-256 checksums and a JSON release manifest.
- `build/version_info.txt` and `build/fps_patcher.manifest` embed the product name
  and version. The version is kept in sync with `pyproject.toml` and
  `src/fps_patcher/__init__.py`.

## Signing process

1. Build release artifacts from the public repository at the release commit.
2. Submit `FPSPatcherStudio.exe` and `FPSPatcherStudio-v<version>-Setup.exe` to
   SignPath as a signing request.
3. An approver reviews the request and approves it manually.
4. Publish only the signed artifacts returned by SignPath.
5. Publish SHA-256 checksums and the release manifest alongside the artifacts.

No release is signed automatically without manual approval. Test or local
developer builds are not submitted for release signing.

## Privacy policy

The application's privacy policy is in [`docs/PRIVACY.md`](PRIVACY.md).

## Certificate and publisher

The certificate is issued to **SignPath Foundation**, not to an individual
maintainer. SignPath Foundation is therefore the publisher of signed builds.
SignPath Foundation is not a Certificate Authority and does not issue
certificates directly to projects.

## Contact

Security and signing questions: `x1swimzft@gmail.com`  
Repository: <https://github.com/x1Swimzft/FPS-Patcher-Studio>
