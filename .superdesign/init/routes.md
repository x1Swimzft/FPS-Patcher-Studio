# Screens — FPS Patcher Studio (Qt)

Desktop app: one window + modal dialogs. No URL routing.

| Screen | File | Size | Summary |
|---|---|---|---|
| Main window | `src/fps_patcher/ui_qt/main_window.py` | 1040x700 (min 880x600) | Toolbar (version badge, FFmpeg pill, Forensic, Output, theme toggle, settings), queue + inspector split, collapsible activity console |
| Settings | `src/fps_patcher/ui_qt/settings_dialog.py` | 920x640 (min 820x560) | Modal: left rail + scroll page per tab — General, Output, Appearance, System; Reset / Apply / OK / Cancel footer; live theme preview |
| Forensic | `src/fps_patcher/ui_qt/forensic_dialog.py` | modal | Analyzer/comparison with background worker signals |
| History | `src/fps_patcher/ui_qt/history_dialog.py` | modal | Past runs |
| Update | `src/fps_patcher/ui_qt/update_dialog.py` | modal | Release notes, install type, download progress |

## States that change the look
- Queue: empty (drop card) / populated rows / patching (per-row progress); readiness badge per row.
- Console: collapsed 32px / expanded 180px; level colors, filters, search.
- Inspector: idle / busy (progress + cancel); per-item override card; VFR banner.
- Appearance: 7 presets (Obsidian default, Crimson Gamer, Midnight Violet, Emerald Terminal, Graphite, Amber Warm, Light) x light/dark; languages en/th; density Compact/Comfortable; radius Sharp/Normal/Round; UI scale 100/125.
