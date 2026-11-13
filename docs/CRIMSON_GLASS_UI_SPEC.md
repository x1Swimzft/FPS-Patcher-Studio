# Crimson Glass — Qt UI Implementation Spec

Status: direction approved on the canvas (design drafts reviewed). Implementation not started.
Surface: FPS Patcher Studio desktop UI — Python 3.11 + PySide6 6.12.
Scope: visual re-skin of the existing Qt UI. Behaviour, copy, information architecture and dependencies stay unchanged.

## 0. Executor brief (paste this to the implementing agent)

> You are implementing the **Crimson Glass** visual direction in FPS Patcher Studio (`E:\Project\fps-patcher-studio`, Python 3.11 + PySide6 6.12). Read this spec and the referenced files first. Change design tokens, QSS, the shell glow and icon tinting exactly as specified. Keep behaviour, strings, layout, preset names and dependencies unchanged. Update only the tests this spec lists. Verify with `uv run pytest`, `uv run ruff check .`, `uv run mypy` and `uv run python tools/capture_qt_screens.py --scale 1.0`. Do not copy the HTML drafts into Qt; they are visual references only.

## 1. References

- Design system (authoritative): `.superdesign/design-system.md`
- Main window draft: https://p.superdesign.dev/draft/96bef631-d73f-49e5-b180-6df311539fae (v4)
- Settings draft: https://p.superdesign.dev/draft/aace7489-8f34-438d-8229-520e4a39a91b (v4, Appearance tab)
- Canvas: https://superdesign.dev/teams/38a53270-5a68-4c8c-b294-0ae288b60530/projects/76e26c44-b3e3-40a7-bd30-f9e63cd96a19
- Current Qt screenshots: `images/after-qt/`
- Structure source of truth: `src/fps_patcher/ui_qt/` (legacy `src/fps_patcher/ui/` customtkinter code is not shipped — do not target it).

## 2. Goal

Dark-first, near-black UI with one crimson accent and a single soft top-left glow. Controls are translucent (`rgba`), never solid near-black boxes. Primary CTAs stay solid accent. Light theme and all seven presets remain. No layout or behaviour changes.

## 3. Non-goals

- No new dependencies. No HTML/CSS import. No web view.
- No changes to `core/`, `app/`, queue/patching/FFmpeg/updater behaviour, shortcuts, drag-and-drop or persistence.
- No copy rewrites; labels and `ui/strings.py` stay as they are.
- No preset renames. `DEFAULT_THEME_PRESET` stays `"Crimson Gamer"`.
- Do not delete or weaken tests; only update the pinned values listed in §9.

## 4. Token changes — `src/fps_patcher/ui_qt/theme.py`

### 4.1 Shared neutrals — `(light, dark)` pairs used by every preset

| token | light | dark |
|---|---|---|
| bg | #F5F1F2 | #0A0A0F |
| surface | #FFFFFF | #111118 |
| surface_raised | #F7F2F3 | #191923 |
| surface_hover | #EEE6E8 | #23262B |
| border | #E3D8DB | #242432 |
| border_hover | #C9BFC2 | #3A3A46 |
| border_control | #E3D8DB | #242432 |
| text | #1C1417 | #ECEBF2 |
| text2 | #463A3E | #C9C8D6 |
| muted | #6D5D62 | #9A99AB |
| success | #15803D | #4ADE80 |
| warn | #8A5A14 | #D6A45F |
| danger | #B91C1C | #FF8A99 |
| console_bg | #EFE9EA | #0A0A0F |
| console_border | #E3D8DB | #242432 |
| toolbar_bg | = bg | = bg |
| inspector_bg | #FAF7F8 | #111118 |

`surface_drop_hover` stays derived (mix of accent with bg at 12%). `_LIGHT_BG = "#F5F1F2"`, `_DARK_BG = "#0A0A0F"`.

### 4.2 Default preset — Crimson Gamer explicit accent family

Extend `_preset()` with optional explicit fields so the default preset can carry designed (not derived) tints:

```python
def _preset(
    name: str,
    *,
    accent: tuple[str, str],
    accent_hover: tuple[str, str],
    accent_pressed: tuple[str, str],
    accent_light: tuple[str, str] | None = None,
    accent_dim: tuple[str, str] | None = None,
    accent_dim_border: tuple[str, str] | None = None,
) -> ThemeTokens:
    return ThemeTokens(
        name=name,
        # …unchanged fields…
        accent_light=accent_light
        or (_mix(accent[0], "#111111", 0.55), _mix(accent[1], "#FFFFFF", 0.55)),
        accent_glow=(_mix(accent[0], _LIGHT_BG, 0.35),
                     _mix(accent[1], _DARK_BG, 0.35)),
        accent_dim=accent_dim or ("", ""),
        accent_dim_border=accent_dim_border or ("", ""),
        # …unchanged fields…
    )
```

Crimson Gamer call:

```python
"Crimson Gamer": _preset(
    "Crimson Gamer",
    accent=("#C8283F", "#C8283F"),
    accent_hover=("#A81F33", "#D93450"),
    accent_pressed=("#8F1A2B", "#B32337"),
    accent_light=("#A81F33", "#FF5A70"),
    accent_dim=("#FBE9EC", "#2A1119"),
    accent_dim_border=("#E7B3BD", "#6B1F30"),
),
```

All other presets keep their current accent triples. Their neutrals change automatically through §4.1.

### 4.3 Custom accent

In `make_theme()`, when a custom accent is set, also reset `accent_light` and derive a legible bright text tone:

```python
if accent:
    light_text = _mix(accent, "#111111", 0.60)
    dark_text = _mix(accent, "#FFFFFF", 0.60)
    tokens = replace(
        tokens,
        accent=(accent, accent),
        accent_hover=(accent, accent),
        accent_pressed=(accent, accent),
        accent_light=(light_text, dark_text),
        accent_dim=("", ""),
        accent_dim_border=("", ""),
        on_accent=("", ""),
    )
```

### 4.4 Radii

```python
CORNER_RADII = {
    "Sharp": Radii(card=4, control=4),
    "Normal": Radii(card=14, control=10),
    "Round": Radii(card=18, control=12),
}
```

Default `radius_style` stays `Normal`. `RADIUS_PILL = 4` stays (technical chips only).

### 4.5 Unchanged

Metrics (window 1040×700, min 880×600, toolbar 48, inspector 300, console 32/180), density metrics, font scales (M = 13/12/11/12), font families, DWM helpers.

## 5. QSS changes — `src/fps_patcher/ui_qt/qss.py`

Add a helper and mode-aware glass constants inside `build_qss()`:

```python
def _rgba(color: str, alpha: float) -> str:
    q = QColor(color)
    return f"rgba({q.red()}, {q.green()}, {q.blue()}, {alpha:g})"

glass_fill = "rgba(255,255,255,0.04)" if theme.is_dark else "rgba(0,0,0,0.03)"
glass_border = "rgba(255,255,255,0.12)" if theme.is_dark else "rgba(0,0,0,0.10)"
glass_hover = "rgba(255,255,255,0.08)" if theme.is_dark else "rgba(0,0,0,0.06)"
glass_hover_border = "rgba(255,255,255,0.18)" if theme.is_dark else "rgba(0,0,0,0.16)"
accent_glass = _rgba(theme.color("accent"), 0.16)
accent_glass_border = _rgba(theme.color("accent"), 0.45)
```

(Import `QColor` is already imported in this module.)

Apply:

1. `QPushButton` base — replace `background: transparent` + `border: 1px solid {border_control}` with `background: {glass_fill}` + `border: 1px solid {glass_border}`. Hover → `{glass_hover}` / `{glass_hover_border}`; pressed → `{glass_hover}`.
2. `QPushButton[variant="secondary"]` — same glass fill/border and hover.
3. Keep `variant="ghost"` and `variant="icon"` transparent (text/icon actions).
4. Keep `variant="primary"` solid `accent` (do not make it translucent).
5. `QPushButton#SettingsFooterButton` — glass fill/border; hover glass. `QPushButton#SettingsPrimaryButton` stays solid accent.
6. `QPushButton#SettingsNavPill[active="true"]`:

```css
background: {accent_glass};
border: 1px solid {accent_glass_border};
color: {c("accent_light")};
```

Remove the old 2px `border-left`. Hover stays `surface_hover`.
7. `QLabel[role="badge"]` — text color `{c("accent_light")}` (keep accent_dim background and accent_dim_border ring).
8. `QProgressBar::chunk`:

```css
background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 {c("accent")}, stop:1 {c("accent_light")});
```

Keep the done/success state where the widget sets it.
9. `QLineEdit`, `QComboBox`, `QSpinBox` — replace `border_control` outlines with `{glass_border}`; keep the 2px accent focus ring (`border_focus`) that the tests assert.
10. `QFrame#PresetSwatchCard[selected="true"]` — keep `accent_dim` background + 2px accent border.
11. Delete the duplicated rules in `inspector.py::_local_qss` (label roles, input base, focus/min-height, `QAbstractItemView`, every `QPushButton` rule and both progress rules). The widget-level stylesheet wins over the app QSS, so leaving them keeps the old opaque outlines in the inspector. Keep only inspector-specific rules: footer, transparent scroll body, read-only input, combo drop-down, `WarnCallout`, plus font-size-only typography rules required by `tests/test_ui_qt_typography.py` (no colors/borders/backgrounds).

## 6. Shell glow — `src/fps_patcher/ui_qt/main_window.py`

1. Remove the 3px `BrandBar` from `_build_toolbar()` (lines ~218–224) and its style update in `_on_theme_changed()` (~line 389). No tests reference it.
2. Add a glow-painting root widget:

```python
class _GlowRoot(QWidget):
    def __init__(self, accent: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._accent = QColor(accent)
        self.setObjectName("Root")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def set_accent(self, accent: str) -> None:
        self._accent = QColor(accent)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = QColor(self._accent)
        colour.setAlpha(51)  # 0.20
        gradient = QRadialGradient(
            QPointF(self.width() * 0.02, -self.height() * 0.08), 720
        )
        gradient.setColorAt(0.0, colour)
        gradient.setColorAt(0.65, QColor(0, 0, 0, 0))
        painter.fillRect(self.rect(), gradient)
```

3. In `_build_shell()`: `root = _GlowRoot(self.theme.color("accent"))`; store it (`self._root = root`).
4. In `_on_theme_changed()`: `self._root.set_accent(theme.color("accent"))`.
5. Imports needed: `QColor`, `QPainter`, `QPointF`, `QRadialGradient`.

## 7. Icon tinting — `src/fps_patcher/ui_qt/icons.py`

Extend the existing loader without touching the 32×32 RGBA assets. Cache key is `(name, dark, tint or "")` so a tinted icon can never be returned to a later untinted caller:

```python
def get_icon(name: str, is_dark: bool, tint: str | None = None) -> QIcon:
    # …existing lookup…
    if tint:
        pixmap = QPixmap(path)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(tint))
        painter.end()
        return QIcon(pixmap)
    # …existing QIcon(path)…
```

Use `tint=theme.color("accent_light")` for the **active** Settings rail icon. Add a small `_sync_nav_icons(theme)` in `settings_dialog.py` that re-applies icons for all nav buttons (active one tinted, others plain) and call it from `_select_tab()` and on theme change.

## 8. Component checks

- `widgets.py` `Switch`, `SegmentedControl`, sliders: verify every colour comes from `theme.color(...)`; replace any hardcoded hex with tokens. On-state = `accent`; off-state = `surface_hover` + `border`.
- `Card` (`QFrame#Card`) is token-driven; no change.
- Queue rows, drop card and console are token-driven; verify empty/populated/patching states after the palette change.
- Settings dialog: no structural change required; the Appearance page already contains Theme Preset, Appearance, Layout density, Custom Accent, Glass (effect/mode/tint/alpha), Reduce motion, UI Scale, Corner style and Font size. Verify all are visible by scrolling at 920×640.
- Toolbar: actions only. The native Windows title bar carries the app icon, title and version; do not duplicate them in the toolbar.

## 9. Tests to update — `tests/test_ui_qt_theme.py` only (intentional changes)

Update `CRIMSON_DARK` to:

```python
CRIMSON_DARK = {
    "bg": "#0A0A0F",
    "surface": "#111118",
    "surface_raised": "#191923",
    "surface_hover": "#23262B",
    "border": "#242432",
    "text": "#ECEBF2",
    "text2": "#C9C8D6",
    "muted": "#9A99AB",
    "accent": "#C8283F",
    "accent_hover": "#D93450",
    "accent_light": "#FF5A70",
    "accent_glow": "#4C1420",
    "accent_pressed": "#B32337",
    "accent_dim": "#2A1119",
    "accent_dim_border": "#6B1F30",
    "toolbar_bg": "#0A0A0F",
    "inspector_bg": "#111118",
    "console_bg": "#0A0A0F",
}
```

- `test_crimson_dark_profile_is_exact`: the light accent assertion becomes `"#C8283F"`.
- `test_density_corner_and_font_scale_values` **and** `test_make_theme_resolves_mode_density_metrics_and_preset` (~line 122): Normal becomes `(14, 10)`, Round `(18, 12)`; Sharp and all density/font values unchanged.
- If `accent_glow` rounding differs on the implementing machine, take the value produced by `_mix` and update the pinned value; do not weaken the test.
- No other test files should need changes. If one fails for a real reason, report it instead of silently editing.

## 10. Verification

```bash
uv run pytest
uv run ruff check .
uv run mypy
uv run python tools/capture_qt_screens.py --scale 1.0
```

Manual checklist (Windows, real build):
- App launches; toolbar, queue, inspector and console render correctly.
- Primary buttons (Start Patch, OK) are solid crimson; secondary buttons (Add Files, Add Folder, Cancel, Apply) are translucent — no solid near-black boxes.
- Active nav/feature pills use a translucent crimson fill, 1px crimson-ish border and `#ff5a70` text; active Settings icon is tinted.
- Progress bars show the crimson→light-crimson gradient.
- One soft glow is visible at the top-left; it follows the active accent (presets and custom accent).
- All seven presets and light/dark modes render without contrast or clipping regressions; English and Thai at 100% and 125%.
- Glass effect / Backdrop material / Tint strength / Window alpha still work through DWM.
- Focus rings remain 2px and visible; reduced-motion and window alpha settings still work.

## 11. Acceptance criteria

- Token values in `theme.py` match §4 exactly; `PRESETS` still has all seven names; `DEFAULT_THEME_PRESET` unchanged.
- QSS matches §5; no QSS rule renders a solid `#191923`-style fill for secondary buttons.
- Glow is painted by the shell, not an image asset; no new dependency.
- Tests pass (with the §9 updates); ruff and mypy clean.
- Screenshot capture completes; the dark default matches the reference drafts in palette, radii, translucency and the glow.
- `ui/strings.py`, `core/` and `app/` untouched; no behaviour changes.

## 12. Risks and notes

- **DWM glass**: real blur/transparency comes from the Windows backdrop (existing glass mode/tint/alpha). QSS `rgba` surfaces sit on top; verify on Windows 10 and 11. Do not attempt CSS-style backdrop blur.
- **QSS rgba** is supported by Qt 6 style sheets (`rgba(r, g, b, a)`), including `qlineargradient` stops; keep the generated string deterministic.
- **Custom accent**: active nav text uses a computed light accent (§4.3); check contrast for very dark custom accents.
- **Icons** are PNGs; the active-rail tint is a pixmap recolor, not a new asset. Keep the dual-mode 32×32 files.
- **Do not copy draft HTML**: the drafts use Tailwind and browser-only effects; the app is Qt/QSS only.

## 13. Out of scope

Multi-window IA changes, new settings, copy rewrites, preset renames or additions, behaviour changes, baseline pixel reproduction, and any change to packaging or update logic.

## 14. Implementation corrections (applied during the build)

These four corrections were found after the first handoff and are already applied in the code; keep them if this spec is reused.

1. **`accent_light` is the readable accent tone, not a background tint.** The old derivation (`_mix(accent, bg, 0.18)`) produced a near-surface tone; used as active-nav/badge text and the progress gradient end it was unreadable for the six non-Crimson presets (Graphite dark ≈ 1.2:1). Derive it toward near-black in light mode and toward white in dark mode (0.55). Crimson Gamer carries explicit values (`#A81F33` / `#FF5A70`).
2. **The icon cache key includes the tint** — `(name, dark, tint or "")` — so a tinted icon cannot be returned to a later untinted caller.
3. **`inspector.py::_local_qss` no longer duplicates app-QSS rules** (see §5 item 11). Exception: font-size-only rules for inspector labels and buttons remain because `tests/test_ui_qt_typography.py` reads the widget stylesheet directly; they set no colors, borders or backgrounds.
4. **Both radius assertions were updated**, not only the density/corner test: `test_make_theme_resolves_mode_density_metrics_and_preset` also pinned Normal at `(8, 6)`.

## 15. Fidelity pass against the approved drafts (applied)

The first build matched the tokens but not the approved canvas layout. These changes close that gap; where this section conflicts with §5, this section wins.

- **Queue area**: the whole queue area is one `#111118` panel with a 1px dashed border and radius 14. The empty state sits centered inside it (32px muted icon, 15/500 title, 12px caption, accent-glass Add Files, glass Add Folder, capsule MP4/MOV/M4V chips). The Active Patch Profile row is a sibling below the panel, not a card footer.
- **Inspector**: one surface card with a 1px border and radius 14, inset by the shell margin. Group cards are flat; captions are 12/600 muted sentence case; rows are 40px; the readiness hint is a raised rounded box; the disabled Start Patch is neutral glass (solid accent only when enabled).
- **Shell**: toolbar and queue gutters are transparent so the single radial glow (accent at 0.15) shows through; app icon 24px, title 13/600, neutral version badge and neutral FFmpeg status pill. Default density is Comfortable (6/10/12); Compact remains a user choice.
- **Settings**: the rail is a surface card; the active nav label is `#ecebf2` with an accent-light icon. The Appearance page is two independent columns: Theme Preset (40px background/accent preview cards, draft order) + UI Scale on the left; Appearance/Layout density rows + Custom Accent + Glass rows on the right. No Appearance "Advanced" collapsible.
- **Segmented control**: raised track, `surface_hover` active thumb, active label `#ecebf2` 600, inactive `text2` 500 (no accent-colored active label).

- **QSlider**: styled in app QSS (4px track, accent→accent-light fill, 14px white knob). Without it Windows draws the native green accent on a real machine even when offscreen captures look crimson.
