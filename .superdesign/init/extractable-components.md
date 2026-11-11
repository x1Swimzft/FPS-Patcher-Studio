# Extractable Components — FPS Patcher Studio (Qt)

Qt widgets, not web components — component extraction is optional and only worth it for multi-screen consistency.

## Toolbar
- Source: `src/fps_patcher/ui_qt/main_window.py` lines 207-301 (_build_toolbar)
- Category: layout
- Description: 48px top bar — brand/version badge, FFmpeg status pill, Forensic, Output, theme toggle, settings
- Extractable props: versionText (string), ffmpegState ("ready"|"missing"|"downloading"), isDark (boolean)
- Hardcoded: icon set, labels, QSS roles

## SettingsRail
- Source: `src/fps_patcher/ui_qt/settings_dialog.py` lines 263-325 (_build_rail + footer)
- Category: layout
- Description: left tab rail (General, Output, Appearance, System) + Reset/Apply/OK/Cancel footer
- Extractable props: activeTab (string, default "general")

## Inspector
- Source: `src/fps_patcher/ui_qt/inspector.py` lines 146-454
- Category: layout
- Description: Target FPS segmented, timescale + preset, platform profile, readiness card, progress rail, Start Patch / Cancel footer

## QueueView / DropCard
- Source: `src/fps_patcher/ui_qt/queue_view.py` (QueueView 1032-1897, DropCard 157-510)
- Category: layout

## Card / Switch / SegmentedControl
- Source: `src/fps_patcher/ui_qt/widgets.py`
- Category: basic — keep inline in drafts, do not extract
