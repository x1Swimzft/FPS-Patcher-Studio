# FPS Patcher Studio — UI redesign brief

Hand this folder to Claude. It contains every screen of the app in its current
state (`images/*.png`) plus the facts a redesign has to respect (this file).

Captured from `main` @ v0.9.0 on 2026-10-25, Windows, 100 % scale, empty queue,
`Solid` backdrop (no acrylic blur), Inter loaded.

## 1. What is in this folder

| File | Screen |
| --- | --- |
| `01-dark-main.png` / `01-dark-settings.png` | Default look: Obsidian preset, dark |
| `02-light-main.png` / `02-light-settings.png` | Light preset, light appearance |
| `03-midnight-violet-*.png` | Preset Midnight Violet |
| `04-emerald-*.png` | Preset Emerald Terminal |
| `05-crimson-*.png` | Preset Crimson Gamer |
| `06-graphite-*.png` | Preset Graphite |
| `07-amber-*.png` | Preset Amber Warm |

Missing (needs a real video file or interaction): queue with items, patch in
progress, cancel/overwrite dialogs, Forensic window, the other six Settings
tabs, Thai language. If the new look must cover those too, capture them from a
running build before locking the design.

## 2. The app, in one paragraph

Python 3.11 desktop tool (customtkinter 6.0.0 + tkinterdnd2, Pillow, ffmpeg
bundled). Users drop MP4/MOV files, pick a target FPS and a patch strategy, and
get a re-timed copy. Windows-first, macOS supported. English + Thai UI. It has
to look like a professional utility, not a game launcher, while still reading as
"for gamers who record at 120 fps".

## 3. Screen map

```
+--------------------------------------------------------------+
| toolbar 52px: version badge · FFmpeg pill · Forensic · Output · theme · settings |
+---------------------------------------+----------------------+
| File queue (weight 1)                 | Inspector 340px      |
|  top bar 36: +Add Files / Add Folder  |  scroll body:        |
|  select-all / clear-selection / clear |   Target FPS (seg)   |
|  drop card                            |   Timescale + Preset |
|  rows                                 |   Platform profile   |
|  footer: preview player, n selected,  |   readiness note     |
|           Apply Selected              |   progress rails     |
|                                       |  pinned footer:      |
|                                       |   Start Patch / Cancel|
+---------------------------------------+----------------------+
| Activity console: collapsed 40 / expanded 210                |
+--------------------------------------------------------------+
```

Settings: separate modal, 740×580 (min 700×520), left tab rail + scroll body +
Reset / Apply / OK / Cancel footer.

## 4. Current design tokens (the real numbers)

`src/fps_patcher/ui/theme.py` is the single source of truth.

**Colours** — every token is a `(light, dark)` tuple, resolved by CTk:
`bg, surface, surface_raised, surface_hover, surface_drop_hover, border,
border_hover, border_focus, text, text2, muted, accent, accent_hover,
accent_pressed, accent_light, accent_glow, success, warn, danger, console_bg,
console_border, toolbar_bg, inspector_bg`.
Semantic sets exist too: `STATUS_SUCCESS/WARNING/DANGER/EXPERIMENTAL/MUTED_*`
(bg / text / border), `CONSOLE_LEVEL_COLORS`.

**Radius** — 16 card, 10 control, 999 pill. Style switch: Sharp 4/4, Round 22/14.

**Type** (Inter, bundled) — big stat 22 · title 14 · section 13 · body 13 ·
caption 12 · badge 11 · mono 12. `font_size` S/M/L shifts every size by −1/+2.

**Spacing** — `PAD_OUTER=16`, `PAD_INNER=12`, `PAD_SPACING=8` are declared but
**not used anywhere**; real padding is hardcoded per widget (6, 8, 10, 12).
This is the main reason the layout cannot be made denser with one switch.

**Fixed sizes** — window 1120×760, min 920×640 · toolbar 52 · inspector 340 ·
console 40/210 · toolbar buttons 28 high, icon buttons 30×28 · segmented 34 ·
entry/combo 32 · primary CTA 40 · secondary 32 · settings modal 740×580.

## 5. Where it reads loose (measured, not taste)

- Header is 52 px for 28 px controls; 24 px of dead vertical space.
- Inspector column is 340 px but the readiness paragraph wraps to four lines;
  that text is the tallest block in the panel.
- 32 px inputs + 10 px gutters make the inspector scroll on a 760 px window.
- Two progress rails ("File Progress", "Batch progress") eat ~90 px even when
  the queue is empty and both are 0 %.
- Drop zone keeps a large empty card when the queue is empty and disappears
  into a single row when it is not — two very different densities.
- Console is always present at 40 px collapsed; its header row (title, line
  count, FFmpeg logs switch, Copy, Clear, Save Log, …) is busier than the app's
  own toolbar.
- Toolbar has two icon-only buttons (theme, settings) with no tooltip label and
  six other controls; on 920 px width it is the first thing to collide.

## 6. Target: compact, not cramped

Keep the identity (dark neutral canvas, one accent, pill status chips, mono
console). Tighten the grid:

| Item | Now | Target |
| --- | --- | --- |
| Window | 1120×760 / min 920×640 | 1040×700 / min 880×600 |
| Toolbar | 52 | 44 |
| Inspector | 340 | 300 |
| Console | 40 / 210 | 36 / 180 |
| Toolbar button | 28 high | 26 |
| Icon button | 30×28 | 26×26 |
| Segmented | 34 | 30 |
| Entry / combo | 32 | 28 |
| Primary CTA | 40 | 36 |
| Secondary button | 32 | 28 |
| Card radius | 16 | 12 |
| Control radius | 10 | 8 |
| Padding | 6 / 8 / 10 / 12 | 4 / 6 / 8 |
| Body / caption type | 13 / 12 | 13 / 12 (do not shrink) |

Hard floors — do not go below these:

- Clickable targets ≥ 26×26 px, primary CTA ≥ 32 px high.
- Body text 13 px, console mono ≥ 11 px, contrast ≥ 4.5:1.
- Thai strings need the extra line height; test both languages at 100 % and
  125 % Windows scaling.
- Keyboard focus ring stays 2 px and visible in every preset.
- The right inspector must stay readable at 300 px: shorten copy, don't clip.

Two levers worth considering instead of shaving pixels everywhere:

1. Wire the three `PAD_*` constants into a `density` setting (Compact /
   Comfortable) and route widget padding through it — one switch, no per-widget
   guesswork.
2. Collapse the two progress rails into one rail with a "file 2/5" caption, and
   move the readiness paragraph behind an ⓘ popover.

## 7. Constraints — Claude must not break these

- **Stack**: Python 3.11, customtkinter 6.0.0, tkinterdnd2, Pillow. No CSS, no
  web view, no new dependency. CTk supports rectangles, radii, flat colour and
  PNG icons — no blur, shadows or gradients without drawing them yourself.
- **Colours are tuples**: `(light, dark)`, 6-digit hex, 100 % opaque. The DWM
  caption colour is derived from `toolbar_bg`.
- **Presets**: `config.THEME_PRESETS` and `PRESETS` share seven names. Renaming
  or dropping one needs a settings migration.
- **Tests that pin the look** (update them only if the redesign is intentional,
  never delete them):
  - `tests/test_theme_typography.py` — exact HIG text/border/success/warn/danger
    values, font sizes 13/12/11 and S/L scaling, preset opacity.
  - `tests/test_ui_icons_and_layout.py` — every icon must exist in light **and**
    dark at 32×32 RGBA, "Start Patch" without emoji, console line-count strings.
  - `tests/test_motion_and_segmented.py`, `tests/test_settings_v2.py` — animation
    and settings behaviour.
- **Copy**: all user-facing text goes through `ui/strings.py` (`en` + `th`).
- **Behaviour is frozen**: patching, queue, ffmpeg handling, persistence,
  keyboard shortcuts, drag-and-drop, Explorer integration must keep working.

## 8. Prompt to paste into Claude

> You are redesigning the desktop UI of FPS Patcher Studio (Python 3.11 +
> customtkinter 6.0.0, Windows-first). Read `images/DESIGN.md` and the
> screenshots in `images/` first, then `src/fps_patcher/ui/theme.py`,
> `main_window.py`, `control_panel.py`, `input_list.py`, `log_console.py`,
> `settings_window.py`.
>
> Goal: a tighter, more intentional "pro tool" look — calmer surfaces, one
> accent, denser spacing per the target table in section 6 — without touching
> behaviour or adding dependencies.
>
> Ground rules: keep the `(light, dark)` token model and all seven presets;
> keep every string in `strings.py` (en + th); keep icons 32×32 RGBA per mode;
> keep the hard floors in section 6; update the listed tests only where the
> change is deliberate.
>
> Deliver, in this order: (1) the new token/spacing values in `theme.py`,
> (2) the layout edits, (3) a short note on every test you changed and why.
> Do not refactor unrelated code.

## 9. How these screenshots were made

The app was launched from source with an isolated `APPDATA` (temp folder) so no
real settings, queue or registry keys were touched, then each window handle was
rendered with `PrintWindow` at 1120×760 (main) and 740×580 (settings). To
refresh them after the redesign, repeat with the new theme and the same window
sizes so before/after stay comparable.
