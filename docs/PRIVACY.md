# Privacy policy — FPS Patcher Studio

**Effective date:** 2026-11-08

FPS Patcher Studio is a local Windows desktop utility for editing MP4/MOV
container metadata and producing TikTok MPEG-TS presets. It does not require an
account and does not include telemetry, analytics, advertising, or
crash-reporting SDKs.

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

The app can make these requests:

1. **Update check on startup (on by default).** If `Check for updates on startup`
   is enabled in Settings, the app requests the latest release metadata from
   `https://api.github.com/repos/x1Swimzft/FPS-Patcher-Studio/releases/latest`.
2. **Update download (user action).** When you accept an update, the installer or
   portable ZIP is fetched from the GitHub release asset URL and verified with
   SHA-256 before use. Builds are currently unsigned; when the release publishes a
   SHA-256, the app warns and applies the unsigned installer or portable update
   only after that checksum matches. If no checksum is published, Authenticode
   verification is required.
3. **FFmpeg download (opt-in).** FFmpeg auto-download stays disabled by default.
   The download buttons are hidden unless the process is started with
   `FPS_PATCHER_ALLOW_NETWORK=1`; then a BtbN FFmpeg build is fetched from
   `https://github.com/BtbN/FFmpeg-Builds/releases`.

No other network requests are made. Media files are never uploaded. The readiness
scoring feature is completely offline.

## Third-party services

- **GitHub** hosts release metadata and downloadable artifacts. It is contacted
  for the update check and update download. GitHub's privacy statement applies:
  <https://docs.github.com/en/site-policy/privacy-policies/github-privacy-statement>
- **BtbN FFmpeg-Builds** is hosted on GitHub and is contacted only when the FFmpeg
  download override is enabled. The FFmpeg binaries are subject to their own
  licenses; see `THIRD_PARTY_NOTICES.md`.

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
