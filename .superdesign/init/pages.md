# Pages — FPS Patcher Studio (Qt)

## Main window
Entry: `src/fps_patcher/ui_qt/main_window.py` (MainWindow : QMainWindow)
Dependencies (UI-touching):
- `src/fps_patcher/ui_qt/console.py` (ConsolePanel)
- `src/fps_patcher/ui_qt/inspector.py` (Inspector)
- `src/fps_patcher/ui_qt/queue_view.py` (QueueView, QueueModel, QueueDelegate, DropCard)
- `src/fps_patcher/ui_qt/qss.py` (build_qss/apply_theme — QSS + palette from Theme)
- `src/fps_patcher/ui_qt/theme.py` (tokens, presets, metrics, fonts, DWM helpers)
- `src/fps_patcher/ui_qt/widgets.py` (Card, CardGroup, Switch, SegmentedControl, buttons)
- `src/fps_patcher/ui_qt/icons.py`, `motion.py`, `thumbnails.py`, `bridge.py`
- `src/fps_patcher/ui_qt/settings_dialog.py` / `forensic_dialog.py` / `history_dialog.py` / `update_dialog.py` (modals opened from the toolbar)
- `src/fps_patcher/ui/strings.py` (en/th copy), `src/fps_patcher/config.py` (settings, presets)
- `src/fps_patcher/app/*`, `core/*` (logic — strip for design context)

## Settings dialog
Entry: `src/fps_patcher/ui_qt/settings_dialog.py`
- `theme.py`, `widgets.py`, `config.py`, `ui/strings.py`; pages: _build_general, _build_output, _build_appearance, _build_system.

## Context-budget notes
- theme.py 511 lines: pass full.
- widgets.py 742 lines: pass full when the target uses shared primitives.
- main_window.py 1367: pass the shell/toolbar range (95-302) only.
- inspector.py 1435: build range 146-454. queue_view.py 1897: build range 1306-1416. console.py 555: build range 105-179.
- settings_dialog.py 1710: pass per-tab builder ranges (_build_appearance 670-866, _build_output 867-955, _build_general 956-1186, _build_system 1187-end) or full when Settings is the target.
- Current Qt screenshots: `images/after-qt/<preset>-<mode>-<lang>-<scale>-{main,settings}.png`.
