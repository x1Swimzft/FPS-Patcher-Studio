"""Compact inset inspector: target FPS, output options, readiness and one progress rail."""

from __future__ import annotations

from typing import cast

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..app.queue_model import QueueItem
from ..config import Settings
from ..core.models import FPS_PRESETS, ProgressEvent
from ..core.platform_profiles import (
    PLATFORM_PROFILES,
    ReadinessReport,
    evaluate_readiness,
    get_profile,
)
from ..core.strategies import UI_PRESETS, migrate_strategy_name
from ..ui.strings import t
from .icons import get_icon
from .motion import MotionProgressBar, animate_height, fade
from .theme import UI_FONT_FAMILIES, Theme, ThemeManager
from .widgets import Card, CardGroup, Popover, SegmentedControl, text_button

CUSTOM_PRESET = "Custom"
MAX_TIMESCALE = 2_147_483_647

# Strategies whose trailing padding is marketed at PC, not mobile. Kept in sync
# with the legacy control panel warning list.
PC_PRESET_KEYS = frozenset(
    {
        "bxd-pc",
        "x1t-pc",
        "bxd-experimental",
        "x1t-experimental",
        "bxd-bypass",
        "x1t-bypass",
    }
)

_CHECK_STATUS_TOKEN = {
    "pass": "success",
    "warning": "warn",
    "error": "danger",
    "unknown": "muted",
}


class Inspector(QWidget):
    """Right-hand control column. Width and metrics come from the active theme."""

    patch_requested = Signal(int, str)
    cancel_requested = Signal()
    profile_changed = Signal()
    strategy_changed = Signal()

    def __init__(
        self,
        settings: Settings,
        theme_manager: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._theme: Theme = theme_manager.theme
        self._busy = False
        self._can_patch = False
        self._percent = 0
        self._invalid = False
        self._focused_item: QueueItem | None = None
        self._report: ReadinessReport | None = None
        self._popover: Popover | None = None
        self._progress_index = 0
        self._progress_total = 0
        self._preset = self._initial_preset()
        self._custom_visible = False
        self._custom_anim: QParallelAnimationGroup | None = None
        self._custom_fade: QPropertyAnimation | None = None
        self._glow: QGraphicsDropShadowEffect | None = None
        self._glow_anim: QVariantAnimation | None = None

        self._label_to_strategy = {s.label: s.name for s in UI_PRESETS.values()}

        self.setObjectName("Inspector")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._build()
        # Internal subscription is idempotent because set_theme only re-styles.
        theme_manager.changed.connect(self.set_theme)
        self.set_theme(self._theme)
        self._apply_preset(self._preset, persist=False)
        self._update_warn(self.strategy())
        self.refresh_readiness()
        self._sync_state()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        theme = self._theme
        lang = self._lang()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.viewport().setStyleSheet("background: transparent;")
        root.addWidget(self._scroll, 1)

        body = QWidget()
        body.setObjectName("InspectorBody")
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(
            theme.outer, theme.outer, theme.outer, theme.outer
        )
        self._body_layout.setSpacing(theme.spacing)
        self._scroll.setWidget(body)

        # -- Target FPS ----------------------------------------------------
        self.target_group = CardGroup(t("target_fps", lang), theme)
        target_content = QWidget()
        target_layout = QVBoxLayout(target_content)
        target_layout.setContentsMargins(theme.inner, theme.inner, theme.inner, theme.inner)
        target_layout.setSpacing(theme.outer)
        self._target_layout = target_layout

        self.segments = SegmentedControl(self._segment_items(), theme)
        self.segments.setAccessibleName(t("target_fps", lang))
        self.segments.valueChanged.connect(self._segment_changed)
        target_layout.addWidget(self.segments)

        self.custom_row = QWidget()
        custom_layout = QVBoxLayout(self.custom_row)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(theme.outer)
        self.custom_label = QLabel(t("timescale_lbl", lang))
        self.custom_label.setProperty("role", "caption")
        custom_layout.addWidget(self.custom_label)
        self.custom_edit = QLineEdit()
        self.custom_edit.setFixedHeight(theme.entry_height)
        self.custom_edit.setAccessibleName(t("timescale_lbl", lang))
        self.custom_edit.setPlaceholderText(t("timescale_lbl", lang))
        self.custom_edit.editingFinished.connect(self._commit_custom)
        custom_layout.addWidget(self.custom_edit)
        target_layout.addWidget(self.custom_row)
        self.custom_row.setVisible(False)
        self.custom_row.setMinimumHeight(0)
        self.custom_row.setMaximumHeight(0)

        self.target_group.body.addWidget(target_content)
        self._body_layout.addWidget(self.target_group)

        # -- Output --------------------------------------------------------
        self.output_group = CardGroup(t("output_lbl", lang), theme)

        self.timescale_field = QLineEdit()
        self.timescale_field.setReadOnly(True)
        self.timescale_field.setFixedHeight(theme.entry_height)
        self.timescale_field.setFixedWidth(112)
        self.timescale_field.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.timescale_field.setAccessibleName(t("timescale_lbl", lang))
        self.timescale_row = self.output_group.add_row(
            t("timescale_lbl", lang), self.timescale_field
        )

        self.strategy_combo = QComboBox()
        self.strategy_combo.setFixedHeight(theme.combo_height)
        self.strategy_combo.setFixedWidth(148)
        self.strategy_combo.setAccessibleName(t("strategy_lbl", lang))
        self.strategy_combo.addItems(list(self._label_to_strategy))
        resolved_key, _ = migrate_strategy_name(str(self.settings.strategy))
        resolved_preset = UI_PRESETS.get(resolved_key)
        if resolved_preset is not None:
            self.strategy_combo.setCurrentText(resolved_preset.label)
        self.strategy_combo.activated.connect(self._strategy_activated)
        self.strategy_row = self.output_group.add_row(
            t("strategy_lbl", lang), self.strategy_combo
        )

        self.profile_block = QWidget()
        profile_layout = QVBoxLayout(self.profile_block)
        profile_layout.setContentsMargins(theme.inner, theme.outer, theme.inner, theme.outer)
        profile_layout.setSpacing(theme.outer)
        self._profile_layout = profile_layout
        self.profile_label = QLabel(t("platform_profile_lbl", lang))
        self.profile_label.setProperty("role", "caption")
        profile_layout.addWidget(self.profile_label)
        self.profile_combo = QComboBox()
        self.profile_combo.setFixedHeight(theme.combo_height)
        self.profile_combo.setAccessibleName(t("platform_profile_lbl", lang))
        self.profile_combo.activated.connect(self._profile_activated)
        profile_layout.addWidget(self.profile_combo)
        self.output_group.body.addWidget(self.profile_block)
        self._populate_profiles()

        self.warn_row = QWidget()
        warn_layout = QVBoxLayout(self.warn_row)
        warn_layout.setContentsMargins(theme.inner, 0, theme.inner, theme.inner)
        self.warn_frame = QFrame()
        self.warn_frame.setObjectName("WarnCallout")
        frame_layout = QVBoxLayout(self.warn_frame)
        frame_layout.setContentsMargins(theme.inner, theme.outer, theme.inner, theme.outer)
        self._warn_layout = warn_layout
        self._warn_frame_layout = frame_layout
        self.warn_label = QLabel(t("bxd_pc_warn", lang))
        self.warn_label.setWordWrap(True)
        frame_layout.addWidget(self.warn_label)
        warn_layout.addWidget(self.warn_frame)
        self.warn_row.setVisible(False)
        self.output_group.body.addWidget(self.warn_row)
        self._body_layout.addWidget(self.output_group)

        # -- Readiness -----------------------------------------------------
        self.readiness_card = Card(theme)
        readiness_layout = QHBoxLayout()
        readiness_layout.setContentsMargins(theme.inner, theme.inner, theme.inner, theme.inner)
        readiness_layout.setSpacing(theme.outer)
        self._readiness_layout = readiness_layout
        self.readiness_label = QLabel(t("readiness_summary", lang))
        self.readiness_label.setProperty("role", "caption")
        self.readiness_label.setWordWrap(True)
        readiness_layout.addWidget(self.readiness_label, 1)
        self.info_btn = QPushButton()
        self.info_btn.setProperty("variant", "icon")
        self.info_btn.setIcon(get_icon("info", theme.is_dark))
        self.info_btn.setIconSize(QSize(14, 14))
        self.info_btn.setFixedSize(theme.icon_button_size, theme.icon_button_size)
        self.info_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.info_btn.setToolTip(t("readiness_tip", lang))
        self.info_btn.setAccessibleName(t("readiness_tip", lang))
        self.info_btn.clicked.connect(self._open_readiness)
        readiness_layout.addWidget(self.info_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.readiness_card.body.addLayout(readiness_layout)
        self._body_layout.addWidget(self.readiness_card)

        # -- One merged progress rail -------------------------------------
        self.progress_group = CardGroup(
            t("progress_idle", lang, index=0, total=0), theme
        )
        progress_content = QWidget()
        progress_layout = QVBoxLayout(progress_content)
        progress_layout.setContentsMargins(theme.inner, theme.inner, theme.inner, theme.inner)
        progress_layout.setSpacing(theme.outer)
        self._progress_layout = progress_layout
        self.percent_label = QLabel("0%")
        self.percent_label.setProperty("role", "muted")
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        progress_layout.addWidget(self.percent_label)
        self.progress_bar = MotionProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(theme.progress_height)
        self.progress_bar.setAccessibleName(t("progress_idle", lang, index=0, total=0))
        progress_layout.addWidget(self.progress_bar)
        self.progress_group.body.addWidget(progress_content)
        self._body_layout.addWidget(self.progress_group)
        self._body_layout.addStretch(1)

        # -- Pinned footer -------------------------------------------------
        footer = QWidget()
        footer.setObjectName("InspectorFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(theme.outer, theme.spacing, theme.outer, theme.outer)
        footer_layout.setSpacing(theme.spacing)
        self._footer_layout = footer_layout
        self.start_btn = text_button(
            t("start_patch", lang),
            theme,
            self._start_clicked,
            variant="primary",
            height=theme.primary_height,
        )
        self.cancel_btn = text_button(
            t("cancel_btn", lang),
            theme,
            self.cancel_requested.emit,
            variant="secondary",
            height=theme.secondary_height,
        )
        self.cancel_btn.setEnabled(False)
        footer_layout.addWidget(self.start_btn)
        footer_layout.addWidget(self.cancel_btn)
        root.addWidget(footer)

    # ------------------------------------------------------------------ theme
    def set_theme(self, theme: Theme) -> None:
        """Re-style every child from the resolved theme (also on language change)."""
        self._theme = theme
        self.setFixedWidth(theme.inspector_width)

        font = QFont()
        font.setFamilies(list(UI_FONT_FAMILIES))
        font.setPixelSize(theme.fonts.body)
        self.setFont(font)

        self.setStyleSheet(self._local_qss(theme))
        self._apply_metrics(theme)
        self.target_group.set_theme(theme)
        self.output_group.set_theme(theme)
        self.progress_group.set_theme(theme)
        self.readiness_card.set_theme(theme)
        self.segments.set_theme(theme)
        self.info_btn.setIcon(get_icon("info", theme.is_dark))
        self.progress_bar.set_theme(theme)
        reduce_motion = self._reduce_motion()
        self.segments.set_reduce_motion(reduce_motion)
        self.progress_bar.set_reduce_motion(reduce_motion)
        self._sync_custom_height()
        self._update_glow()
        self._retranslate()
        self._set_timescale_invalid(self._invalid)

    def _apply_metrics(self, theme: Theme) -> None:
        """Density can change at runtime; keep every nested margin in sync."""
        self._body_layout.setContentsMargins(
            theme.outer, theme.outer, theme.outer, theme.outer
        )
        self._body_layout.setSpacing(theme.spacing)
        self._target_layout.setContentsMargins(
            theme.inner, theme.inner, theme.inner, theme.inner
        )
        self._target_layout.setSpacing(theme.outer)
        self._profile_layout.setContentsMargins(
            theme.inner, theme.outer, theme.inner, theme.outer
        )
        self._profile_layout.setSpacing(theme.outer)
        self._warn_layout.setContentsMargins(theme.inner, 0, theme.inner, theme.inner)
        self._warn_frame_layout.setContentsMargins(
            theme.inner, theme.outer, theme.inner, theme.outer
        )
        self._readiness_layout.setContentsMargins(
            theme.inner, theme.inner, theme.inner, theme.inner
        )
        self._readiness_layout.setSpacing(theme.outer)
        self._progress_layout.setContentsMargins(
            theme.inner, theme.inner, theme.inner, theme.inner
        )
        self._progress_layout.setSpacing(theme.outer)
        self._footer_layout.setContentsMargins(
            theme.outer, theme.spacing, theme.outer, theme.outer
        )
        self._footer_layout.setSpacing(theme.spacing)

    def _local_qss(self, theme: Theme) -> str:
        c = theme.color
        body = theme.fonts.body
        caption = theme.fonts.caption
        control = theme.radii.control
        inner = theme.inner
        outer = theme.outer
        spacing = theme.spacing
        entry = theme.entry_height
        combo = theme.combo_height
        primary = theme.primary_height
        secondary = theme.secondary_height
        button = theme.button_height
        bar_radius = theme.progress_height // 2
        return f"""
QWidget#Inspector {{
    background: {c("inspector_bg")};
    border-left: 1px solid {c("border")};
}}
QWidget#InspectorFooter {{
    background: {c("inspector_bg")};
    border-top: 1px solid {c("border")};
}}
QScrollArea, QWidget#InspectorBody {{
    background: transparent;
    border: none;
}}
QWidget#Inspector QLabel {{
    background: transparent;
    color: {c("text")};
    font-size: {body}px;
}}
QWidget#Inspector QLabel[role="title"] {{
    font-size: {body + 2}px;
    font-weight: 600;
}}
QWidget#Inspector QLabel[role="caption"] {{
    color: {c("text2")};
    font-size: {caption}px;
}}
QWidget#Inspector QLabel[role="muted"] {{
    color: {c("muted")};
    font-size: {caption}px;
}}
QWidget#Inspector QLabel[role="cardCaption"] {{
    color: {c("text2")};
    font-size: {caption}px;
    font-weight: 600;
}}
QWidget#Inspector QLineEdit, QWidget#Inspector QComboBox {{
    background: {c("surface")};
    border: 1px solid {c("border")};
    border-radius: {control}px;
    color: {c("text")};
    font-size: {body}px;
    padding: 0 {inner}px;
}}
QWidget#Inspector QLineEdit {{
    min-height: {entry}px;
}}
QWidget#Inspector QComboBox {{
    min-height: {combo}px;
    padding-right: {inner + spacing}px;
}}
QWidget#Inspector QLineEdit:read-only {{
    background: {c("surface_raised")};
    color: {c("text2")};
}}
QWidget#Inspector QLineEdit:hover, QWidget#Inspector QComboBox:hover {{
    border-color: {c("border_hover")};
}}
QWidget#Inspector QLineEdit:focus, QWidget#Inspector QComboBox:focus {{
    border: 2px solid {c("border_focus")};
}}
QWidget#Inspector QComboBox::drop-down {{
    border: none;
    border-left: 1px solid {c("border")};
    width: {spacing}px;
    margin: 1px;
}}
QWidget#Inspector QComboBox QAbstractItemView {{
    background: {c("surface_raised")};
    border: 1px solid {c("border")};
    color: {c("text")};
    selection-background-color: {c("accent_dim")};
    selection-color: {c("text")};
    padding: {outer}px;
}}
QWidget#Inspector QPushButton {{
    background: {c("surface_raised")};
    border: 1px solid {c("border")};
    border-radius: {control}px;
    color: {c("text")};
    font-size: {body}px;
    min-height: {button}px;
    padding: 0 {inner}px;
}}
QWidget#Inspector QPushButton:hover {{
    background: {c("surface_hover")};
    border-color: {c("border_hover")};
}}
QWidget#Inspector QPushButton:disabled {{
    background: {c("surface_raised")};
    border-color: {c("border")};
    color: {c("muted")};
}}
QWidget#Inspector QPushButton[variant="primary"] {{
    background: {c("accent")};
    border: 1px solid {c("accent")};
    color: {c("on_accent")};
    font-weight: 600;
    min-height: {primary}px;
}}
QWidget#Inspector QPushButton[variant="primary"]:hover {{
    background: {c("accent_hover")};
    border-color: {c("accent_hover")};
}}
QWidget#Inspector QPushButton[variant="primary"]:disabled {{
    background: {c("accent_dim")};
    border-color: {c("accent_dim_border")};
    color: {c("muted")};
}}
QWidget#Inspector QPushButton[variant="secondary"] {{
    background: {c("surface")};
    min-height: {secondary}px;
}}
QWidget#Inspector QPushButton[variant="secondary"]:hover {{
    background: {c("surface_hover")};
}}
QWidget#Inspector QPushButton[variant="secondary"]:disabled {{
    background: transparent;
    border-color: transparent;
    color: {c("muted")};
}}
QWidget#Inspector QPushButton[variant="icon"] {{
    background: transparent;
    border: 1px solid transparent;
    padding: 0;
}}
QWidget#Inspector QPushButton[variant="icon"]:hover {{
    background: {c("surface_hover")};
    border-color: {c("border")};
}}
QFrame#WarnCallout {{
    background: {c("surface_raised")};
    border: 1px solid {c("warn")};
    border-radius: {control}px;
}}
QFrame#WarnCallout QLabel {{
    color: {c("warn")};
    font-size: {caption}px;
}}
QWidget#Inspector QProgressBar {{
    background: {c("surface_raised")};
    border: 1px solid {c("border")};
    border-radius: {bar_radius}px;
    max-height: {theme.progress_height}px;
    min-height: {theme.progress_height}px;
}}
QWidget#Inspector QProgressBar::chunk {{
    background: {c("accent")};
    border-radius: {bar_radius}px;
}}
"""

    def _retranslate(self) -> None:
        lang = self._lang()
        self.target_group.caption.setText(t("target_fps", lang).upper())
        self.output_group.caption.setText(t("output_lbl", lang).upper())
        self.timescale_row.label.setText(t("timescale_lbl", lang))
        self.strategy_row.label.setText(t("strategy_lbl", lang))
        self.profile_label.setText(t("platform_profile_lbl", lang))
        self.warn_label.setText(t("bxd_pc_warn", lang))
        self.readiness_label.setText(t("readiness_summary", lang))
        self.timescale_field.setAccessibleName(t("timescale_lbl", lang))
        self.custom_edit.setAccessibleName(t("timescale_lbl", lang))
        self.custom_edit.setPlaceholderText(t("timescale_lbl", lang))
        self.custom_label.setText(t("timescale_lbl", lang))
        self.strategy_combo.setAccessibleName(t("strategy_lbl", lang))
        self.profile_combo.setAccessibleName(t("platform_profile_lbl", lang))
        self.info_btn.setToolTip(t("readiness_tip", lang))
        self.info_btn.setAccessibleName(t("readiness_tip", lang))
        self.start_btn.setText(
            t("patching_btn", lang, pct=self._percent)
            if self._busy
            else t("start_patch", lang)
        )
        self.cancel_btn.setText(t("cancel_btn", lang))
        self.segments.set_items(self._segment_items(), self._preset_display(self._preset))
        self._populate_profiles()
        self._progress_caption()

    # ------------------------------------------------------------------ state
    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._sync_state()

    def set_can_patch(self, can_patch: bool) -> None:
        self._can_patch = can_patch
        self._sync_state()

    def set_progress(self, event: ProgressEvent) -> None:
        fraction = max(0.0, min(1.0, event.fraction))
        self._percent = int(round(fraction * 100))
        self._progress_index = event.file_index
        self._progress_total = event.total_files
        self.progress_bar.animate_value(self._percent)
        self.percent_label.setText(f"{self._percent}%")
        self._progress_caption()
        if self._busy:
            self.start_btn.setText(
                t("patching_btn", self._lang(), pct=self._percent)
            )

    def set_idle(self) -> None:
        self._percent = 0
        self._progress_index = 0
        self._progress_total = 0
        self.progress_bar.stop()
        self.progress_bar.setValue(0)
        self.percent_label.setText("0%")
        self._progress_caption()

    def _sync_state(self) -> None:
        lang = self._lang()
        editable = not self._busy
        self.segments.setEnabled(editable)
        self.custom_edit.setEnabled(editable)
        self.timescale_field.setEnabled(editable)
        self.strategy_combo.setEnabled(editable)
        self.profile_combo.setEnabled(editable)

        if self._busy:
            self.start_btn.setEnabled(False)
            self.start_btn.setText(t("patching_btn", lang, pct=self._percent))
            self.cancel_btn.setEnabled(True)
        else:
            self.start_btn.setEnabled(self._can_patch)
            self.start_btn.setText(t("start_patch", lang))
            self.cancel_btn.setEnabled(False)
        self.progress_bar.set_busy(self._busy)
        self._update_glow()
        self._progress_caption()

    def _progress_caption(self) -> None:
        lang = self._lang()
        if self._busy:
            text = t(
                "progress_patching",
                lang,
                index=self._progress_index,
                total=self._progress_total,
            )
        else:
            text = t("progress_idle", lang, index=0, total=0)
        self.progress_group.caption.setText(text)
        self.progress_bar.setAccessibleName(text)

    # ------------------------------------------------------------------ values
    def timescale(self) -> int | None:
        if self._preset != CUSTOM_PRESET:
            return FPS_PRESETS.get(self._preset)
        return self._parse_custom_timescale()

    def strategy(self) -> str:
        label = self.strategy_combo.currentText()
        return self._label_to_strategy.get(
            label, migrate_strategy_name(str(self.settings.strategy))[0]
        )

    def _reduce_motion(self) -> bool:
        return bool(getattr(self.settings, "reduce_motion", False))

    def set_custom_visible(self, visible: bool) -> None:
        """Show/hide the custom timescale row with a short height + fade."""
        visible = bool(visible)
        if visible == self._custom_visible:
            if visible:
                self._sync_custom_height()
            return
        self._custom_visible = visible
        self._stop_custom_animation()
        target = max(1, self.custom_row.sizeHint().height())
        if self._reduce_motion():
            self.custom_row.setMinimumHeight(target if visible else 0)
            self.custom_row.setMaximumHeight(target if visible else 0)
            self.custom_row.setVisible(visible)
        elif visible:
            self.custom_row.setMinimumHeight(0)
            self.custom_row.setMaximumHeight(0)
            self.custom_row.setVisible(True)
            self._custom_fade = fade(
                self.custom_row,
                0.0,
                1.0,
                180,
                False,
                on_finished=self._clear_custom_fade,
            )
            self._custom_anim = animate_height(
                self.custom_row, 0, target, 180, False,
                on_finished=self._show_custom_done,
            )
        else:
            start = self.custom_row.height() or target
            self._custom_fade = fade(
                self.custom_row,
                1.0,
                0.0,
                180,
                False,
                on_finished=self._clear_custom_fade,
            )
            self._custom_anim = animate_height(
                self.custom_row, start, 0, 180, False,
                on_finished=self._hide_custom_done,
            )
        if visible:
            self.custom_edit.setEnabled(not self._busy)

    def _stop_custom_animation(self) -> None:
        if self._custom_anim is not None:
            self._custom_anim.stop()
            self._custom_anim.deleteLater()
            self._custom_anim = None
        if self._custom_fade is not None:
            self._custom_fade.stop()
            self._custom_fade.deleteLater()
            self._custom_fade = None
        if isinstance(self.custom_row.graphicsEffect(), QGraphicsOpacityEffect):
            self.custom_row.setGraphicsEffect(None)  # type: ignore[arg-type]

    def _sync_custom_height(self) -> None:
        if not self._custom_visible or self._custom_anim is not None:
            return
        height = max(1, self.custom_row.sizeHint().height())
        self.custom_row.setMinimumHeight(height)
        self.custom_row.setMaximumHeight(height)

    def _clear_custom_fade(self) -> None:
        self._custom_fade = None

    def _show_custom_done(self) -> None:
        self._custom_anim = None
        self._sync_custom_height()

    def _hide_custom_done(self) -> None:
        self._custom_anim = None
        if not self._custom_visible:
            self.custom_row.setVisible(False)
            self.custom_row.setMinimumHeight(0)
            self.custom_row.setMaximumHeight(0)

    def _update_glow(self) -> None:
        active = (
            self._can_patch
            and not self._busy
            and not self._reduce_motion()
            and hasattr(self, "start_btn")
        )
        if not active:
            self._stop_glow()
            return
        if self._glow is None:
            self._glow = QGraphicsDropShadowEffect(self.start_btn)
            self._glow.setOffset(0, 0)
            self.start_btn.setGraphicsEffect(self._glow)
        if self._glow_anim is None:
            animation = QVariantAnimation(self)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            animation.setDuration(2400)
            animation.setLoopCount(-1)
            animation.setEasingCurve(QEasingCurve(QEasingCurve.Type.InOutSine))
            animation.valueChanged.connect(self._pulse_glow)
            self._glow_anim = animation
            animation.start()
        self._pulse_glow(self._glow_anim.currentValue() or 0.0)

    def _pulse_glow(self, value: object) -> None:
        if self._glow is None:
            return
        phase = float(cast(float, value))
        color = QColor(self._theme.color("accent_light"))
        color.setAlphaF(0.18 + 0.42 * phase)
        self._glow.setColor(color)
        self._glow.setBlurRadius(10.0 + 18.0 * phase)

    def _stop_glow(self) -> None:
        if self._glow_anim is not None:
            self._glow_anim.stop()
            self._glow_anim.deleteLater()
            self._glow_anim = None
        if self._glow is not None:
            self.start_btn.setGraphicsEffect(None)  # type: ignore[arg-type]
            self._glow = None

    def hideEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._stop_glow()
        self.progress_bar.stop()
        self._stop_custom_animation()
        if self._custom_visible:
            self.custom_row.setVisible(True)
            self._sync_custom_height()
        else:
            self.custom_row.setVisible(False)
            self.custom_row.setMinimumHeight(0)
            self.custom_row.setMaximumHeight(0)
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        self._update_glow()
        self.progress_bar.set_busy(self._busy)

    def set_focused_item(self, item: QueueItem | None) -> None:
        key = None if item is None else (item.item_id, id(item.info))
        current = (
            None
            if self._focused_item is None
            else (self._focused_item.item_id, id(self._focused_item.info))
        )
        if key == current:
            return
        self._focused_item = item
        self.refresh_readiness()

    def refresh_readiness(self) -> None:
        lang = self._lang()
        self._report = None
        if self._focused_item is not None:
            self._report = evaluate_readiness(
                self._focused_item.info, self.settings.platform_profile
            )
        self.readiness_label.setText(t("readiness_summary", lang))
        self.info_btn.setToolTip(t("readiness_tip", lang))
        self.info_btn.setAccessibleName(t("readiness_tip", lang))

    # ------------------------------------------------------------------ internals
    def _lang(self) -> str:
        return getattr(self.settings, "language", "en")

    def _initial_preset(self) -> str:
        value = str(getattr(self.settings, "last_preset", "60 FPS"))
        return value if value in (*FPS_PRESETS, CUSTOM_PRESET) else "60 FPS"

    def _segment_items(self) -> list[str]:
        return [*FPS_PRESETS, t("custom", self._lang())]

    def _preset_display(self, preset: str) -> str:
        return preset if preset in FPS_PRESETS else t("custom", self._lang())

    def _segment_changed(self, value: str) -> None:
        preset = CUSTOM_PRESET if value == t("custom", self._lang()) else value
        self._apply_preset(preset, persist=True)

    def _apply_preset(self, preset: str, *, persist: bool) -> None:
        self._preset = preset
        is_custom = preset == CUSTOM_PRESET
        self.segments.set_items(self._segment_items(), self._preset_display(preset))
        self.set_custom_visible(is_custom)
        self._set_timescale_invalid(False)
        if is_custom:
            self.custom_edit.setText(str(self.settings.custom_timescale))
        self._update_timescale_display()
        if persist:
            self.settings.last_preset = preset
            self.settings.save_async()

    def _commit_custom(self) -> None:
        if self._preset != CUSTOM_PRESET:
            return
        value = self._parse_custom_timescale()
        if value is None:
            return
        self.settings.custom_timescale = value
        self.settings.last_preset = CUSTOM_PRESET
        self.settings.save_async()
        self._set_timescale_invalid(False)
        self._update_timescale_display()

    def _parse_custom_timescale(self) -> int | None:
        try:
            value = int(self.custom_edit.text().strip())
        except ValueError:
            return None
        return value if 1 <= value <= MAX_TIMESCALE else None

    def _update_timescale_display(self) -> None:
        value = self.timescale()
        self.timescale_field.setText("" if value is None else str(value))

    def _set_timescale_invalid(self, invalid: bool) -> None:
        self._invalid = invalid
        if invalid:
            color = self._theme.color("danger")
            self.custom_edit.setStyleSheet(
                f"QLineEdit {{ border: 1px solid {color}; }}"
            )
        else:
            self.custom_edit.setStyleSheet("")

    def _start_clicked(self) -> None:
        value = self.timescale()
        if value is None:
            self._set_timescale_invalid(True)
            if self._preset == CUSTOM_PRESET:
                self.custom_edit.setFocus()
            return
        self._set_timescale_invalid(False)
        if self._preset == CUSTOM_PRESET:
            self.settings.custom_timescale = value
        strategy = self.strategy()
        self.settings.last_preset = self._preset
        self.settings.strategy = strategy
        self.settings.save_async()
        self._update_timescale_display()
        self.patch_requested.emit(value, strategy)

    def _strategy_activated(self, index: int) -> None:
        if index < 0:
            return
        key = self._label_to_strategy.get(self.strategy_combo.itemText(index))
        if key is None:
            return
        self.settings.strategy = key
        self.settings.save_async()
        self._update_warn(key)
        self.strategy_changed.emit()

    def _update_warn(self, strategy_key: str) -> None:
        self.warn_row.setVisible(strategy_key in PC_PRESET_KEYS)

    def _populate_profiles(self) -> None:
        lang = self._lang()
        labels = {
            t(profile.label_key, lang): profile.profile_id
            for profile in PLATFORM_PROFILES.values()
        }
        current_id = get_profile(self.settings.platform_profile).profile_id
        current = next(
            (label for label, profile_id in labels.items() if profile_id == current_id),
            next(iter(labels)),
        )
        self._profile_labels = labels
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for label in labels:
            self.profile_combo.addItem(label)
            self.profile_combo.setItemData(
                self.profile_combo.count() - 1, label, Qt.ItemDataRole.ToolTipRole
            )
        self.profile_combo.setCurrentText(current)
        self.profile_combo.blockSignals(False)

    def _profile_activated(self, index: int) -> None:
        if index < 0:
            return
        profile_id = self._profile_labels.get(self.profile_combo.itemText(index))
        if profile_id is None:
            return
        self.settings.platform_profile = profile_id
        self.settings.save_async()
        self.refresh_readiness()
        self.profile_changed.emit()

    # ------------------------------------------------------------------ popover
    def _open_readiness(self) -> None:
        if self._popover is not None:
            self._popover.close()
            self._popover.deleteLater()
            self._popover = None

        theme = self._theme
        lang = self._lang()
        pop = Popover(theme)
        pop.setFixedWidth(340)
        pop.setStyleSheet(
            pop.styleSheet()
            + f"""
QLabel {{ color: {theme.color("text")}; font-size: {theme.fonts.body}px; }}
QLabel[role="title"] {{ font-size: {theme.fonts.body + 2}px; font-weight: 600; }}
QLabel[role="muted"] {{ color: {theme.color("muted")}; font-size: {theme.fonts.caption}px; }}
QLabel[role="caption"] {{ color: {theme.color("text2")}; font-size: {theme.fonts.caption}px; }}
QScrollArea, QWidget#PopoverBody {{ background: transparent; border: none; }}
"""
        )
        title = QLabel(t("readiness_info_title", lang))
        title.setProperty("role", "title")
        pop.body.addWidget(title)

        disclaimer = QLabel(t("readiness_disclaimer", lang))
        disclaimer.setProperty("role", "muted")
        disclaimer.setWordWrap(True)
        pop.body.addWidget(disclaimer)

        content = QWidget()
        content.setObjectName("PopoverBody")
        content.setFixedWidth(310)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(theme.outer)
        report = self._report
        if report is None:
            empty = QLabel(t("no_selection", lang))
            empty.setProperty("role", "muted")
            empty.setWordWrap(True)
            content_layout.addWidget(empty)
        else:
            profile = get_profile(self.settings.platform_profile)
            badge = QLabel(
                t(
                    "readiness_badge",
                    lang,
                    profile=t(profile.label_key, lang),
                    status=t(f"readiness_{report.status}", lang),
                    score=report.score,
                )
            )
            badge.setProperty("role", "caption")
            badge.setWordWrap(True)
            content_layout.addWidget(badge)
            for check in report.checks:
                status = t(f"check_status_{check.status}", lang)
                color = theme.color(_CHECK_STATUS_TOKEN.get(check.status, "muted"))
                line = QLabel(f"{check.label} — {status}")
                line.setStyleSheet(f"color: {color}; font-weight: 600;")
                line.setWordWrap(True)
                content_layout.addWidget(line)
                detail = QLabel(check.detail)
                detail.setProperty("role", "muted")
                detail.setWordWrap(True)
                content_layout.addWidget(detail)
                if check.recommendation:
                    recommendation = QLabel(check.recommendation)
                    recommendation.setStyleSheet(
                        f"color: {theme.color('accent')}; font-size: "
                        f"{theme.fonts.caption}px;"
                    )
                    recommendation.setWordWrap(True)
                    content_layout.addWidget(recommendation)
        content_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        content.adjustSize()
        height = min(max(120, content.sizeHint().height()), 380)
        scroll.setFixedHeight(height)
        pop.body.addWidget(scroll)

        pop.show_for(self.info_btn)
        self._popover = pop

    # Alias for callers that use the qss.apply_theme wording.
    apply_theme = set_theme
