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

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
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
from .motion import fade_in
from .qss import build_qss
from .theme import Theme, ThemeManager
from .widgets import Card, SegmentedControl, Switch, set_prop, text_button

SWATCHES = ["#3B82F6", "#8B5CF6", "#10B981", "#F43F5E", "#F59E0B", "#06B6D4", "#EC4899"]
CUSTOM_PRESET = "Custom"

# Local structural rules only; every colour and metric still comes from build_qss.
_SCROLL_QSS = """
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QStackedWidget { background: transparent; }
"""


class _WidgetTheme:
    """Adapter for widgets.py's old ``*_radius`` names until that module catches up."""

    # shortcut: widgets.py still asks for *_radius; remove when it uses card/control.

    def __init__(self, theme: Theme) -> None:
        self._theme = theme

    def __getattr__(self, name: str) -> Any:
        if name == "card_radius":
            return self._theme.card
        if name == "control_radius":
            return self._theme.control
        return getattr(self._theme, name)


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
        self._pages: list[tuple[str, QPushButton, QWidget]] = []
        self._page_layouts: list[QVBoxLayout] = []
        self._themed_widgets: list[Any] = []
        self._swatches: list[tuple[QPushButton, str]] = []
        self._ff_status: QLabel | None = None
        self._ff_status_token = "muted"
        self._fade_anim = None

        self.setObjectName("SettingsDialog")
        self.setWindowTitle(self._title())
        self.resize(740, 580)
        self.setMinimumSize(700, 520)
        self.setSizeGripEnabled(True)
        self.setModal(True)

        self._root = QVBoxLayout(self)
        self._build_ui()
        self._theme_manager.changed.connect(self._refresh_theme)

    # ------------------------------------------------------------------ text
    def _tr(self, key: str, **kwargs: object) -> str:
        return t(key, self._draft.language, **kwargs)

    def _title(self) -> str:
        return f"{self._tr('settings_btn')} — {self._tr('app_title')}"

    # -------------------------------------------------------------- assembly
    def _build_ui(self) -> None:
        theme = self._theme_manager.theme
        self.setWindowTitle(self._title())
        self.setStyleSheet(build_qss(theme) + _SCROLL_QSS)
        self._themed_widgets = []
        self._swatches = []
        self._page_layouts = []
        self._pages = []
        self._nav_buttons = {}
        self._ff_status = None

        self._root.setContentsMargins(theme.inner, theme.inner, theme.inner, theme.inner)
        self._root.setSpacing(theme.outer)

        body_row = QHBoxLayout()
        body_row.setSpacing(theme.outer)
        body_row.addWidget(self._build_rail(theme))
        body_row.addWidget(self._build_body(theme), 1)
        self._root.addLayout(body_row, 1)
        self._root.addLayout(self._build_footer(theme))
        self._select_tab("appearance")

    def _build_rail(self, theme: Theme) -> Card:
        rail = Card(_WidgetTheme(theme))
        rail.setObjectName("SettingsRail")
        rail.setFixedWidth(theme.icon_button_size * 7)
        self._themed_widgets.append(rail)
        layout = QVBoxLayout()
        layout.setContentsMargins(theme.inner, theme.inner, theme.inner, theme.inner)
        layout.setSpacing(theme.outer)
        rail.body.addLayout(layout)

        title = QLabel(self._tr("settings_btn"))
        title.setProperty("role", "title")
        title.setWordWrap(True)
        layout.addWidget(title)

        for key, label_key in self._TABS:
            button = QPushButton(self._tr(label_key))
            button.setProperty("variant", "ghost")
            button.setStyleSheet("text-align: left;")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.setAccessibleName(button.text())
            button.clicked.connect(lambda _checked=False, k=key: self._select_tab(k))
            layout.addWidget(button)
            self._nav_buttons[key] = button
        layout.addStretch(1)
        return rail

    def _build_body(self, theme: Theme) -> Card:
        body = Card(_WidgetTheme(theme))
        body.setObjectName("SettingsBody")
        body.body.setContentsMargins(theme.inner, theme.inner, theme.inner, theme.inner)
        self._themed_widgets.append(body)
        self._stack = QStackedWidget()
        self._stack.setObjectName("SettingsStack")
        body.body.addWidget(self._stack)

        self._build_appearance()
        self._build_output()
        self._build_patching()
        self._build_ffmpeg()
        self._build_console()
        self._build_behavior()
        self._build_about()
        return body

    def _build_footer(self, theme: Theme) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setSpacing(theme.spacing)
        reset = text_button(self._tr("reset_defaults"), theme, self._reset_all, variant="ghost")
        footer.addWidget(reset)
        footer.addStretch(1)
        footer.addWidget(text_button(self._tr("apply"), theme, self._apply, variant="secondary"))
        footer.addWidget(text_button(self._tr("ok"), theme, self._ok, variant="primary"))
        footer.addWidget(text_button(self._tr("cancel"), theme, self.reject, variant="secondary"))
        return footer

    def _new_page(self, key: str) -> tuple[QWidget, QVBoxLayout]:
        theme = self._theme_manager.theme
        scroll = QScrollArea()
        scroll.setObjectName(f"SettingsTab_{key}")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        page.setObjectName(f"SettingsPage_{key}")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(theme.inner, theme.inner, theme.inner, theme.inner)
        layout.setSpacing(theme.spacing)
        scroll.setWidget(page)
        self._stack.addWidget(scroll)
        self._page_layouts.append(layout)
        self._pages.append((key, self._nav_buttons[key], scroll))
        return page, layout

    # ------------------------------------------------------- shared controls
    def _section(self, layout: QVBoxLayout, key: str) -> QLabel:
        theme = self._theme_manager.theme
        if layout.count():
            layout.addSpacing(theme.outer)
        label = QLabel(self._tr(key))
        label.setProperty("role", "title")
        label.setWordWrap(True)
        layout.addWidget(label)
        return label

    def _hint(self, layout: QVBoxLayout, key: str) -> QLabel:
        label = QLabel(self._tr(key))
        label.setProperty("role", "caption")
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(label)
        return label

    def _field_label(self, layout: QVBoxLayout, key: str) -> QLabel:
        label = QLabel(self._tr(key))
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
        control = SegmentedControl(items, _WidgetTheme(theme))
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
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        switch = Switch(_WidgetTheme(theme))
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
        _page, layout = self._new_page("appearance")
        draft = self._draft

        self._preset = self._combo(
            layout, "theme_preset", THEME_PRESETS, draft.theme_preset, self._on_preset
        )

        self._appearance_labels = [self._tr("mode_dark"), self._tr("mode_light")]
        current_mode = self._appearance_labels[1 if draft.appearance == "light" else 0]
        self._appearance = self._segmented(
            layout,
            "appearance_mode",
            self._appearance_labels,
            current_mode,
            self._on_appearance,
        )

        self._field_label(layout, "custom_accent")
        self._accent = QLineEdit(draft.custom_accent)
        self._accent.setPlaceholderText("#RRGGBB")
        self._accent.setAccessibleName(self._tr("custom_accent"))
        self._accent.textChanged.connect(self._on_accent)
        layout.addWidget(self._accent)

        swatch_label = QLabel(self._tr("accent_swatches"))
        swatch_label.setProperty("role", "caption")
        layout.addWidget(swatch_label)
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
        layout.addLayout(swatch_row)

        self._glass = self._switch(layout, "glass_effect", draft.glass)
        self._backdrop = self._combo(
            layout,
            "glass_mode",
            BACKDROP_MODES,
            draft.glass_mode,
            lambda value: setattr(self._draft, "glass_mode", value),
        )
        self._tint = self._slider(layout, "tint_strength", draft.tint_strength, 0, 100)
        self._alpha = self._slider(layout, "window_alpha", round(draft.window_alpha * 100), 85, 100)
        self._radius = self._segmented(
            layout,
            "radius_style",
            RADIUS_STYLES,
            draft.radius_style,
            lambda value: self._set_and_preview("radius_style", value),
        )
        self._reduce_motion = self._switch(layout, "reduce_motion", draft.reduce_motion)
        self._font_size = self._combo(
            layout, "font_size", FONT_SIZES, draft.font_size, self._on_font_size
        )
        self._ui_scale = self._spin(layout, "ui_scale", draft.ui_scale, 50, 200, 5, "%")
        self._density_labels = [self._tr("density_compact"), self._tr("density_comfortable")]
        current_density = (
            self._density_labels[1]
            if draft.layout_density == "Comfortable"
            else self._density_labels[0]
        )
        self._density = self._segmented(
            layout,
            "layout_density",
            self._density_labels,
            current_density,
            self._on_density,
        )
        layout.addStretch(1)

    def _on_preset(self, value: str) -> None:
        self._draft.theme_preset = value
        with QSignalBlocker(self._accent):
            self._accent.clear()
        self._draft.custom_accent = ""
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
        _page, layout = self._new_page("output")
        draft = self._draft
        self._out_dir = self._path_row(
            layout,
            "default_output_dir",
            draft.output_dir,
            hint_key="leave_empty_source",
            reset=True,
        )
        self._template = self._entry(layout, "filename_template", draft.filename_template)
        self._hint(layout, "template_help")
        self._template_preview = QLabel()
        self._template_preview.setProperty("role", "caption")
        self._template_preview.setWordWrap(True)
        layout.addWidget(self._template_preview)
        self._template.textChanged.connect(self._update_template_preview)
        self._update_template_preview()

        self._open_done = self._switch(layout, "open_when_done", draft.open_when_done)
        self._preserve_mtime = self._switch(layout, "preserve_mtime", draft.preserve_mtime)

        self._section(layout, "watch_folder_section")
        self._hint(layout, "watch_folder_hint")
        self._watch_enabled = self._switch(
            layout, "watch_folder_enable", draft.watch_folder_enabled
        )
        self._watch_dir = self._path_row(layout, "watch_folder_dir", draft.watch_folder)
        self._explorer_menu = self._switch(layout, "explorer_menu_enable", draft.explorer_menu)
        layout.addStretch(1)

    def _update_template_preview(self, _value: str = "") -> None:
        template = self._template.text().strip() or "{name}_{fps}fps"
        rendered = render_filename_template(template, "sample_clip", 60)
        self._template_preview.setText(self._tr("template_preview", preview=f"{rendered}.mp4"))

    # -------------------------------------------------------------- patching
    def _build_patching(self) -> None:
        _page, layout = self._new_page("patching")
        draft = self._draft
        self._custom_fps = self._tr("custom")
        fps_items = [*FPS_PRESETS, self._custom_fps]
        if draft.last_preset == CUSTOM_PRESET:
            current_fps = self._custom_fps
        elif draft.last_preset in fps_items:
            current_fps = draft.last_preset
        else:
            current_fps = self._first_fps(fps_items)
        self._fps_preset = self._combo(
            layout,
            "default_target_preset",
            fps_items,
            current_fps,
            self._on_fps_preset,
        )
        self._timescale = self._spin(
            layout, "default_timescale", draft.custom_timescale, 1, 2_000_000_000
        )
        self._timescale.setEnabled(current_fps == self._custom_fps)

        strategy_labels = [preset.label for preset in UI_PRESETS.values()]
        self._strategy_label_to_key = {preset.label: preset.name for preset in UI_PRESETS.values()}
        resolved, _old = migrate_strategy_name(draft.strategy)
        current_strategy = UI_PRESETS.get(resolved)
        self._strategy = self._combo(
            layout,
            "default_strategy",
            strategy_labels,
            current_strategy.label if current_strategy else strategy_labels[0],
            lambda _value: None,
        )

        self._padding = self._spin(
            layout, "bxd_padding_lbl", draft.bxd_padding_bytes, 0, MAX_BXD_PADDING_BYTES, 1024
        )
        self._tail_ms = self._spin(layout, "bxd_tail_ms_lbl", draft.bxd_max_tail_ms, 0, 5000)
        self._mask_paths = self._switch(layout, "mask_paths_lbl", draft.mask_diagnostic_paths)

        self._section(layout, "v4_options")
        self._v4_strict = self._switch(layout, "v4_strict", draft.v4_strict_lossless)
        self._v4_video = self._switch(layout, "v4_preserve_video", draft.v4_preserve_video)
        self._v4_audio = self._switch(layout, "v4_preserve_audio", draft.v4_preserve_audio)
        self._v4_sync = self._switch(layout, "v4_sync_mvhd", draft.v4_sync_mvhd)
        self._v4_report = self._switch(layout, "v4_export_report", draft.v4_export_report)
        self._v4_dry_run = self._switch(layout, "v4_dry_run", draft.v4_dry_run)

        self._verify = self._switch(layout, "verify_after", draft.verify_after)
        self._backup = self._switch(layout, "backup_original", draft.backup_original)
        self._stop_on_error = self._switch(layout, "stop_on_error", draft.stop_on_error)

        self._section(layout, "preflight_section")
        self._normalize_audio = self._switch(
            layout, "auto_normalize_audio", draft.auto_normalize_audio
        )
        self._cap_bitrate = self._switch(layout, "auto_cap_bitrate", draft.auto_cap_bitrate)

        self._section(layout, "color_metadata_section")
        self._fix_color = self._switch(layout, "fix_color_tag", draft.fix_color_tag)
        self._scrub_metadata = self._switch(layout, "scrub_metadata", draft.scrub_metadata)
        layout.addStretch(1)

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
        _page, layout = self._new_page("ffmpeg")
        draft = self._draft

        label = self._field_label(layout, "ffmpeg_dir")
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
        layout.addLayout(row)

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
        layout.addLayout(test_row)

        download = text_button(
            self._tr("ffmpeg_auto_download_btn"),
            theme,
            self.download_requested.emit,
            variant="secondary",
        )
        layout.addWidget(download)

        self._check_ffmpeg = self._switch(layout, "check_on_start", draft.check_ffmpeg_on_start)
        self._show_ffmpeg = self._switch(layout, "show_output_console", draft.show_ffmpeg_output)

        self._section(layout, "extra_args")
        self._hint(layout, "extra_args_warn")
        self._extra_args = self._entry(layout, "extra_args", draft.extra_ffmpeg_args)
        layout.addStretch(1)

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
        _page, layout = self._new_page("console")
        draft = self._draft
        self._console_font = self._spin(layout, "console_font_size", draft.console_font_size, 8, 24)
        self._max_log_lines = self._spin(
            layout, "max_log_lines", draft.max_log_lines, 100, 20000, 100
        )
        self._log_timestamps = self._switch(layout, "log_timestamps", draft.log_timestamps)
        self._log_autoscroll = self._switch(layout, "log_autoscroll", draft.log_autoscroll)
        self._log_to_file = self._switch(layout, "log_to_file", draft.log_to_file)
        layout.addStretch(1)

    # -------------------------------------------------------------- behavior
    def _build_behavior(self) -> None:
        _page, layout = self._new_page("behavior")
        draft = self._draft
        self._remember_geometry = self._switch(layout, "remember_geometry", draft.remember_geometry)
        self._always_on_top = self._switch(layout, "always_on_top", draft.always_on_top)
        self._confirm_cancel = self._switch(layout, "confirm_cancel", draft.confirm_cancel)
        self._confirm_overwrite = self._switch(layout, "confirm_overwrite", draft.confirm_overwrite)

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
            layout,
            "notify_done",
            self._notify_labels,
            current_notify,
            lambda _value: None,
        )

        self._language_labels = ["English (en)", "ไทย (th)"]
        self._language = self._combo(
            layout,
            "language_choice",
            self._language_labels,
            self._language_labels[1 if draft.language == "th" else 0],
            self._on_language,
        )
        self._check_updates = self._switch(
            layout, "check_updates_on_start", draft.check_updates_on_start
        )
        layout.addStretch(1)

    def _on_language(self, value: str) -> None:
        self._draft.language = "th" if "th" in value else "en"
        self._harvest()
        self._rebuild()

    # ----------------------------------------------------------------- about
    def _build_about(self) -> None:
        theme = self._theme_manager.theme
        _page, layout = self._new_page("about")

        version = QLabel(self._tr("app_info", version=__version__))
        version.setProperty("role", "title")
        version.setWordWrap(True)
        layout.addWidget(version)
        self._hint(layout, "about_desc")

        copy = text_button(self._tr("copy_diagnostics"), theme, self._copy_diagnostics)
        export = text_button(self._tr("export_settings"), theme, self._export_settings)
        import_btn = text_button(self._tr("import_settings"), theme, self._import_settings)
        reset = text_button(self._tr("reset_defaults"), theme, self._reset_all, variant="secondary")
        for button in (copy, export, import_btn, reset):
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            layout.addWidget(button)

        self._hint(layout, "restart_hint")
        layout.addStretch(1)

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

    # ---------------------------------------------------------------- actions
    def _current_tab_key(self) -> str | None:
        if not self._pages:
            return None
        index = self._stack.currentIndex()
        if 0 <= index < len(self._pages):
            return self._pages[index][0]
        return None

    def _select_tab(self, key: str) -> None:
        for index, (page_key, _button, _page) in enumerate(self._pages):
            if page_key == key:
                self._stack.setCurrentIndex(index)
                break
        for page_key, button, _page in self._pages:
            set_prop(button, "variant", "secondary" if page_key == key else "ghost")

    def _refresh_theme(self, theme: Theme) -> None:
        self.setStyleSheet(build_qss(theme) + _SCROLL_QSS)
        for widget in self._themed_widgets:
            with contextlib.suppress(Exception):
                widget.set_theme(_WidgetTheme(theme))
        for button, color in self._swatches:
            self._style_swatch(button, color)
        self._root.setContentsMargins(theme.inner, theme.inner, theme.inner, theme.inner)
        self._root.setSpacing(theme.outer)
        for layout in self._page_layouts:
            layout.setContentsMargins(theme.inner, theme.inner, theme.inner, theme.inner)
            layout.setSpacing(theme.spacing)
        self._select_tab(self._current_tab_key() or "appearance")
        if self._ff_status is not None:
            self._set_ff_status(self._ff_status.text(), self._ff_status_token)

    def _rebuild(self) -> None:
        tab = self._current_tab_key()
        self._clear_layout(self._root)
        self._build_ui()
        if tab:
            self._select_tab(tab)

    def _clear_layout(self, layout: QLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
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
            self.setGraphicsEffect(None)

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
