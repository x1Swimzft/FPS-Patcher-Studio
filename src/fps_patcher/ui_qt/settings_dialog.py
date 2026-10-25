"""Modal Qt settings dialog: seven tabs, draft/apply semantics, live theme preview."""

from __future__ import annotations

import contextlib
import copy
import json
import platform
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPropertyAnimation, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..config import (
    BACKDROP_MODES,
    FONT_SIZES,
    LAYOUT_DENSITIES,
    MAX_BXD_PADDING_BYTES,
    NOTIFY_MODES,
    RADIUS_STYLES,
    THEME_PRESETS,
    Settings,
    app_data_dir,
    render_filename_template,
)
from ..core.ffmpeg_locator import locate
from ..core.models import FPS_PRESETS
from ..core.strategies import UI_PRESETS, migrate_strategy_name
from ..ui.strings import t
from .icons import get_icon
from .motion import fade_in
from .qss import build_qss
from .theme import PRESETS, Theme, ThemeManager, ThemeTokens
from .widgets import Card, SegmentedControl, Switch, set_prop, text_button

SWATCHES = ["#3B82F6", "#8B5CF6", "#10B981", "#F43F5E", "#F59E0B", "#06B6D4", "#EC4899"]
CUSTOM_PRESET = "Custom"

DIALOG_WIDTH = 920
DIALOG_HEIGHT = 640
DIALOG_MIN_WIDTH = 820
DIALOG_MIN_HEIGHT = 560
SIDEBAR_WIDTH = 210
FOOTER_HEIGHT = 52
GRID_GAP = 16
PAGE_MARGIN = 20

_NAV_ICONS = {
    "appearance": "sun",
    "output": "folder",
    "patching": "zap",
    "ffmpeg": "play",
    "console": "info",
    "behavior": "settings",
    "about": "forensic",
}

# Local structural rules only; every colour and metric still comes from build_qss.
_SCROLL_QSS = """
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QStackedWidget { background: transparent; }
"""


class _PresetCard(QFrame):
    """Clickable visual preset swatch: mini bg/surface/accent dots plus name."""

    clicked = Signal(str)

    def __init__(
        self,
        name: str,
        tokens: ThemeTokens,
        mode: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.preset_name = name
        self.setObjectName("PresetSwatchCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(name)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        dots = QHBoxLayout()
        dots.setContentsMargins(0, 0, 0, 0)
        dots.setSpacing(4)
        self.dots: list[QLabel] = []
        for _index in range(3):
            dot = QLabel()
            dot.setFixedSize(12, 12)
            dots.addWidget(dot)
            self.dots.append(dot)
        dots.addStretch(1)
        layout.addLayout(dots)

        self.name_label = QLabel(name)
        self.name_label.setProperty("role", "caption")
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)
        self.set_colors(tokens, mode)

    def set_colors(self, tokens: ThemeTokens, mode: str) -> None:
        index = 0 if mode == "light" else 1
        border = tokens.border[index]
        for dot, pair in zip(
            self.dots, (tokens.bg, tokens.surface, tokens.accent), strict=True
        ):
            dot.setStyleSheet(
                f"background: {pair[index]}; border: 1px solid {border}; border-radius: 6px;"
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.preset_name)
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self.preset_name)
            return
        super().keyPressEvent(event)


class SettingsDialog(QDialog):
    """Settings modal built on a cloned draft so Cancel can discard edits."""

    applied = Signal(object)
    download_requested = Signal()

    _TABS = [
        ("appearance", "tab_appearance"),
        ("output", "tab_output"),
        ("patching", "tab_patching"),
        ("ffmpeg", "tab_ffmpeg"),
        ("console", "tab_console"),
        ("behavior", "tab_behavior"),
        ("about", "tab_about"),
    ]

    def __init__(
        self,
        settings: Settings,
        theme_manager: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._theme_manager = theme_manager
        self._draft = copy.deepcopy(settings)
        self._nav_buttons: dict[str, QPushButton] = {}
        self._pages: list[tuple[str, QPushButton, QScrollArea]] = []
        self._page_layouts: list[QGridLayout] = []
        self._themed_widgets: list[Any] = []
        self._swatches: list[tuple[QPushButton, str]] = []
        self._preset_cards: dict[str, _PresetCard] = {}
        self._search_rows: list[tuple[QPushButton, str]] = []
        self._last_tab = "appearance"
        self._ff_status: QLabel | None = None
        self._ff_status_token = "muted"
        self._fade_anim: QPropertyAnimation | None = None

        self.setObjectName("SettingsDialog")
        self.setWindowTitle(self._title())
        self.resize(DIALOG_WIDTH, DIALOG_HEIGHT)
        self.setMinimumSize(DIALOG_MIN_WIDTH, DIALOG_MIN_HEIGHT)
        self.setSizeGripEnabled(True)
        self.setModal(True)
        self.setWindowOpacity(max(0.85, min(1.0, float(settings.window_alpha))))

        self._root = QVBoxLayout(self)
        self._build_ui()
        self._theme_manager.changed.connect(self._refresh_theme)

    # ------------------------------------------------------------------ text
    def _tr(self, key: str, **kwargs: object) -> str:
        return t(key, self._draft.language, **kwargs)

    def _title(self) -> str:
        return f"{self._tr('settings_title')} — {self._tr('app_title')}"

    # -------------------------------------------------------------- assembly
    def _build_ui(self) -> None:
        theme = self._theme_manager.theme
        self.setWindowTitle(self._title())
        self.setStyleSheet(build_qss(theme) + _SCROLL_QSS)
        self._themed_widgets = []
        self._swatches = []
        self._preset_cards = {}
        self._search_rows = []
        self._page_layouts = []
        self._pages = []
        self._nav_buttons = {}
        self._ff_status = None

        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)

        body_row = QHBoxLayout()
        body_row.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, 16)
        body_row.setSpacing(GRID_GAP)
        body_row.addWidget(self._build_rail(theme))
        body_row.addWidget(self._build_body(theme), 1)
        self._root.addLayout(body_row, 1)
        self._build_search_page()
        self._root.addWidget(self._build_footer(theme), 0)
        self._select_tab("appearance")
        self._sync_preset_cards()

    def _build_rail(self, theme: Theme) -> Card:
        rail = Card(theme)
        rail.setObjectName("SettingsRail")
        rail.setFixedWidth(SIDEBAR_WIDTH)
        self._themed_widgets.append(rail)
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        rail.body.addLayout(layout)

        self._search = QLineEdit()
        self._search.setObjectName("SettingsSearch")
        self._search.setPlaceholderText(self._tr("settings_search_placeholder"))
        self._search.setAccessibleName(self._tr("settings_search_placeholder"))
        self._search.setClearButtonEnabled(True)
        self._search.setFixedHeight(28)
        # QSS min-height is the content box; subtract the 1px border to land on 28px total.
        self._search.setStyleSheet(
            "QLineEdit#SettingsSearch { min-height: 26px; max-height: 26px; }"
        )
        self._search.textChanged.connect(self._filter_settings)
        layout.addWidget(self._search)
        layout.addSpacing(6)

        for key, label_key in self._TABS:
            label = self._tr(label_key)
            button = QPushButton(label.replace("&", "&&"))
            button.setObjectName("SettingsNavPill")
            button.setProperty("active", "false")
            button.setFixedHeight(34)
            # QSS min/max-height is the content box; 32px + 1px border lands on 34px total.
            button.setStyleSheet(
                "QPushButton#SettingsNavPill { min-height: 32px; max-height: 32px; }"
            )
            button.setIcon(get_icon(_NAV_ICONS[key], theme.is_dark))
            button.setIconSize(QSize(16, 16))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.setAccessibleName(label)
            button.clicked.connect(lambda _checked=False, k=key: self._nav_clicked(k))
            layout.addWidget(button)
            self._nav_buttons[key] = button
        layout.addStretch(1)
        return rail

    def _build_body(self, theme: Theme) -> QWidget:
        body = QWidget()
        body.setObjectName("SettingsBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self._stack = QStackedWidget()
        self._stack.setObjectName("SettingsStack")
        body_layout.addWidget(self._stack)

        self._build_appearance()
        self._build_output()
        self._build_patching()
        self._build_ffmpeg()
        self._build_console()
        self._build_behavior()
        self._build_about()
        return body

    def _build_footer(self, theme: Theme) -> QWidget:
        footer = QWidget()
        footer.setObjectName("SettingsFooter")
        footer.setFixedHeight(FOOTER_HEIGHT)
        footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(footer)
        row.setContentsMargins(20, 10, 20, 10)
        row.setSpacing(8)

        self._reset_btn = self._footer_button(
            self._tr("reset_to_defaults"), "SettingsFooterButton", self._reset_all
        )
        self._cancel_btn = self._footer_button(
            self._tr("cancel"), "SettingsFooterButton", self.reject
        )
        self._apply_btn = self._footer_button(
            self._tr("apply"), "SettingsFooterButton", self._apply
        )
        self._ok_btn = self._footer_button(
            self._tr("ok"), "SettingsPrimaryButton", self._ok
        )
        self._ok_btn.setDefault(True)
        row.addWidget(self._reset_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        row.addWidget(self._cancel_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._apply_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._ok_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self._footer = footer
        return footer

    def _footer_button(
        self,
        text: str,
        object_name: str,
        on_click: Callable[[], None],
    ) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setFixedHeight(32)
        # QSS min/max-height is the content box; 30px + 1px border lands on 32px total.
        button.setStyleSheet(
            "QPushButton { min-height: 30px; max-height: 30px; }"
        )
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.clicked.connect(on_click)
        return button

    def _new_page(self, key: str) -> tuple[QWidget, QGridLayout]:
        scroll = QScrollArea()
        scroll.setObjectName(f"SettingsTab_{key}")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        page.setObjectName(f"SettingsPage_{key}")
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(GRID_GAP)
        grid.setVerticalSpacing(GRID_GAP)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(99, 1)
        scroll.setWidget(page)
        self._stack.addWidget(scroll)
        self._page_layouts.append(grid)
        self._pages.append((key, self._nav_buttons[key], scroll))

        banner = QLabel(self._tr(f"settings_banner_{key}"))
        banner.setProperty("role", "title")
        banner.setWordWrap(True)
        banner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        grid.addWidget(banner, 0, 0, 1, 2)
        return page, grid

    def _card(
        self,
        grid: QGridLayout,
        row: int,
        column: int,
        row_span: int = 1,
        *,
        expand: bool = False,
    ) -> QVBoxLayout:
        theme = self._theme_manager.theme
        card = Card(theme)
        vertical = QSizePolicy.Policy.Expanding if expand else QSizePolicy.Policy.Maximum
        card.setSizePolicy(QSizePolicy.Policy.Expanding, vertical)
        layout = QVBoxLayout()
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        card.body.addLayout(layout)
        if expand:
            grid.addWidget(card, row, column, row_span, 1)
        else:
            grid.addWidget(card, row, column, row_span, 1, Qt.AlignmentFlag.AlignTop)
        self._themed_widgets.append(card)
        return layout

    # ------------------------------------------------------- shared controls
    def _section(self, layout: QVBoxLayout, key: str) -> QLabel:
        theme = self._theme_manager.theme
        if layout.count():
            layout.addSpacing(theme.outer)
        label = QLabel(self._tr(key))
        label.setProperty("role", "title")
        label.setProperty("settingsSearch", True)
        label.setWordWrap(True)
        layout.addWidget(label)
        return label

    def _hint(self, layout: QVBoxLayout, key: str) -> QLabel:
        label = QLabel(self._tr(key))
        label.setProperty("role", "caption")
        label.setProperty("settingsSearch", True)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(label)
        return label

    def _field_label(self, layout: QVBoxLayout, key: str) -> QLabel:
        label = QLabel(self._tr(key))
        label.setProperty("settingsSearch", True)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(label)
        return label

    def _entry(self, layout: QVBoxLayout, key: str, value: str, placeholder: str = "") -> QLineEdit:
        label = self._field_label(layout, key)
        edit = QLineEdit(value)
        edit.setPlaceholderText(placeholder)
        edit.setAccessibleName(label.text())
        label.setBuddy(edit)
        layout.addWidget(edit)
        return edit

    def _path_row(
        self,
        layout: QVBoxLayout,
        key: str,
        value: str,
        *,
        hint_key: str | None = None,
        reset: bool = False,
    ) -> QLineEdit:
        theme = self._theme_manager.theme
        label = self._field_label(layout, key)
        if hint_key:
            self._hint(layout, hint_key)
        row = QHBoxLayout()
        row.setSpacing(theme.spacing)
        edit = QLineEdit(value)
        edit.setAccessibleName(label.text())
        label.setBuddy(edit)
        browse = text_button(
            self._tr("browse"),
            theme,
            lambda: self._choose_dir(edit),
            variant="secondary",
        )
        row.addWidget(edit, 1)
        row.addWidget(browse)
        if reset:
            row.addWidget(text_button(self._tr("reset"), theme, edit.clear, variant="ghost"))
        layout.addLayout(row)
        return edit

    def _combo(
        self,
        layout: QVBoxLayout,
        key: str,
        items: list[str],
        current: str,
        on_change: Callable[[str], None],
    ) -> QComboBox:
        label = self._field_label(layout, key)
        combo = QComboBox()
        combo.addItems(items)
        combo.setCurrentText(current if current in items else items[0])
        combo.setAccessibleName(label.text())
        label.setBuddy(combo)
        combo.currentTextChanged.connect(on_change)
        layout.addWidget(combo)
        return combo

    def _segmented(
        self,
        layout: QVBoxLayout,
        key: str,
        items: list[str],
        current: str,
        on_change: Callable[[str], None],
    ) -> SegmentedControl:
        theme = self._theme_manager.theme
        label = self._field_label(layout, key)
        control = SegmentedControl(items, theme)
        control.set_reduce_motion(bool(self._draft.reduce_motion))
        if current in items:
            control.set_value(current)
        control.setAccessibleName(label.text())
        control.valueChanged.connect(on_change)
        self._themed_widgets.append(control)
        layout.addWidget(control)
        return control

    def _switch(self, layout: QVBoxLayout, key: str, checked: bool) -> Switch:
        theme = self._theme_manager.theme
        row = QHBoxLayout()
        row.setSpacing(theme.spacing)
        label = QLabel(self._tr(key))
        label.setProperty("settingsSearch", True)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        switch = Switch(theme)
        switch.setChecked(checked)
        switch.setAccessibleName(label.text())
        switch.setToolTip(label.text())
        row.addWidget(label, 1)
        row.addWidget(switch, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(row)
        self._themed_widgets.append(switch)
        return switch

    def _spin(
        self,
        layout: QVBoxLayout,
        key: str,
        value: int,
        minimum: int,
        maximum: int,
        step: int = 1,
        suffix: str = "",
    ) -> QSpinBox:
        label = self._field_label(layout, key)
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setAccelerated(True)
        if suffix:
            spin.setSuffix(suffix)
        spin.setValue(value)
        spin.setAccessibleName(label.text())
        label.setBuddy(spin)
        layout.addWidget(spin)
        return spin

    def _slider(
        self,
        layout: QVBoxLayout,
        key: str,
        value: int,
        minimum: int,
        maximum: int,
        suffix: str = "%",
    ) -> QSlider:
        theme = self._theme_manager.theme
        label = self._field_label(layout, key)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.setAccessibleName(label.text())
        readout = QLabel(f"{value}{suffix}")
        readout.setProperty("role", "muted")
        readout.setMinimumWidth(theme.spacing * 4)
        readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def update_readout(current: int) -> None:
            readout.setText(f"{current}{suffix}")

        slider.valueChanged.connect(update_readout)
        row = QHBoxLayout()
        row.setSpacing(theme.spacing)
        row.addWidget(slider, 1)
        row.addWidget(readout)
        layout.addLayout(row)
        return slider

    # ------------------------------------------------------------ appearance
    def _build_appearance(self) -> None:
        _page, grid = self._new_page("appearance")
        draft = self._draft

        preset = self._card(grid, 1, 0)
        self._field_label(preset, "theme_preset")
        self._hint(preset, "settings_helper_preset")
        self._preset = QComboBox()
        self._preset.addItems(THEME_PRESETS)
        current_preset = (
            draft.theme_preset if draft.theme_preset in THEME_PRESETS else THEME_PRESETS[0]
        )
        self._preset.setCurrentText(current_preset)
        self._preset.currentTextChanged.connect(self._on_preset)
        self._preset.hide()
        preset.addWidget(self._preset)

        swatch_grid = QGridLayout()
        swatch_grid.setContentsMargins(0, 4, 0, 0)
        swatch_grid.setHorizontalSpacing(8)
        swatch_grid.setVerticalSpacing(8)
        swatch_grid.setColumnStretch(0, 1)
        swatch_grid.setColumnStretch(1, 1)
        mode = "light" if draft.appearance == "light" else "dark"
        for index, name in enumerate(THEME_PRESETS):
            card = _PresetCard(name, PRESETS[name], mode)
            card.clicked.connect(self._choose_preset)
            swatch_grid.addWidget(card, index // 2, index % 2)
            self._preset_cards[name] = card
        preset.addLayout(swatch_grid)

        custom = self._card(grid, 1, 1, row_span=2, expand=True)
        self._field_label(custom, "custom_accent")
        self._accent = QLineEdit(draft.custom_accent)
        self._accent.setPlaceholderText("#RRGGBB")
        self._accent.setAccessibleName(self._tr("custom_accent"))
        self._accent.textChanged.connect(self._on_accent)
        custom.addWidget(self._accent)
        self._hint(custom, "settings_helper_accent")

        swatch_label = QLabel(self._tr("accent_swatches"))
        swatch_label.setProperty("role", "caption")
        swatch_label.setProperty("settingsSearch", True)
        custom.addWidget(swatch_label)
        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(self._theme_manager.theme.outer)
        theme = self._theme_manager.theme
        for color in SWATCHES:
            button = QPushButton()
            button.setProperty("variant", "icon")
            button.setProperty("motionSkip", True)
            button.setFixedSize(theme.icon_button_size, theme.icon_button_size)
            button.setToolTip(color)
            button.setAccessibleName(f"{self._tr('custom_accent')} {color}")
            button.clicked.connect(lambda _checked=False, c=color: self._pick_accent(c))
            self._style_swatch(button, color)
            self._swatches.append((button, color))
            swatch_row.addWidget(button)
        swatch_row.addStretch(1)
        custom.addLayout(swatch_row)

        self._appearance_labels = [self._tr("mode_dark"), self._tr("mode_light")]
        current_mode = self._appearance_labels[1 if draft.appearance == "light" else 0]
        self._appearance = self._segmented(
            custom,
            "appearance_mode",
            self._appearance_labels,
            current_mode,
            self._on_appearance,
        )

        self._density_labels = [self._tr("density_compact"), self._tr("density_comfortable")]
        current_density = (
            self._density_labels[1]
            if draft.layout_density == "Comfortable"
            else self._density_labels[0]
        )
        self._density = self._segmented(
            custom,
            "layout_density",
            self._density_labels,
            current_density,
            self._on_density,
        )
        self._hint(custom, "settings_helper_density")

        self._ui_scale = self._spin(custom, "ui_scale", draft.ui_scale, 50, 200, 5, "%")
        self._hint(custom, "settings_helper_scale")

        self._reduce_motion = self._switch(custom, "reduce_motion", draft.reduce_motion)
        self._hint(custom, "settings_helper_motion")

        window = self._card(grid, 2, 0)
        self._glass = self._switch(window, "glass_effect", draft.glass)
        self._backdrop = self._combo(
            window,
            "glass_mode",
            BACKDROP_MODES,
            draft.glass_mode,
            lambda value: setattr(self._draft, "glass_mode", value),
        )
        self._tint = self._slider(window, "tint_strength", draft.tint_strength, 0, 100)
        self._alpha = self._slider(window, "window_alpha", round(draft.window_alpha * 100), 85, 100)
        self._alpha.valueChanged.connect(
            lambda value: self.setWindowOpacity(max(0.85, min(1.0, value / 100.0)))
        )
        self._font_size = self._combo(
            window, "font_size", FONT_SIZES, draft.font_size, self._on_font_size
        )
        self._radius = self._segmented(
            window,
            "radius_style",
            RADIUS_STYLES,
            draft.radius_style,
            lambda value: self._set_and_preview("radius_style", value),
        )

    def _choose_preset(self, name: str) -> None:
        if name != self._preset.currentText():
            self._preset.setCurrentText(name)
        else:
            self._sync_preset_cards()

    def _sync_preset_cards(self) -> None:
        if not self._preset_cards:
            return
        theme = self._theme_manager.theme
        current = self._preset.currentText()
        for name, card in self._preset_cards.items():
            set_prop(card, "selected", "true" if name == current else "false")
            card.set_colors(PRESETS[name], theme.mode)

    def _on_preset(self, value: str) -> None:
        self._draft.theme_preset = value
        with QSignalBlocker(self._accent):
            self._accent.clear()
        self._draft.custom_accent = ""
        self._sync_preset_cards()
        self._preview_theme()

    def _on_accent(self, value: str) -> None:
        self._draft.custom_accent = value.strip()
        self._preview_theme()

    def _on_appearance(self, value: str) -> None:
        self._draft.appearance = "light" if value == self._appearance_labels[1] else "dark"
        self._preview_theme()

    def _on_font_size(self, value: str) -> None:
        self._draft.font_size = value
        self._preview_theme()

    def _on_density(self, value: str) -> None:
        index = self._density_labels.index(value)
        self._draft.layout_density = LAYOUT_DENSITIES[index]
        self._preview_theme()

    def _set_and_preview(self, field_name: str, value: str) -> None:
        setattr(self._draft, field_name, value)
        self._preview_theme()

    def _pick_accent(self, color: str) -> None:
        with QSignalBlocker(self._accent):
            self._accent.setText(color)
        self._draft.custom_accent = color
        self._preview_theme()

    def _style_swatch(self, button: QPushButton, color: str) -> None:
        theme = self._theme_manager.theme
        radius = theme.icon_button_size // 2
        button.setStyleSheet(
            "QPushButton {"
            f"background: {color};"
            f"border: 1px solid {theme.color('border')};"
            f"border-radius: {radius}px;"
            "}"
            "QPushButton:hover {"
            f"border-color: {theme.color('text')};"
            "}"
        )

    # ---------------------------------------------------------------- output
    def _build_output(self) -> None:
        _page, grid = self._new_page("output")
        draft = self._draft
        paths = self._card(grid, 1, 0)
        self._out_dir = self._path_row(
            paths,
            "default_output_dir",
            draft.output_dir,
            hint_key="leave_empty_source",
            reset=True,
        )
        self._template = self._entry(paths, "filename_template", draft.filename_template)
        self._hint(paths, "template_help")
        self._template_preview = QLabel()
        self._template_preview.setProperty("role", "caption")
        self._template_preview.setWordWrap(True)
        paths.addWidget(self._template_preview)
        self._template.textChanged.connect(self._update_template_preview)
        self._update_template_preview()

        workflow = self._card(grid, 1, 1)
        self._open_done = self._switch(workflow, "open_when_done", draft.open_when_done)
        self._preserve_mtime = self._switch(workflow, "preserve_mtime", draft.preserve_mtime)

        watch = self._card(grid, 2, 0)
        self._section(watch, "watch_folder_section")
        self._hint(watch, "watch_folder_hint")
        self._watch_enabled = self._switch(
            watch, "watch_folder_enable", draft.watch_folder_enabled
        )
        self._watch_dir = self._path_row(watch, "watch_folder_dir", draft.watch_folder)

        explorer = self._card(grid, 2, 1)
        self._explorer_menu = self._switch(
            explorer, "explorer_menu_enable", draft.explorer_menu
        )

    def _update_template_preview(self, _value: str = "") -> None:
        template = self._template.text().strip() or "{name}_{fps}fps"
        rendered = render_filename_template(template, "sample_clip", 60)
        self._template_preview.setText(self._tr("template_preview", preview=f"{rendered}.mp4"))

    # -------------------------------------------------------------- patching
    def _build_patching(self) -> None:
        _page, grid = self._new_page("patching")
        draft = self._draft
        self._custom_fps = self._tr("custom")
        fps_items = [*FPS_PRESETS, self._custom_fps]
        if draft.last_preset == CUSTOM_PRESET:
            current_fps = self._custom_fps
        elif draft.last_preset in fps_items:
            current_fps = draft.last_preset
        else:
            current_fps = self._first_fps(fps_items)

        target = self._card(grid, 1, 0)
        self._fps_preset = self._combo(
            target,
            "default_target_preset",
            fps_items,
            current_fps,
            self._on_fps_preset,
        )
        self._timescale = self._spin(
            target, "default_timescale", draft.custom_timescale, 1, 2_000_000_000
        )
        self._timescale.setEnabled(current_fps == self._custom_fps)

        strategy_labels = [preset.label for preset in UI_PRESETS.values()]
        self._strategy_label_to_key = {preset.label: preset.name for preset in UI_PRESETS.values()}
        resolved, _old = migrate_strategy_name(draft.strategy)
        current_strategy = UI_PRESETS.get(resolved)
        self._strategy = self._combo(
            target,
            "default_strategy",
            strategy_labels,
            current_strategy.label if current_strategy else strategy_labels[0],
            lambda _value: None,
        )
        self._padding = self._spin(
            target, "bxd_padding_lbl", draft.bxd_padding_bytes, 0, MAX_BXD_PADDING_BYTES, 1024
        )
        self._tail_ms = self._spin(
            target, "bxd_tail_ms_lbl", draft.bxd_max_tail_ms, 0, 5000
        )

        safety = self._card(grid, 1, 1)
        self._mask_paths = self._switch(safety, "mask_paths_lbl", draft.mask_diagnostic_paths)
        self._verify = self._switch(safety, "verify_after", draft.verify_after)
        self._backup = self._switch(safety, "backup_original", draft.backup_original)
        self._stop_on_error = self._switch(safety, "stop_on_error", draft.stop_on_error)

        container = self._card(grid, 2, 0)
        self._section(container, "v4_options")
        self._v4_strict = self._switch(container, "v4_strict", draft.v4_strict_lossless)
        self._v4_video = self._switch(container, "v4_preserve_video", draft.v4_preserve_video)
        self._v4_audio = self._switch(container, "v4_preserve_audio", draft.v4_preserve_audio)
        self._v4_sync = self._switch(container, "v4_sync_mvhd", draft.v4_sync_mvhd)
        self._v4_report = self._switch(container, "v4_export_report", draft.v4_export_report)
        self._v4_dry_run = self._switch(container, "v4_dry_run", draft.v4_dry_run)

        preflight = self._card(grid, 2, 1)
        self._section(preflight, "preflight_section")
        self._normalize_audio = self._switch(
            preflight, "auto_normalize_audio", draft.auto_normalize_audio
        )
        self._cap_bitrate = self._switch(preflight, "auto_cap_bitrate", draft.auto_cap_bitrate)

        self._section(preflight, "color_metadata_section")
        self._fix_color = self._switch(preflight, "fix_color_tag", draft.fix_color_tag)
        self._scrub_metadata = self._switch(preflight, "scrub_metadata", draft.scrub_metadata)

    @staticmethod
    def _first_fps(items: list[str]) -> str:
        return next(iter(FPS_PRESETS), items[0])

    def _on_fps_preset(self, value: str) -> None:
        custom = value == self._custom_fps
        self._draft.last_preset = CUSTOM_PRESET if custom else value
        self._timescale.setEnabled(custom)

    # ---------------------------------------------------------------- ffmpeg
    def _build_ffmpeg(self) -> None:
        theme = self._theme_manager.theme
        _page, grid = self._new_page("ffmpeg")
        draft = self._draft

        location = self._card(grid, 1, 0)
        label = self._field_label(location, "ffmpeg_dir")
        row = QHBoxLayout()
        row.setSpacing(theme.spacing)
        self._ffmpeg_dir = QLineEdit(draft.ffmpeg_dir)
        self._ffmpeg_dir.setAccessibleName(label.text())
        label.setBuddy(self._ffmpeg_dir)
        row.addWidget(self._ffmpeg_dir, 1)
        row.addWidget(
            text_button(
                self._tr("browse"),
                theme,
                lambda: self._choose_dir(self._ffmpeg_dir),
                variant="secondary",
            )
        )
        row.addWidget(
            text_button(
                self._tr("auto_detect"), theme, self._autodetect_ffmpeg, variant="secondary"
            )
        )
        location.addLayout(row)

        test_row = QHBoxLayout()
        test_row.setSpacing(theme.spacing)
        test_row.addWidget(
            text_button(self._tr("test_ffmpeg"), theme, self._test_ffmpeg, variant="secondary")
        )
        self._ff_status = QLabel()
        self._ff_status.setProperty("role", "caption")
        self._ff_status.setWordWrap(True)
        self._ff_status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        test_row.addWidget(self._ff_status, 1)
        location.addLayout(test_row)

        download = text_button(
            self._tr("ffmpeg_auto_download_btn"),
            theme,
            self.download_requested.emit,
            variant="secondary",
        )
        location.addWidget(download)

        options = self._card(grid, 1, 1)
        self._check_ffmpeg = self._switch(options, "check_on_start", draft.check_ffmpeg_on_start)
        self._show_ffmpeg = self._switch(options, "show_output_console", draft.show_ffmpeg_output)

        self._section(options, "extra_args")
        self._hint(options, "extra_args_warn")
        self._extra_args = self._entry(options, "extra_args", draft.extra_ffmpeg_args)

    def _set_ff_status(self, text: str, token: str) -> None:
        if self._ff_status is None:
            return
        self._ff_status_token = token
        self._ff_status.setText(text)
        self._ff_status.setStyleSheet(f"color: {self._theme_manager.theme.color(token)};")

    def _autodetect_ffmpeg(self) -> None:
        try:
            paths = locate()
        except Exception:
            self._set_ff_status(self._tr("ffmpeg_not_found"), "danger")
            return
        self._ffmpeg_dir.setText(str(paths.ffmpeg.parent))
        self._set_ff_status(self._tr("ffmpeg_ok"), "success")
        if self._ff_status is not None:
            self._ff_status.setToolTip(paths.version)

    def _test_ffmpeg(self) -> None:
        folder = self._ffmpeg_dir.text().strip()
        custom = Path(folder) if folder else None
        try:
            paths = locate(custom)
        except Exception:
            self._set_ff_status(self._tr("ffmpeg_not_found"), "danger")
            return
        self._set_ff_status(self._tr("ffmpeg_ok"), "success")
        if self._ff_status is not None:
            self._ff_status.setToolTip(paths.version)

    # --------------------------------------------------------------- console
    def _build_console(self) -> None:
        _page, grid = self._new_page("console")
        draft = self._draft
        display = self._card(grid, 1, 0)
        self._console_font = self._spin(
            display, "console_font_size", draft.console_font_size, 8, 24
        )
        self._log_timestamps = self._switch(display, "log_timestamps", draft.log_timestamps)
        self._log_autoscroll = self._switch(display, "log_autoscroll", draft.log_autoscroll)

        retention = self._card(grid, 1, 1)
        self._max_log_lines = self._spin(
            retention, "max_log_lines", draft.max_log_lines, 100, 20000, 100
        )
        self._log_to_file = self._switch(retention, "log_to_file", draft.log_to_file)

    # -------------------------------------------------------------- behavior
    def _build_behavior(self) -> None:
        _page, grid = self._new_page("behavior")
        draft = self._draft
        window = self._card(grid, 1, 0)
        self._remember_geometry = self._switch(
            window, "remember_geometry", draft.remember_geometry
        )
        self._always_on_top = self._switch(window, "always_on_top", draft.always_on_top)

        workflow = self._card(grid, 1, 1)
        self._confirm_cancel = self._switch(workflow, "confirm_cancel", draft.confirm_cancel)
        self._confirm_overwrite = self._switch(
            workflow, "confirm_overwrite", draft.confirm_overwrite
        )

        language = self._card(grid, 2, 0)
        self._language_labels = [
            f"{self._tr('language_en')} (en)",
            f"{self._tr('language_th')} (th)",
        ]
        self._language = self._combo(
            language,
            "language_choice",
            self._language_labels,
            self._language_labels[1 if draft.language == "th" else 0],
            self._on_language,
        )

        notify_card = self._card(grid, 2, 1)
        self._notify_labels = [
            self._tr("notify_none"),
            self._tr("notify_sound"),
            self._tr("notify_toast"),
        ]
        current_notify = (
            self._notify_labels[NOTIFY_MODES.index(draft.notify_done)]
            if draft.notify_done in NOTIFY_MODES
            else self._notify_labels[0]
        )
        self._notify = self._combo(
            notify_card,
            "notify_done",
            self._notify_labels,
            current_notify,
            lambda _value: None,
        )
        self._check_updates = self._switch(
            notify_card, "check_updates_on_start", draft.check_updates_on_start
        )

    def _on_language(self, value: str) -> None:
        self._draft.language = "th" if "th" in value else "en"
        self._harvest()
        self._rebuild()

    # ----------------------------------------------------------------- about
    def _build_about(self) -> None:
        theme = self._theme_manager.theme
        _page, grid = self._new_page("about")

        info = self._card(grid, 1, 0)
        version = QLabel(self._tr("app_info", version=__version__))
        version.setProperty("role", "title")
        version.setProperty("settingsSearch", True)
        version.setWordWrap(True)
        info.addWidget(version)
        self._hint(info, "about_desc")

        actions = self._card(grid, 1, 1)
        copy = text_button(self._tr("copy_diagnostics"), theme, self._copy_diagnostics)
        export = text_button(self._tr("export_settings"), theme, self._export_settings)
        import_btn = text_button(self._tr("import_settings"), theme, self._import_settings)
        reset = text_button(self._tr("reset_defaults"), theme, self._reset_all, variant="secondary")
        for button in (copy, export, import_btn, reset):
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            actions.addWidget(button)
        self._hint(actions, "restart_hint")

    def _copy_diagnostics(self) -> None:
        payload = {
            "app": __version__,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "settings_path": str(app_data_dir() / "settings.json"),
        }
        QApplication.clipboard().setText(json.dumps(payload, indent=2))
        QMessageBox.information(self, self._tr("copy_diagnostics"), self._tr("diagnostics_copied"))

    def _export_settings(self) -> None:
        self._harvest()
        path, _filter = QFileDialog.getSaveFileName(
            self,
            self._tr("export_settings"),
            str(app_data_dir() / "settings.json"),
            "*.json",
        )
        if not path:
            return
        self._draft.save(Path(path))
        QMessageBox.information(
            self, self._tr("export_settings"), self._tr("export_success", path=path)
        )

    def _import_settings(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, self._tr("import_settings"), "", "*.json")
        if not path:
            return
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("settings json must be an object")
        except (OSError, ValueError):
            QMessageBox.warning(self, self._tr("import_settings"), self._tr("import_error"))
            return
        self._draft = Settings.load(Path(path))
        self._rebuild()
        self._theme_manager.apply(self._draft)
        QMessageBox.information(self, self._tr("import_settings"), self._tr("import_success"))

    # ----------------------------------------------------------------- search
    def _build_search_page(self) -> None:
        scroll = QScrollArea()
        scroll.setObjectName("SettingsSearchResults")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        page.setObjectName("SettingsSearchPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._search_empty = QLabel(self._tr("settings_search_empty"))
        self._search_empty.setProperty("role", "caption")
        self._search_empty.setWordWrap(True)
        self._search_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._search_empty.hide()
        layout.addWidget(self._search_empty)

        seen: set[tuple[str, str]] = set()
        for key, _button, tab_scroll in self._pages:
            tab_page = tab_scroll.widget()
            if tab_page is None:
                continue
            tab_label = self._tr(dict(self._TABS)[key])
            for label in tab_page.findChildren(QLabel):
                text = label.text().strip()
                if not text or not label.property("settingsSearch"):
                    continue
                dedupe = (key, text.casefold())
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                row = QPushButton(text.replace("&", "&&"))
                row.setProperty("variant", "ghost")
                row.setStyleSheet("text-align: left;")
                row.setCursor(Qt.CursorShape.PointingHandCursor)
                row.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                row.setAccessibleName(text)
                row.setToolTip(tab_label)
                row.clicked.connect(
                    lambda _checked=False, k=key: self._open_search_result(k)
                )
                layout.addWidget(row)
                self._search_rows.append((row, text.casefold()))
        layout.addStretch(1)
        scroll.setWidget(page)
        self._search_scroll = scroll
        self._stack.addWidget(scroll)

    def _filter_settings(self, text: str) -> None:
        query = text.strip().casefold()
        if not query:
            self._search_empty.hide()
            self._select_tab(self._last_tab)
            return
        active = self._current_tab_key()
        if active is not None:
            self._last_tab = active
        matches = 0
        for row, haystack in self._search_rows:
            visible = query in haystack
            row.setVisible(visible)
            matches += int(visible)
        self._search_empty.setVisible(matches == 0)
        self._stack.setCurrentWidget(self._search_scroll)

    def _nav_clicked(self, key: str) -> None:
        if self._search.text():
            with QSignalBlocker(self._search):
                self._search.clear()
        self._search_empty.hide()
        self._select_tab(key)

    def _open_search_result(self, key: str) -> None:
        self._nav_clicked(key)

    # ---------------------------------------------------------------- actions
    def _current_tab_key(self) -> str | None:
        if not self._pages:
            return None
        index = self._stack.currentIndex()
        if 0 <= index < len(self._pages):
            return self._pages[index][0]
        return None

    def _select_tab(self, key: str) -> None:
        if not self._search.text().strip():
            for index, (page_key, _button, _page) in enumerate(self._pages):
                if page_key == key:
                    self._stack.setCurrentIndex(index)
                    break
        self._last_tab = key
        for page_key, button, _page in self._pages:
            set_prop(button, "active", "true" if page_key == key else "false")

    def _refresh_theme(self, theme: Theme) -> None:
        self.setStyleSheet(build_qss(theme) + _SCROLL_QSS)
        for widget in self._themed_widgets:
            with contextlib.suppress(Exception):
                widget.set_theme(theme)
        for button, color in self._swatches:
            self._style_swatch(button, color)
        for key, button in self._nav_buttons.items():
            button.setIcon(get_icon(_NAV_ICONS[key], theme.is_dark))
        self._sync_preset_cards()
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        for layout in self._page_layouts:
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(GRID_GAP)
        self._select_tab(self._current_tab_key() or self._last_tab)
        if self._ff_status is not None:
            self._set_ff_status(self._ff_status.text(), self._ff_status_token)

    def _rebuild(self) -> None:
        tab = self._current_tab_key() or self._last_tab
        self._clear_layout(self._root)
        self._build_ui()
        self._select_tab(tab)

    def _clear_layout(self, layout: QLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
                continue
            child = item.layout()
            if child is not None:
                self._clear_layout(child)

    def _harvest(self) -> None:
        draft = self._draft

        draft.theme_preset = self._preset.currentText()
        draft.appearance = (
            "light" if self._appearance.value == self._appearance_labels[1] else "dark"
        )
        draft.custom_accent = self._accent.text().strip()
        draft.glass = self._glass.isChecked()
        draft.glass_mode = self._backdrop.currentText()
        draft.tint_strength = self._tint.value()
        draft.window_alpha = round(self._alpha.value() / 100.0, 2)
        draft.radius_style = self._radius.value
        draft.reduce_motion = self._reduce_motion.isChecked()
        draft.font_size = self._font_size.currentText()
        draft.ui_scale = self._ui_scale.value()
        draft.layout_density = LAYOUT_DENSITIES[self._density_labels.index(self._density.value)]

        draft.output_dir = self._out_dir.text().strip()
        draft.filename_template = self._template.text().strip() or "{name}_{fps}fps"
        draft.open_when_done = self._open_done.isChecked()
        draft.preserve_mtime = self._preserve_mtime.isChecked()
        draft.watch_folder = self._watch_dir.text().strip()
        draft.watch_folder_enabled = self._watch_enabled.isChecked()
        draft.explorer_menu = self._explorer_menu.isChecked()

        fps_label = self._fps_preset.currentText()
        draft.last_preset = CUSTOM_PRESET if fps_label == self._custom_fps else fps_label
        draft.custom_timescale = self._timescale.value()
        draft.strategy = self._strategy_label_to_key.get(
            self._strategy.currentText(), draft.strategy
        )
        draft.bxd_padding_bytes = self._padding.value()
        draft.bxd_max_tail_ms = self._tail_ms.value()
        draft.mask_diagnostic_paths = self._mask_paths.isChecked()
        draft.v4_strict_lossless = self._v4_strict.isChecked()
        draft.v4_preserve_video = self._v4_video.isChecked()
        draft.v4_preserve_audio = self._v4_audio.isChecked()
        draft.v4_sync_mvhd = self._v4_sync.isChecked()
        draft.v4_export_report = self._v4_report.isChecked()
        draft.v4_dry_run = self._v4_dry_run.isChecked()
        draft.verify_after = self._verify.isChecked()
        draft.backup_original = self._backup.isChecked()
        draft.stop_on_error = self._stop_on_error.isChecked()
        draft.auto_normalize_audio = self._normalize_audio.isChecked()
        draft.auto_cap_bitrate = self._cap_bitrate.isChecked()
        draft.fix_color_tag = self._fix_color.isChecked()
        draft.scrub_metadata = self._scrub_metadata.isChecked()

        draft.ffmpeg_dir = self._ffmpeg_dir.text().strip()
        draft.check_ffmpeg_on_start = self._check_ffmpeg.isChecked()
        draft.show_ffmpeg_output = self._show_ffmpeg.isChecked()
        draft.extra_ffmpeg_args = self._extra_args.text().strip()

        draft.console_font_size = self._console_font.value()
        draft.max_log_lines = self._max_log_lines.value()
        draft.log_timestamps = self._log_timestamps.isChecked()
        draft.log_autoscroll = self._log_autoscroll.isChecked()
        draft.log_to_file = self._log_to_file.isChecked()

        draft.remember_geometry = self._remember_geometry.isChecked()
        draft.always_on_top = self._always_on_top.isChecked()
        draft.confirm_cancel = self._confirm_cancel.isChecked()
        draft.confirm_overwrite = self._confirm_overwrite.isChecked()
        notify_index = self._notify_labels.index(self._notify.currentText())
        draft.notify_done = NOTIFY_MODES[notify_index]
        draft.language = "th" if "th" in self._language.currentText() else "en"
        draft.check_updates_on_start = self._check_updates.isChecked()

    def _preview_theme(self) -> None:
        self._harvest()
        self._theme_manager.apply(self._draft)

    def _apply(self) -> None:
        self._harvest()
        for field in fields(Settings):
            if field.init:
                setattr(self._settings, field.name, getattr(self._draft, field.name))
        self.setWindowOpacity(
            max(0.85, min(1.0, float(self._settings.window_alpha)))
        )
        self._settings.save()
        self._draft = copy.deepcopy(self._settings)
        self._theme_manager.apply(self._settings)
        self.applied.emit(self._settings)

    def _ok(self) -> None:
        self._apply()
        self.accept()

    def _reset_all(self) -> None:
        answer = QMessageBox.question(
            self,
            self._tr("reset_defaults"),
            self._tr("reset_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._draft = Settings()
        self._rebuild()
        self._apply()

    def _choose_dir(self, edit: QLineEdit) -> None:
        start = edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, self._tr("browse"), start)
        if folder:
            edit.setText(folder)

    def _stop_fade(self) -> None:
        if self._fade_anim is not None:
            self._fade_anim.stop()
            self._fade_anim.deleteLater()
            self._fade_anim = None
        if self.graphicsEffect() is not None:
            self.setGraphicsEffect(None)  # type: ignore[arg-type]

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        self._stop_fade()
        if not self._draft.reduce_motion:
            self._fade_anim = fade_in(self, 140, False)
            if self._fade_anim is not None:
                self._fade_anim.finished.connect(
                    lambda: setattr(self, "_fade_anim", None)
                )

    def hideEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._stop_fade()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._stop_fade()
        super().closeEvent(event)

    def done(self, result: int) -> None:
        self._stop_fade()
        super().done(result)

    def reject(self) -> None:
        self._theme_manager.apply(self._settings)
        super().reject()
