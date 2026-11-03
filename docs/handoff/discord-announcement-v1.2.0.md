# Discord announcement — FPS Patcher Studio v1.2.0

Draft only. The owner posts it. Keep the unsigned wording unless a signed build
actually exists.

---

**FPS Patcher Studio v1.2.0 is out**

This release makes bitrate visible before patching, adds a target you control, and prompts when a newer build exists.

**What's new**
- **Bitrate plan** — queue rows and the Inspector show the source bitrate, or `source → target` when auto-cap applies.
- **Adjustable target** — `bitrate_target_mbps` in Settings, 1–24 Mbps, default 16. With auto-cap on, sources at or below the target stay lossless; higher sources are re-encoded to H.264 at the target.
- **Startup update prompt** — when a newer release exists, the update dialog opens after launch and still asks before downloading or installing; No leaves the toolbar button available.

**Download**
- Installer: https://github.com/x1Swimzft/FPS-Patcher-Studio/releases/download/v1.2.0/FPSPatcherStudio-v1.2.0-Setup.exe
- Portable ZIP: https://github.com/x1Swimzft/FPS-Patcher-Studio/releases/download/v1.2.0/FPSPatcherStudio-v1.2.0-win64.zip

**SHA-256**
```
98f840d64654f5ae824a70e21df5c91578f963edafd1684f3421d425a4c90973  FPSPatcherStudio-v1.2.0-Setup.exe
ae5032e1431fdcd68b37d78cfb870da234919b25e4c21275da73a41523c44c7f  FPSPatcherStudio-v1.2.0-win64.zip
```

Verify in PowerShell:
```powershell
Get-FileHash .\FPSPatcherStudio-v1.2.0-Setup.exe -Algorithm SHA256
Get-FileHash .\FPSPatcherStudio-v1.2.0-win64.zip -Algorithm SHA256
```

**About the Windows warning**
These builds are unsigned. SmartScreen may show "Unknown publisher" or "Windows protected your PC." Expected for an unsigned build, not proof of malware. Check SHA-256 and download only from the official release page. Code signing is not active.

**Scope**
The app edits local MP4/MOV/M4V container metadata and copies video payload unless bitrate capping is on. It does not bypass DRM, platform access controls, or upload checks, and it does not guarantee that a platform will skip re-encoding. No DRM or platform bypass is claimed.

Changelog: https://github.com/x1Swimzft/FPS-Patcher-Studio/blob/main/CHANGELOG.md
