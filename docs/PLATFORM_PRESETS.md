# Platform Presets & Readiness Scoring

**Version:** 0.10.0  
**Evidence reviewed:** 2026-10-25  
**Scope:** read-only pre-flight checks. No media is modified by selecting a profile.

FPS Patcher Studio can grade each queued file against a platform profile. The
profile is a **readiness layer**, not a platform-specific binary rewrite. It does
not claim to bypass TikTok, Instagram, or YouTube compression. No app can
guarantee that a social platform will not re-encode an uploaded video.

## Evidence labels

| Label | Meaning |
| --- | --- |
| **Documented** | The platform explicitly publishes the condition. |
| **Recommended** | A published setting, not a strict acceptance rule. |
| **Heuristic** | A local file-level warning derived from practical guidance, not guaranteed by the platform. |
| **Unknown** | Probe data is missing or the condition cannot be verified. |

## Profile matrix

| Profile | Container / codecs | Frame geometry | Frame rate | Duration | Audio | Bitrate warning |
| --- | --- | --- | --- | --- | --- | --- |
| **Generic (No Platform)** | MP4/MOV; common codecs accepted | not checked | not checked | not checked | AAC 48 kHz stereo recommended | none |
| **X1T — TikTok (No Compress)** | MP4 recommended, MOV/WebM accepted; H.264 recommended, H.265/VP8/VP9 accepted — **documented** | 360–4096 px each side — **documented**; 9:16 recommended — **heuristic** | 23–60 fps — **documented** | 10 min API limit — **documented**; in-app limits vary | AAC 48 kHz stereo — **heuristic** | 20 Mbps — **heuristic** |
| **X1T — Instagram Reels** | MP4/MOV; H.264/HEVC recommended — **heuristic** | 1.91:1 to 9:16 — **documented**; 9:16 and ≤1920 px — **heuristic** | minimum 30 fps — **documented**; 60 fps ceiling — **heuristic** | 3 min practical Reels window — **documented** recommendation | AAC 48 kHz stereo — **heuristic** | 25 Mbps — **heuristic** |
| **X1T — YouTube Shorts** | MP4; H.264 recommended — **documented** | square or vertical — **documented**; ≤1080p upload — **documented** | upload at source rate; 24–60 fps common — **documented** recommendation | 3 min — **documented** | AAC-LC 48 kHz stereo — **documented** recommendation | none: YouTube states no bitrate limit is required — **documented** |

The selector applies globally to the queue and is stored in `settings.json`. The
patch preset (`X1T For Mobile`, etc.) remains independently selectable; choosing
a platform profile does not silently change the patch strategy, codec, bitrate,
or container.

## Sources

| Platform | Source | What it supports |
| --- | --- | --- |
| TikTok | <https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide> | MP4/WebM/MOV, H.264/H.265/VP8/VP9, 23–60 fps, 360–4096 px, 4 GB, 10 min API duration. |
| TikTok | <https://support.tiktok.com/en/using-tiktok/creating-videos/video-upload-requirements> | Public upload guidance. |
| Instagram | <https://help.instagram.com/1038071743007909> | Reels aspect ratio range 1.91:1 to 9:16, minimum 30 fps, minimum 720 px. |
| Instagram | <https://about.instagram.com/features/reels> | Reels can be up to 3 minutes; longer Reels are not recommended to new audiences. |
| Meta (secondary) | Facebook Reels specifications: <https://www.facebook.com/business/help/1197310377458196> | H.264/H.265 recommendation, 24–60 fps, 4:2:0, 1080p recommendation. Used only as labelled heuristic context for Instagram because Meta does not publish a complete public Reels ingest specification. |
| YouTube | <https://support.google.com/youtube/answer/1722171> | MP4, H.264, AAC-LC/Opus, 48 kHz, recommended bitrates, BT.709 SDR, no required bitrate limit. |
| YouTube | <https://support.google.com/youtube/answer/15424877> | Shorts up to 3 minutes, square or vertical. |
| YouTube | <https://support.google.com/youtube/answer/12779649> | Shorts upload through YouTube Studio; maximum 1080p upload. |

Secondary references are labelled **heuristic** in code and UI. They are not
presented as private Meta or TikTok ingest rules.

## Scoring model

Each report contains a stable check id, severity, status, measured value, short
explanation, and recommendation. The score starts at 100 and subtracts:

| Condition | Penalty |
| --- | --- |
| Blocker error (hard incompatibility) | −40 |
| Warning | −12 |
| Recommendation only | −3 |
| Critical field unknown | no direct penalty, score capped at 70 |
| Optional field unknown (for example color tags) | no direct penalty, score capped at 95 |

Status thresholds:

| Status | Rule |
| --- | --- |
| **Issues** | Any blocker error, or score ≤ 49. Blocker score is capped at 40. |
| **Review** | Any warning, a critical unknown, or score < 85. |
| **Ready** | No warnings or blockers, no critical unknowns, and score ≥ 85. |

Unknown probe fields never award a full 100% score. A missing critical field
(for example bitrate or geometry) caps the score at 70 and forces **Review**;
missing optional color metadata caps the score at 95 but can remain **Ready**.
Untagged HDR is reported as unknown rather than silently treated as SDR.

The score is a local heuristic. It is not an official platform score and does not
predict whether the platform will avoid recompression.

## Checks implemented

- Container: MP4/MOV, with MP4 recommended where documented.
- Video codec: documented support list per profile; H.264 preferred.
- Frame geometry: dimension limits, aspect-ratio range, vertical recommendation.
- Frame rate: documented ranges, preferred minimums, variable-frame-rate warning.
- Duration: documented Shorts/Reels/TikTok windows.
- File size: TikTok 4 GB documented limit.
- Audio: AAC-LC, 48 kHz, mono/stereo recommendation; non-AAC warning.
- Bitrate: per-profile heuristic threshold; no TikTok cap applied to YouTube.
- Color/HDR: HDR/BT.2020 warning; color metadata is never stripped or converted.

## Intentionally not implemented

- No `ftyp`/`moov` brand mutation, sample-table rewrite, timestamp change, edit-list
  change, or other unverified atom-level platform transformation.
- No automatic remux, re-encode, bitrate cap, or color conversion from selecting a
  profile. Existing pre-flight toggles remain explicit and opt-in.
- No claim of "Guaranteed TikTok Ready" or "No Compression Guaranteed".
- No runtime network calls. Profiles are deterministic local data.

## Limitations

- Platform rules change; re-review the sources before changing thresholds.
- Instagram's complete ingest specification is not publicly documented. Codec,
  bitrate, resolution, and audio values are labelled heuristic, not official.
- Direct container probing does not expose color tags, sample rate, or channel
  count. Those checks show unknown until ffprobe data is available.
- HDR/BT.2020 files are left intact. The app does not convert HDR to SDR as part of
  readiness scoring or profile selection.
- The TikTok preset label is retained for continuity. It prepares and checks the
  file; it cannot guarantee zero platform recompression.

## Performance, privacy, compatibility

- Scoring reuses the existing `VideoInfo`; it does not run `ffprobe` again.
- All scoring is local and offline.
- Media files are read-only during scoring; source files are never overwritten.
- Badge rendering happens on the Tk main thread using already-probed data. The
  queue card signature includes the selected profile, so changing the profile
  refreshes every visible row without re-probing.
