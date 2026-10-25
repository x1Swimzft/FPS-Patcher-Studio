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

The app makes network requests only in these cases:

1. **Update check on startup (optional).** If `Check for updates on startup` is
   enabled (default), the app requests the latest release metadata from
   `https://api.github.com/repos/x1Swimzft/FPS-Patcher-Studio/releases/latest`.
   GitHub receives standard HTTP request information such as your IP address and
   user agent. No media, local paths, or settings are sent. Disable this in
   **Settings → Behavior → Check for updates on startup**.
2. **Update download (user action).** If you choose to download an update, the
   installer is fetched from the GitHub release asset URL. The app verifies the
   published SHA-256 before launching it.
3. **FFmpeg download (user action).** If you click the FFmpeg download button,
   the app downloads a BtbN FFmpeg build from
   `https://github.com/BtbN/FFmpeg-Builds/releases`. Nothing is downloaded
   unless you request it.

No other network requests are made. The readiness scoring feature is completely
offline.

## Third-party services

- **GitHub** hosts release metadata and downloadable artifacts. GitHub's privacy
  statement applies to those requests: <https://docs.github.com/en/site-policy/privacy-policies/github-privacy-statement>
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
