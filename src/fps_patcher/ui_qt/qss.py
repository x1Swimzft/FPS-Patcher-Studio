"""Generate Qt style sheets and palettes from a resolved Theme."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from .theme import (
    MONO_FONT_FAMILIES,
    RADIUS_PILL,
    UI_FONT_FAMILIES,
    Theme,
    load_qt_fonts,
)


def _families(families: tuple[str, ...]) -> str:
    return ", ".join(f'"{name}"' for name in families)


def build_qss(theme: Theme) -> str:
    """Build the application style sheet purely from theme tokens/metrics."""
    c = theme.color
    ui = _families(UI_FONT_FAMILIES)
    mono = _families(MONO_FONT_FAMILIES)

    body = theme.fonts.body
    caption = theme.fonts.caption
    badge = theme.fonts.badge
    mono_size = theme.fonts.mono

    outer = theme.outer
    inner = theme.inner
    spacing = theme.spacing
    card = theme.radii.card
    control = theme.radii.control
    button = theme.button_height
    icon = theme.icon_button_size
    primary = theme.primary_height
    secondary = theme.secondary_height
    entry = theme.entry_height
    combo = theme.combo_height
    indicator = theme.indicator_size
    scrollbar = theme.scrollbar_thickness
    chevron = (
        Path(__file__).resolve().parent.parent
        / "ui"
        / "assets"
        / f"chevron_down_{'dark' if theme.is_dark else 'light'}.png"
    ).as_posix()

    return f"""
* {{
    font-family: {ui};
    font-size: {body}px;
    outline: none;
}}
QMainWindow, QDialog {{
    background: {c("bg")};
    color: {c("text")};
}}
QWidget {{
    color: {c("text")};
    selection-background-color: {c("accent")};
    selection-color: {c("on_accent")};
}}
QWidget#Root {{
    background: {c("bg")};
}}
QWidget#Toolbar {{
    background: {c("toolbar_bg")};
    border-bottom: 1px solid {c("border")};
}}
QWidget#Inspector {{
    background: {c("inspector_bg")};
    border-left: 1px solid {c("border")};
}}
QWidget#Console {{
    background: {c("console_bg")};
    border-top: 1px solid {c("console_border")};
}}
QFrame#Card {{
    background: {c("surface")};
    border: 1px solid {c("border")};
    border-radius: {card}px;
}}
QFrame#Hairline {{
    background: {c("border")};
    border: none;
    min-height: 1px;
    max-height: 1px;
}}
QLabel {{
    background: transparent;
    color: {c("text")};
    font-size: {body}px;
}}
QLabel[role="title"] {{
    color: {c("text")};
    font-size: {body + 2}px;
    font-weight: 600;
}}
QLabel[role="caption"] {{
    color: {c("text2")};
    font-size: {caption}px;
}}
QLabel[role="muted"] {{
    color: {c("muted")};
    font-size: {caption}px;
}}
QLabel[role="badge"] {{
    background: {c("accent_dim")};
    border: 1px solid {c("accent_dim_border")};
    border-radius: {RADIUS_PILL}px;
    color: {c("accent")};
    font-size: {badge}px;
    font-weight: 600;
    padding: 1px {outer}px;
}}
QLabel[role="cardCaption"] {{
    color: {c("text2")};
    font-size: {caption}px;
    font-weight: 600;
}}
QPushButton {{
    background: {c("surface_raised")};
    border: 1px solid {c("border")};
    border-radius: {control}px;
    color: {c("text")};
    font-size: {body}px;
    min-height: {button}px;
    padding: 0 {inner}px;
}}
QPushButton:hover {{
    background: {c("surface_hover")};
    border-color: {c("border_hover")};
}}
QPushButton:pressed {{
    background: {c("surface_drop_hover")};
}}
QPushButton:disabled {{
    background: {c("surface_raised")};
    border-color: {c("border")};
    color: {c("muted")};
}}
QPushButton[variant="primary"] {{
    background: {c("accent")};
    border: 1px solid {c("accent")};
    color: {c("on_accent")};
    font-weight: 600;
    min-height: {primary}px;
}}
QPushButton[variant="primary"]:hover {{
    background: {c("accent_hover")};
    border-color: {c("accent_hover")};
}}
QPushButton[variant="primary"]:pressed {{
    background: {c("accent_pressed")};
    border-color: {c("accent_pressed")};
}}
QPushButton[variant="primary"]:disabled {{
    background: {c("accent_dim")};
    border-color: {c("accent_dim_border")};
    color: {c("muted")};
}}
QPushButton[variant="secondary"] {{
    background: {c("surface")};
    border: 1px solid {c("border")};
    color: {c("text")};
    min-height: {secondary}px;
}}
QPushButton[variant="secondary"]:hover {{
    background: {c("surface_hover")};
    border-color: {c("border_hover")};
}}
QPushButton[variant="secondary"]:pressed {{
    background: {c("surface_raised")};
}}
QPushButton[variant="secondary"]:disabled, QPushButton[variant="ghost"]:disabled,
QPushButton[variant="icon"]:disabled {{
    background: transparent;
    border-color: transparent;
    color: {c("muted")};
}}
QPushButton[variant="ghost"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {c("text2")};
}}
QPushButton[variant="ghost"]:hover {{
    background: {c("surface_hover")};
    color: {c("text")};
}}
QPushButton[variant="ghost"]:pressed {{
    background: {c("surface_raised")};
}}
QPushButton[variant="icon"] {{
    background: transparent;
    border: 1px solid transparent;
    min-height: {icon}px;
    max-height: {icon}px;
    min-width: {icon}px;
    max-width: {icon}px;
    padding: 0;
}}
QPushButton[variant="icon"]:hover {{
    background: {c("surface_hover")};
    border-color: {c("border")};
}}
QPushButton[variant="icon"]:pressed {{
    background: {c("surface_raised")};
}}
QLineEdit, QSpinBox {{
    background: {c("surface")};
    border: 1px solid {c("border")};
    border-radius: {control}px;
    color: {c("text")};
    min-height: {entry}px;
    padding: 0 {inner}px;
}}
QLineEdit:hover, QSpinBox:hover {{
    border-color: {c("border_hover")};
}}
QLineEdit:disabled, QSpinBox:disabled {{
    background: {c("surface_raised")};
    color: {c("muted")};
}}
QComboBox {{
    background: {c("surface")};
    border: 1px solid {c("border")};
    border-radius: {control}px;
    color: {c("text")};
    min-height: {combo}px;
    padding: 0 {inner + 14}px 0 {inner}px;
}}
QComboBox:hover {{
    border-color: {c("border_hover")};
}}
QComboBox:disabled {{
    background: {c("surface_raised")};
    color: {c("muted")};
}}
QComboBox::drop-down {{
    border: none;
    width: {spacing + 8}px;
    margin: 1px;
}}
QComboBox::down-arrow {{
    image: url("{chevron}");
    width: 10px;
    height: 10px;
}}
QComboBox QAbstractItemView {{
    background: {c("surface_raised")};
    border: 1px solid {c("border")};
    color: {c("text")};
    selection-background-color: {c("accent_dim")};
    selection-color: {c("text")};
    padding: {outer}px;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background: transparent;
    border-left: 1px solid {c("border")};
    width: {spacing}px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background: {c("surface_hover")};
}}
QPlainTextEdit#ConsoleLog {{
    background: {c("console_bg")};
    border: 1px solid {c("console_border")};
    border-radius: {control}px;
    color: {c("text")};
    font-family: {mono};
    font-size: {mono_size}px;
    padding: {outer}px {inner}px;
    selection-background-color: {c("accent")};
    selection-color: {c("on_accent")};
}}
QProgressBar {{
    background: {c("surface_raised")};
    border: 1px solid {c("border")};
    border-radius: {control // 2}px;
    color: {c("text2")};
    font-size: {caption}px;
    max-height: {theme.progress_height}px;
    min-height: {theme.progress_height}px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {c("accent")};
    border-radius: {control // 2}px;
}}
QScrollBar:vertical {{
    background: transparent;
    border: none;
    width: {scrollbar}px;
    margin: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    border: none;
    height: {scrollbar}px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {c("surface_raised")};
    border-radius: {scrollbar // 2}px;
    min-height: {spacing * 2}px;
}}
QScrollBar::handle:horizontal {{
    background: {c("surface_raised")};
    border-radius: {scrollbar // 2}px;
    min-width: {spacing * 2}px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: {c("border_hover")};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    background: none;
    border: none;
    height: 0;
    width: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
}}
QCheckBox, QRadioButton {{
    background: transparent;
    color: {c("text")};
    font-size: {body}px;
    spacing: {spacing}px;
}}
QCheckBox:disabled, QRadioButton:disabled {{
    color: {c("muted")};
}}
QCheckBox::indicator {{
    background: {c("surface")};
    border: 1px solid {c("border_hover")};
    border-radius: {control // 4}px;
    height: {indicator}px;
    width: {indicator}px;
}}
QCheckBox::indicator:checked {{
    background: {c("accent")};
    border-color: {c("accent")};
}}
QCheckBox::indicator:disabled {{
    background: {c("surface_raised")};
    border-color: {c("border")};
}}
QRadioButton::indicator {{
    background: {c("surface")};
    border: 1px solid {c("border_hover")};
    border-radius: {indicator // 2}px;
    height: {indicator}px;
    width: {indicator}px;
}}
QRadioButton::indicator:checked {{
    background: {c("accent")};
    border: {spacing // 2}px solid {c("surface")};
}}
QMenu {{
    background: {c("surface_raised")};
    border: 1px solid {c("border")};
    border-radius: {control}px;
    color: {c("text")};
    padding: {outer}px;
}}
QMenu::item {{
    border-radius: {control}px;
    padding: {outer}px {inner}px;
}}
QMenu::item:selected {{
    background: {c("accent_dim")};
    color: {c("text")};
}}
QMenu::item:disabled {{
    color: {c("muted")};
}}
QMenu::separator {{
    background: {c("border")};
    height: 1px;
    margin: {outer}px {inner}px;
}}
QToolTip {{
    background: {c("surface_raised")};
    border: 1px solid {c("border")};
    color: {c("text")};
    font-size: {caption}px;
    padding: {outer}px {inner}px;
}}
QListWidget#QueueList {{
    background: {c("surface")};
    border: 1px solid {c("border")};
    border-radius: {card}px;
    color: {c("text")};
    padding: {outer}px;
}}
QListWidget#QueueList::item {{
    border-radius: {control}px;
    padding: {outer}px {inner}px;
}}
QListWidget#QueueList::item:hover {{
    background: {c("surface_hover")};
}}
QListWidget#QueueList::item:selected {{
    background: {c("accent_dim")};
    border: 1px solid {c("accent_dim_border")};
    color: {c("text")};
}}
QLabel:disabled, QListWidget#QueueList:disabled {{
    color: {c("muted")};
}}
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QCheckBox:focus, QRadioButton:focus, QListWidget#QueueList:focus {{
    border: 2px solid {c("border_focus")};
}}
QWidget#SettingsFooter {{
    background: {c("toolbar_bg")};
    border-top: 1px solid {c("border")};
}}
QPushButton#SettingsFooterButton, QPushButton#SettingsPrimaryButton {{
    min-height: 32px;
    max-height: 32px;
    margin: 0px;
    padding: 0px 16px;
    border-width: 1px;
    border-style: solid;
    border-radius: {control}px;
    font-size: {body}px;
}}
QPushButton#SettingsFooterButton {{
    background: {c("surface")};
    border-color: {c("border")};
    color: {c("text")};
}}
QPushButton#SettingsFooterButton:hover {{
    background: {c("surface_hover")};
    border-color: {c("border_hover")};
}}
QPushButton#SettingsFooterButton:pressed {{
    background: {c("surface_raised")};
}}
QPushButton#SettingsPrimaryButton {{
    background: {c("accent")};
    border-color: {c("accent")};
    color: {c("on_accent")};
    font-weight: 600;
}}
QPushButton#SettingsPrimaryButton:hover {{
    background: {c("accent_hover")};
    border-color: {c("accent_hover")};
}}
QPushButton#SettingsPrimaryButton:pressed {{
    background: {c("accent_pressed")};
    border-color: {c("accent_pressed")};
}}
QPushButton#SettingsFooterButton:disabled, QPushButton#SettingsPrimaryButton:disabled {{
    background: {c("accent_dim")};
    border-color: {c("accent_dim_border")};
    color: {c("muted")};
}}
QPushButton#SettingsNavPill {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {control}px;
    color: {c("text2")};
    font-size: {body}px;
    min-height: 34px;
    max-height: 34px;
    padding: 0 {inner}px;
    text-align: left;
}}
QPushButton#SettingsNavPill:hover {{
    background: {c("surface_hover")};
    color: {c("text")};
}}
QPushButton#SettingsNavPill[active="true"] {{
    background: {c("accent_dim")};
    border-left: 3px solid {c("accent")};
    color: {c("accent")};
}}
QFrame#PresetSwatchCard {{
    background: {c("surface_raised")};
    border: 1px solid {c("border")};
    border-radius: {card}px;
}}
QFrame#PresetSwatchCard:hover {{
    background: {c("surface_hover")};
    border-color: {c("border_hover")};
}}
QFrame#PresetSwatchCard[selected="true"] {{
    background: {c("accent_dim")};
    border: 2px solid {c("accent")};
}}
QLabel#QueueThumb {{
    background: {c("surface_raised")};
    border: 1px solid {c("border")};
    border-radius: 6px;
}}
QLabel#QueueMetaPill {{
    background: {c("surface_raised")};
    border: 1px solid {c("border")};
    border-radius: {RADIUS_PILL}px;
    color: {c("text2")};
    font-size: {caption}px;
    padding: 1px {outer}px;
}}
QPushButton#QueueRowAction {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {control}px;
    min-height: 26px;
    max-height: 26px;
    min-width: 26px;
    max-width: 26px;
    padding: 0;
}}
QPushButton#QueueRowAction:hover {{
    background: {c("surface_hover")};
    border-color: {c("border")};
}}
"""


def build_palette(theme: Theme) -> QPalette:
    """Build a QPalette that matches the QSS for widgets that ignore stylesheets."""
    palette = QPalette()

    def set_color(role: QPalette.ColorRole, color: str) -> None:
        palette.setColor(role, QColor(color))

    set_color(QPalette.ColorRole.Window, theme.color("bg"))
    set_color(QPalette.ColorRole.WindowText, theme.color("text"))
    set_color(QPalette.ColorRole.Base, theme.color("surface"))
    set_color(QPalette.ColorRole.AlternateBase, theme.color("surface_raised"))
    set_color(QPalette.ColorRole.Text, theme.color("text"))
    set_color(QPalette.ColorRole.Button, theme.color("surface_raised"))
    set_color(QPalette.ColorRole.ButtonText, theme.color("text"))
    set_color(QPalette.ColorRole.BrightText, theme.color("danger"))
    set_color(QPalette.ColorRole.Highlight, theme.color("accent"))
    set_color(QPalette.ColorRole.HighlightedText, theme.color("on_accent"))
    set_color(QPalette.ColorRole.ToolTipBase, theme.color("surface_raised"))
    set_color(QPalette.ColorRole.ToolTipText, theme.color("text"))
    set_color(QPalette.ColorRole.PlaceholderText, theme.color("muted"))
    set_color(QPalette.ColorRole.Link, theme.color("accent_hover"))

    disabled = QPalette.ColorGroup.Disabled
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.HighlightedText,
    ):
        palette.setColor(disabled, role, QColor(theme.color("muted")))
    palette.setColor(disabled, QPalette.ColorRole.Base, QColor(theme.color("surface_raised")))
    palette.setColor(disabled, QPalette.ColorRole.Button, QColor(theme.color("surface_raised")))
    palette.setColor(disabled, QPalette.ColorRole.Highlight, QColor(theme.color("border")))

    return palette


def apply_theme(app: QApplication, theme: Theme) -> None:
    """Apply fonts, palette and stylesheet to the running application."""
    load_qt_fonts()
    app.setPalette(build_palette(theme))
    app.setStyleSheet(build_qss(theme))

    font = QFont()
    font.setFamilies(list(UI_FONT_FAMILIES))
    font.setPixelSize(theme.fonts.body)
    app.setFont(font)
