# Design System — FPS Patcher Studio (desktop UI, Qt)

Supersedes the previous Settings-page direction (product facts kept). Applied from the Universal Downloader reference: this is the "Crimson Glass" direction.

## Product
FPS Patcher Studio is a Windows desktop tool (Python 3.11 + PySide6 6.12) that patches MP4/MOV container timing. The default preset "X1T 1080p" (Zilem) copies the H.264 video and AAC audio unchanged — lossless, no re-encode. "X1T 720p" copies video and re-encodes audio only. Users are creators preparing files for TikTok / Instagram Reels / YouTube Shorts; they care about quality preservation, batch throughput, and knowing exactly when a setting causes a re-encode. No telemetry, no media uploads.
Screens: Main window (1040x700) = toolbar + queue + 300px inspector + collapsible activity console; Settings modal 920x640 (tabs: General, Output, Appearance, System); Forensic / History / Update dialogs. English + Thai.

## Visual direction — Crimson Glass
Dark-first, near-black canvas with one crimson accent. Quiet flat surfaces, hairline borders, precise row rhythm, pill chips for technical tags, one soft top-left crimson glow as the single expressive element. The app keeps its own structure (toolbar / queue / inspector / console) — the reference's sidebar layout is NOT part of this direction.

### Colour — dark (default)
bg `#0a0a0f` · surface `#111118` · raised `#191923` · hover `#23262b` · border `#242432` (control outlines use the same border)
text `#ecebf2` · text2 `#c9c8d6` · muted `#9a99ab`
accent `#c8283f` · accent-hover `#d93450` · accent-light `#ff5a70` · accent-dim `#2a1119` · accent-dim-border `#6b1f30`
success `#4ade80` · warn `#d6a45f` · danger `#ff8a99`
inspector `#111118` · console `#0a0a0f` (border `#242432`) · toolbar = bg
glow (single, painted behind shell content): radial-gradient(720px 460px at 2% -8%, rgba(200,40,63,0.2), transparent 65%)

### Colour — light
bg `#f5f1f2` · surface `#ffffff` · raised `#f7f2f3` · hover `#eee6e8` · border `#e3d8db`
text `#1c1417` · text2 `#463a3e` · muted `#6d5d62`
accent `#c8283f` · accent-hover `#a81f33` · accent-light `#a81f33` · accent-dim `#fbe9ec` · accent-dim-border `#e7b3bd`
success `#15803d` · warn `#8a5a14` · danger `#b91c1c`

### Presets
Keep all seven preset names (Obsidian, Crimson Gamer, Midnight Violet, Emerald Terminal, Graphite, Amber Warm, Light). Neutrals are shared: this neutral change applies to every preset; each preset keeps its own accent. The default **Crimson Gamer** preset takes the crimson accent family above (`#c8283f` / `#d93450` / light `#ff5a70`); Obsidian keeps its warm gold.

### Shape, density, metrics
Radii: card 14 · control 10 · input 10 · chips/pills 999 · progress rails pill.
Window 1040x700 (min 880x600). Toolbar 48. Inspector 300. Console 32 collapsed / 180 expanded. Body 13px (S 12 / L 15), caption 12, badge 11, mono 12 (Cascadia Mono). Button 30, primary 44, segmented 32, entry/combo 30, icon button 28, switch 38x22 with a 16px knob, progress 4.

### Components
- Card: `#111118`, 1px `#242432`, radius 14, no shadow.
- Buttons: secondary `#191923` + 1px border, radius 10; primary = accent fill, white 600 text, radius 10; ghost = transparent + border.
- Chips (technical tags): 26-34px pill, 1px border, raised bg; active = accent-dim bg + accent-dim-border ring + accent-light text.
- Segmented control: track `#191923` + 1px border, radius 10, moving thumb `#23262b`, active label `#ecebf2` 600.
- Switch: 38x22 pill; off `#23262b`; on accent; 16px knob; 140ms.
- Progress: 4px pill rail; fill linear-gradient(90deg, `#c8283f`, `#ff5a70`); done = success.
- Status dot: 6-7px circle + 12px label, success/warn/danger only — never a filled banner for a non-error.
- Drop card: 1px dashed border, radius 14, muted icon + "Drop MP4, MOV, or M4V here".
- Rows: hairline separators, 40-44px rhythm, title 13/500, meta 12 muted.

### Motion
Subtle only: 140ms switch, 140ms dialog fade, progress transition; respect reduce-motion and the app's Reduce effects setting. No page-load animations.

### Qt translation rules (this app is Qt, not web)
- No fake CSS blur in drafts; the app's real glass comes from the Windows DWM backdrop (existing glass switch, glass mode, tint strength and window alpha settings).
- Translucency is allowed and preferred for controls: secondary buttons use `rgba(255,255,255,0.04)` fills with `rgba(255,255,255,0.12)` borders; accent controls use `rgba(200,40,63,0.16)` fills with `rgba(255,90,112,0.45)` borders. Never render a solid near-black box where a translucent control is meant.
- The single top-left glow is painted with QRadialGradient behind the shell content.
- Cards are flat: no drop shadows, no inset highlight; keep the 2px visible focus ring.
- Icons stay the app's dual-mode 32x32 PNG set; the brand mark is the app icon Brand Asset (`brand-app-icon`) — never substitute initials, emoji or invented marks.
- Test English + Thai at 100% and 125% scaling; Thai keeps its extra line height.

### Copy rules (keep)
Sentence case; verbs first ("Save changes", "Start Patch"); name the outcome, not the mechanism ("Convert audio to AAC 48 kHz stereo"); the lossless claim only while it is true; no middle-dot metadata strings, no eyebrow labels, no numbered markers.

### Constraints
- No new dependencies; behaviour (patching, queue, ffmpeg, persistence, shortcuts, drag-and-drop, Explorer integration) is frozen.
- Keep the `(light, dark)` token model and the seven preset names.
- Tests that pin visual values are updated only where the change is deliberate.
