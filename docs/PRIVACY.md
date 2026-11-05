# Privacy policy — FPS Patcher Studio

**Effective date:** 2026-10-25

FPS Patcher Studio is a local Windows desktop utility for editing MP4/MOV
container metadata. It does not require an account and does not include
telemetry, analytics, advertising, or crash-reporting SDKs.

## Data the app processes locally

- **Media files you select:** read to inspect and patch container metadata. The
  app writes patched output only to the location you choose. It does not upload
  media.
- **Queue and settings:** `settings.json` and `queue.json` are stored under
  `%APPDATA%\FPSPatcherStudio`. They can contain local file paths and your UI
  preferences.
- **Logs and diagnostic reports:** written locally when you request them or when
  the app saves a diagnostic log. They can contain local file paths. Path
  masking is available in settings.
- **Watch Folder:** scans the folder you configure. Files are processed locally.

None of this local data is transmitted to the project or to a third party by the
app.

## Network access

This build disables network downloads. The app does not check GitHub for updates
and does not download FFmpeg. Use a bundled or locally installed FFmpeg binary;
the FFmpeg download buttons are hidden.

For development and testing only, the underlying download paths can be enabled
by starting the process with `FPS_PATCHER_ALLOW_NETWORK=1`. When that override is
set, the app may make these requests:

1. **Update check on startup (optional).** If `Check for updates on startup` is
   enabled, the app requests the latest release metadata from
   `https://api.github.com/repos/x1Swimzft/FPS-Patcher-Studio/releases/latest`.
2. **Update download (user action).** The installer is fetched from the GitHub
   release asset URL and verified with SHA-256 before launch.
3. **FFmpeg download (user action).** A BtbN FFmpeg build is fetched from
   `https://github.com/BtbN/FFmpeg-Builds/releases`.

No other network requests are made. The readiness scoring feature is completely
offline.

## Third-party services

- **GitHub** hosts release metadata and downloadable artifacts. It is contacted
  only when the development override is enabled. GitHub's privacy statement
  applies to those requests: <https://docs.github.com/en/site-policy/privacy-policies/github-privacy-statement>
- **BtbN FFmpeg-Builds** is hosted on GitHub. The FFmpeg binaries are subject to
  their own licenses; see `THIRD_PARTY_NOTICES.md`.

## Data sharing and retention

The project does not receive, sell, rent, or share user data. Local files remain
under your control. Removing `%APPDATA%\FPSPatcherStudio` removes the app's
settings, queue, and logs.

## System changes

The optional Explorer integration adds a per-user context-menu entry under
`HKCU\Software\Classes`. The uninstaller and the app's settings can remove it.
The app does not install services, drivers, or kernel components.

## Contact

Privacy questions: `x1swimzft@gmail.com`
