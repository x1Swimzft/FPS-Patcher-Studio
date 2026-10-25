"""Model/view file queue with a native drag-and-drop empty state.

``controller.items`` (``InputQueue``) stays the single source of truth: the Qt
model only snapshots item *references* and resets when the queue changes.
Rows are painted by one delegate, so a 500-file queue stays cheap.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QEasingCurve,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QUrl,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetricsF,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListView,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..app.queue_model import QueueItem
from ..core.models import FPS_PRESETS, SUPPORTED_EXTENSIONS
from ..core.platform_profiles import ReadinessReport, evaluate_readiness
from ..core.strategies import UI_PRESETS, migrate_strategy_name
from ..ui.strings import t
from .icons import get_icon
from .motion import animate
from .theme import UI_FONT_FAMILIES, Theme
from .thumbnails import THUMBNAIL_SIZE, ThumbnailLoader
from .widgets import ElidedLabel, Switch, hairline, text_button

if TYPE_CHECKING:
    from ..app.controller import AppController
    from ..config import Settings
    from .theme import ThemeManager

ROW_HEIGHT = 56
_INVALID_INDEX = QModelIndex()
_MAX_THUMBS = 240
_ACTION_SIZE = 28.0


def _fps_text(value: float) -> str:
    if value <= 0:
        return "—"
    rounded = round(value)
    if abs(value - rounded) < 0.05:
        return str(rounded)
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _format_size(size: int | None) -> str:
    if not size or size <= 0:
        return "—"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _format_duration(seconds: float) -> str:
    total = int(round(seconds or 0))
    if total <= 0:
        return "00:00"
    mins, secs = divmod(total, 60)
    hrs, mins = divmod(mins, 60)
    return f"{hrs:d}:{mins:02d}:{secs:02d}" if hrs else f"{mins:02d}:{secs:02d}"


def _blend_color(start: QColor, end: QColor, phase: float) -> QColor:
    phase = max(0.0, min(1.0, phase))
    return QColor(
        round(start.red() + (end.red() - start.red()) * phase),
        round(start.green() + (end.green() - start.green()) * phase),
        round(start.blue() + (end.blue() - start.blue()) * phase),
    )


def _format_meta(item: QueueItem) -> str:
    info = item.info
    if info is None:
        return "—"
    parts: list[str] = []
    if info.width and info.height:
        parts.append(f"{info.width}×{info.height}")
    if info.duration_s:
        parts.append(_format_duration(info.duration_s))
    if info.fps:
        fps = f"{info.fps:.2f}".rstrip("0").rstrip(".")
        parts.append(f"{fps} fps")
    return " · ".join(parts) if parts else "—"


class DropCard(QWidget):
    """Dashed rounded drop target. Package 7 animates ``breath_phase``."""

    browse_requested = Signal()
    folder_requested = Signal()

    def __init__(
        self,
        theme: Theme,
        language: str = "en",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._language = language
        self._drag_active = False
        self._breath_phase = 0.0
        self._scale = 1.0
        self._bob = 0.0
        self._profile: tuple[str, str, str] = ("—", "—", "—")
        self.reduce_motion = False
        self._breath_anim: QPropertyAnimation | None = None
        self._bob_anim: QPropertyAnimation | None = None
        self._scale_anim: QPropertyAnimation | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.inner, theme.inner, theme.inner, theme.inner)
        layout.setSpacing(theme.outer)
        layout.addStretch(1)

        self.center_card = QFrame(self)
        self.center_card.setObjectName("DropCenterCard")
        self.center_card.setFixedWidth(400)
        self._card_layout = QVBoxLayout(self.center_card)
        self._card_layout.setContentsMargins(
            theme.outer, theme.outer, theme.outer, theme.outer
        )
        self._card_layout.setSpacing(theme.outer)
        layout.addWidget(self.center_card, 0, Qt.AlignmentFlag.AlignHCenter)

        self.icon_holder = QWidget(self.center_card)
        self.icon_holder.setFixedSize(40, 44)
        self.icon_label = QLabel(self.icon_holder)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setFixedSize(40, 40)
        self._card_layout.addWidget(self.icon_holder, 0, Qt.AlignmentFlag.AlignHCenter)

        self.title_label = QLabel()
        self.title_label.setProperty("role", "title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._card_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel()
        self.subtitle_label.setProperty("role", "caption")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._card_layout.addWidget(self.subtitle_label)

        buttons = QWidget(self.center_card)
        button_row = QHBoxLayout(buttons)
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(theme.outer)
        self.browse_button = text_button(
            t("add_files_btn", language), theme, self.browse_requested.emit, variant="primary"
        )
        self.browse_button.setMinimumWidth(128)
        self.folder_button = text_button(
            t("add_folder_btn", language),
            theme,
            self.folder_requested.emit,
            variant="secondary",
        )
        self.folder_button.setMinimumWidth(128)
        button_row.addStretch(1)
        button_row.addWidget(self.browse_button)
        button_row.addWidget(self.folder_button)
        button_row.addStretch(1)
        self._card_layout.addWidget(buttons)

        self.format_labels: dict[str, QLabel] = {}
        formats = QWidget(self.center_card)
        format_row = QHBoxLayout(formats)
        format_row.setContentsMargins(0, 0, 0, 0)
        format_row.setSpacing(theme.outer)
        format_row.addStretch(1)
        for key in ("mp4", "mov", "m4v"):
            label = QLabel()
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setFixedHeight(20)
            self.format_labels[key] = label
            format_row.addWidget(label)
        format_row.addStretch(1)
        self._card_layout.addWidget(formats)

        self.profile_strip = QFrame(self.center_card)
        self.profile_strip.setObjectName("DropProfileStrip")
        profile_layout = QVBoxLayout(self.profile_strip)
        profile_layout.setContentsMargins(theme.inner, theme.outer, theme.inner, theme.outer)
        profile_layout.setSpacing(2)
        self._profile_layout = profile_layout
        self.profile_title = QLabel()
        self.profile_title.setProperty("role", "cardCaption")
        profile_layout.addWidget(self.profile_title)
        self.profile_summary = ElidedLabel()
        self.profile_summary.setProperty("role", "caption")
        self.profile_summary.setFixedHeight(16)
        profile_layout.addWidget(self.profile_summary)
        self._card_layout.addWidget(self.profile_strip)

        layout.addStretch(1)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_theme(theme)

    @Property(bool)
    def dragActive(self) -> bool:  # noqa: N802 - Qt property name
        return self._drag_active

    @dragActive.setter  # type: ignore[no-redef]
    def dragActive(self, active: bool) -> None:  # noqa: N802 - Qt property name
        self.set_drag_active(active)

    @Property(float)
    def breath_phase(self) -> float:  # noqa: N802 - Qt property name
        return self._breath_phase

    @breath_phase.setter  # type: ignore[no-redef]
    def breath_phase(self, value: float) -> None:  # noqa: N802 - Qt property name
        self._breath_phase = float(value)
        self.update()

    @Property(float)
    def scale(self) -> float:  # noqa: N802 - Qt property name
        return self._scale

    @scale.setter  # type: ignore[no-redef]
    def scale(self, value: float) -> None:  # noqa: N802 - Qt property name
        self._scale = float(value)
        self.update()

    @Property(float)
    def bob(self) -> float:  # noqa: N802 - Qt property name
        return self._bob

    @bob.setter  # type: ignore[no-redef]
    def bob(self, value: float) -> None:  # noqa: N802 - Qt property name
        self._bob = float(value)
        self._place_icon()

    def set_reduce_motion(self, enabled: bool) -> None:
        self.reduce_motion = bool(enabled)
        if self.reduce_motion:
            self.set_breathing(False)
            self._scale = 1.0
            self.update()

    def set_breathing(self, active: bool) -> None:
        should_run = bool(active) and not self.reduce_motion
        if not should_run:
            self._stop_animations()
            self._breath_phase = 0.0
            self._bob = 0.0
            self._place_icon()
            self.update()
            return
        if (
            self._breath_anim is not None
            and self._breath_anim.state() == QPropertyAnimation.State.Running
        ):
            return
        breathing = QPropertyAnimation(self, b"breath_phase", self)
        breathing.setDuration(3200)
        breathing.setLoopCount(-1)
        breathing.setEasingCurve(QEasingCurve(QEasingCurve.Type.InOutSine))
        breathing.setKeyValueAt(0.0, 0.0)
        breathing.setKeyValueAt(0.5, 1.0)
        breathing.setKeyValueAt(1.0, 0.0)
        self._breath_anim = breathing
        breathing.start()

        bobbing = QPropertyAnimation(self, b"bob", self)
        bobbing.setDuration(2600)
        bobbing.setLoopCount(-1)
        bobbing.setEasingCurve(QEasingCurve(QEasingCurve.Type.InOutSine))
        bobbing.setKeyValueAt(0.0, -3.0)
        bobbing.setKeyValueAt(0.5, 3.0)
        bobbing.setKeyValueAt(1.0, -3.0)
        self._bob_anim = bobbing
        bobbing.start()

    def _stop_animations(self) -> None:
        for animation in (self._breath_anim, self._bob_anim):
            if animation is not None:
                animation.stop()
                animation.deleteLater()
        self._breath_anim = None
        self._bob_anim = None

    def _place_icon(self) -> None:
        if not hasattr(self, "icon_label"):
            return
        x = (self.icon_holder.width() - self.icon_label.width()) // 2
        y = (self.icon_holder.height() - self.icon_label.height()) // 2 + int(self._bob)
        self.icon_label.move(max(0, x), max(0, y))

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._place_icon()

    def hideEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.set_breathing(False)
        super().hideEvent(event)

    def set_drag_active(self, active: bool) -> None:
        if active == self._drag_active:
            return
        self._drag_active = active
        if self._scale_anim is not None:
            self._scale_anim.stop()
            self._scale_anim.deleteLater()
        self._scale_anim = animate(
            self, b"scale", self._scale, 1.01 if active else 1.0, 140
        )
        self._refresh_text()
        self._refresh_icon()
        self.update()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._card_layout.setContentsMargins(
            theme.outer, theme.outer, theme.outer, theme.outer
        )
        self._card_layout.setSpacing(theme.outer)
        self._profile_layout.setContentsMargins(
            theme.inner, theme.outer, theme.inner, theme.outer
        )
        self.folder_button.setIcon(get_icon("folder", theme.is_dark))
        self.folder_button.setIconSize(QSize(14, 14))
        self._refresh_text()
        self._refresh_icon()
        self._refresh_style()
        self.update()

    def set_profile(self, fps: str, mode: str, output: str) -> None:
        self._profile = (fps, mode, output)
        self._refresh_text()

    def set_language(self, language: str) -> None:
        self._language = language
        self._refresh_text()

    def _refresh_text(self) -> None:
        key = "drag_active" if self._drag_active else "drop_title"
        self.title_label.setText(t(key, self._language))
        self.subtitle_label.setText(t("drop_sub", self._language))
        self.browse_button.setText(t("add_files_btn", self._language))
        self.folder_button.setText(t("add_folder_btn", self._language))
        for key, label in self.format_labels.items():
            label.setText(t(f"format_{key}", self._language))
        self.profile_title.setText(t("active_patch_profile", self._language))
        fps, mode, output = self._profile
        self.profile_summary.setText(
            t("drop_profile_summary", self._language, fps=fps, mode=mode, output=output)
        )

    def _refresh_style(self) -> None:
        theme = self._theme
        caption = theme.fonts.caption
        self.center_card.setStyleSheet(
            "QFrame#DropCenterCard {"
            f"background: {theme.color('surface_raised')};"
            f"border: 1px solid {theme.color('border')};"
            f"border-radius: {theme.radii.card}px;"
            "}"
        )
        if self.center_card.graphicsEffect() is None:
            shadow = QGraphicsDropShadowEffect(self.center_card)
            shadow.setBlurRadius(26)
            shadow.setOffset(0, 4)
            shadow.setColor(QColor(0, 0, 0, 64))
            self.center_card.setGraphicsEffect(shadow)
        badge_qss = (
            "QLabel {"
            f"background: {theme.color('surface')};"
            f"border: 1px solid {theme.color('border')};"
            "border-radius: 9px;"
            f"color: {theme.color('text2')};"
            f"font-size: {caption}px;"
            "font-weight: 600;"
            "padding: 0 9px;"
            "}"
        )
        for label in self.format_labels.values():
            label.setStyleSheet(badge_qss)
        self.profile_strip.setStyleSheet(
            "QFrame#DropProfileStrip {"
            f"background: {theme.color('surface')};"
            f"border: 1px solid {theme.color('border')};"
            f"border-radius: {theme.radii.control}px;"
            "}"
            f"QFrame#DropProfileStrip QLabel {{ color: {theme.color('text2')}; }}"
        )

    def _refresh_icon(self) -> None:
        icon = get_icon("zap" if self._drag_active else "folder", self._theme.is_dark)
        pixmap = icon.pixmap(QSize(40, 40))
        if pixmap.isNull():
            pixmap = QPixmap()
        self.icon_label.setPixmap(pixmap)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.browse_requested.emit()
        super().mousePressEvent(event)

    def paintEvent(self, _event: QPaintEvent) -> None:
        theme = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        radius = theme.radii.card
        painter.translate(rect.center())
        painter.scale(self._scale, self._scale)
        painter.translate(-rect.center())

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            QColor(theme.color("surface_drop_hover" if self._drag_active else "surface"))
        )
        painter.drawRoundedRect(rect, radius, radius)

        if self._drag_active:
            border = QColor(theme.color("accent"))
        else:
            border = _blend_color(
                QColor(theme.color("border")),
                QColor(theme.color("accent_dim_border")),
                self._breath_phase,
            )
        pen = QPen(border)
        pen.setWidthF(2.0 if self._drag_active else 1.4)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([4.0, 3.0])
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.8, 0.8, -0.8, -0.8), radius, radius)
        painter.end()


class QueueModel(QAbstractListModel):
    """Thin adapter over ``controller.items.items``; never owns queue state."""

    ItemRole = Qt.ItemDataRole.UserRole + 1

    def __init__(self, owner: QueueView) -> None:
        super().__init__(owner)
        self._owner = owner
        self._items: list[QueueItem] = []

    def rowCount(
        self, parent: QModelIndex | QPersistentModelIndex = _INVALID_INDEX
    ) -> int:
        return 0 if parent.isValid() else len(self._items)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        if role == self.ItemRole:
            return item
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return str(item.path)
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        return base | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def item_at(self, row: int) -> QueueItem | None:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def refresh(self) -> None:
        self.beginResetModel()
        self._items = list(self._owner.controller.items.items)
        self.endResetModel()

    def notify_row(self, row: int) -> None:
        if 0 <= row < len(self._items):
            index = self.createIndex(row, 0)
            self.dataChanged.emit(index, index)


class QueueDelegate(QStyledItemDelegate):
    """Paint-only rows: checkbox, filename, caption, meta, pills, remove."""

    def __init__(self, owner: QueueView) -> None:
        super().__init__(owner)
        self._owner = owner
        self._theme = owner.theme
        self._colors: dict[str, QColor] = {}
        self.font_filename = QFont()
        self.font_caption = QFont()
        self.font_badge = QFont()
        self.fm_caption = QFontMetricsF(self.font_caption)
        self.fm_filename = QFontMetricsF(self.font_filename)
        self.fm_badge = QFontMetricsF(self.font_badge)
        self._appear: dict[str, float] = {}
        self._appear_anims: dict[str, QVariantAnimation] = {}
        self._pill_widths: dict[str, float] = {}
        self._action_pixmaps: dict[str, QPixmap] = {}
        self._readiness_hits: dict[str, QRectF | None] = {}
        self.reduce_motion = False
        self.set_theme(self._theme)

    def set_reduce_motion(self, enabled: bool) -> None:
        self.reduce_motion = bool(enabled)
        if self.reduce_motion:
            for animation in self._appear_anims.values():
                animation.stop()
                animation.deleteLater()
            self._appear_anims.clear()
            self._appear.clear()

    def mark_new(self, item_ids: list[str], current_ids: set[str]) -> None:
        for item_id in list(self._appear):
            if item_id not in current_ids:
                self._appear.pop(item_id, None)
                animation = self._appear_anims.pop(item_id, None)
                if animation is not None:
                    animation.stop()
                    animation.deleteLater()
        if self.reduce_motion:
            return
        for item_id in item_ids[:12]:
            if item_id in self._appear_anims:
                continue
            self._appear[item_id] = 0.0
            animation = QVariantAnimation(self)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            animation.setDuration(160)
            animation.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
            animation.valueChanged.connect(
                lambda value, key=item_id: self._appear_tick(key, float(value))
            )
            animation.finished.connect(lambda key=item_id: self._appear_done(key))
            self._appear_anims[item_id] = animation
            animation.start()

    def _appear_tick(self, item_id: str, value: float) -> None:
        self._appear[item_id] = value
        self._owner.list_view.viewport().update()

    def _appear_done(self, item_id: str) -> None:
        self._appear.pop(item_id, None)
        animation = self._appear_anims.pop(item_id, None)
        if animation is not None:
            animation.deleteLater()
        self._owner.list_view.viewport().update()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._colors = {}
        self._pill_widths = {}
        self._action_pixmaps = {}
        for font, size, weight in (
            (self.font_filename, theme.fonts.body, QFont.Weight.DemiBold),
            (self.font_caption, theme.fonts.caption, QFont.Weight.Normal),
            (self.font_badge, theme.fonts.badge, QFont.Weight.DemiBold),
        ):
            font.setFamilies(list(UI_FONT_FAMILIES))
            font.setPixelSize(size)
            font.setWeight(weight)
        self.fm_caption = QFontMetricsF(self.font_caption)
        self.fm_filename = QFontMetricsF(self.font_filename)
        self.fm_badge = QFontMetricsF(self.font_badge)

    # ---------- geometry shared with the view's hit testing ----------
    def row_rect(self, rect: QRectF) -> QRectF:
        return QRectF(rect).adjusted(2, 2, -2, -2)

    def checkbox_rect(self, rect: QRectF) -> QRectF:
        row = self.row_rect(rect)
        size = 16.0
        return QRectF(row.left() + 12, row.center().y() - size / 2, size, size)

    def thumbnail_rect(self, rect: QRectF) -> QRectF:
        row = self.row_rect(rect)
        check = self.checkbox_rect(rect)
        width, height = THUMBNAIL_SIZE
        return QRectF(
            check.right() + 10,
            row.center().y() - height / 2,
            width,
            height,
        )

    def action_rects(self, rect: QRectF) -> dict[str, QRectF]:
        row = self.row_rect(rect)
        y = row.center().y() - _ACTION_SIZE / 2
        right = row.right() - 10
        rects: dict[str, QRectF] = {}
        for key in ("remove", "forensic", "override"):
            rects[key] = QRectF(right - _ACTION_SIZE, y, _ACTION_SIZE, _ACTION_SIZE)
            right -= _ACTION_SIZE + 4
        return rects

    def remove_rect(self, rect: QRectF) -> QRectF:
        return self.action_rects(rect)["remove"]

    def readiness_rect(self, item: QueueItem) -> QRectF | None:
        """Last painted badge rect; paint is what the user can actually click."""
        if self._owner.readiness(item) is None:  # still probing: nothing to explain
            return None
        return self._readiness_hits.get(item.item_id)

    def readiness_tooltip(self, item: QueueItem) -> str:
        report = self._owner.readiness(item)
        if report is None:
            return self._owner.tr("readiness_unknown")
        lines = [
            f"{self._owner.tr(f'readiness_{report.status}')} {report.score}%",
            *(
                f"{check.label}: {self._owner.tr(f'check_status_{check.status}')} "
                f"— {check.detail}"
                for check in report.checks
            ),
            self._owner.tr("readiness_tip"),
        ]
        return "\n".join(lines)

    def row_pills(self, item: QueueItem) -> list[tuple[str, str]]:
        """Structured metadata for one row, keyed for tests and tooling."""
        info = item.info
        resolution = (
            f"{info.width}×{info.height}" if info and info.width and info.height else "—"
        )
        source = _fps_text(info.fps) if info is not None else "—"
        codec = (info.codec or "—") if info is not None else "—"
        timescale = item.timescale or self._owner.target_timescale()
        target = _fps_text(timescale / 1000) if timescale else "—"
        mode = self._owner.strategy_short_label(item.strategy)
        size = _format_size(info.file_size_bytes if info is not None else None)
        return [
            ("resolution", resolution),
            ("fps", f"{source} → {target} fps"),
            ("mode", f"{codec} · {mode}"),
            ("size", size),
        ]

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        return QSize(0, ROW_HEIGHT)

    # ---------- painting ----------
    def color(self, name: str) -> QColor:
        cached = self._colors.get(name)
        if cached is None:
            cached = QColor(self._theme.color(name))
            self._colors[name] = cached
        return cached

    def fill(self, name: str, alpha: int = 34) -> QColor:
        key = f"{name}:{alpha}"
        cached = self._colors.get(key)
        if cached is None:
            cached = QColor(self._theme.color(name))
            cached.setAlpha(alpha)
            self._colors[key] = cached
        return cached

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        model = index.model()
        item = model.item_at(index.row()) if isinstance(model, QueueModel) else None
        if item is None:
            return

        owner = self._owner
        theme = self._theme
        row = self.row_rect(QRectF(option.rect))
        focused = owner.is_focused(item)
        hovered = owner.hover_row == index.row()
        radius = theme.radii.control

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        appear = self._appear.get(item.item_id, 1.0)
        if appear < 1.0:
            painter.setOpacity(max(0.0, appear))
            painter.translate(0.0, (1.0 - appear) * 8.0)

        if focused:
            painter.setPen(QPen(self.color("accent_dim_border"), 1))
            painter.setBrush(self.color("accent_dim"))
            painter.drawRoundedRect(row, radius, radius)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.color("surface_hover"))
            painter.drawRoundedRect(row, radius, radius)
        elif index.row() < model.rowCount() - 1:
            painter.setPen(QPen(self.color("border"), 1))
            painter.drawLine(
                int(row.left() + 12),
                int(row.bottom()),
                int(row.right() - 12),
                int(row.bottom()),
            )

        # Checkbox
        check = self.checkbox_rect(QRectF(option.rect))
        check_radius = max(3, theme.radii.control // 2)
        if item.selected:
            painter.setPen(QPen(self.color("accent"), 1))
            painter.setBrush(self.color("accent"))
        else:
            painter.setPen(QPen(self.color("border_hover"), 1.4))
            painter.setBrush(self.color("surface"))
        painter.drawRoundedRect(check, check_radius, check_radius)
        if item.selected:
            pen = QPen(self.color("on_accent"), 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            path = [
                (check.left() + 4, check.center().y()),
                (check.center().x() - 1, check.bottom() - 4),
                (check.right() - 3.5, check.top() + 4.5),
            ]
            for start, end in zip(path, path[1:], strict=False):
                painter.drawLine(int(start[0]), int(start[1]), int(end[0]), int(end[1]))

        # Thumbnail (56x32, 6px radius) after the checkbox.
        thumb = self.thumbnail_rect(QRectF(option.rect))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color("surface_raised"))
        painter.drawRoundedRect(thumb, 6, 6)
        pixmap = owner.thumbnail(item.item_id)
        if pixmap is not None and not pixmap.isNull():
            painter.save()
            clip = QPainterPath()
            clip.addRoundedRect(thumb, 6, 6)
            painter.setClipPath(clip)
            scaled = pixmap.scaled(
                int(thumb.width()),
                int(thumb.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(
                int(thumb.center().x() - scaled.width() / 2),
                int(thumb.center().y() - scaled.height() / 2),
                scaled,
            )
            painter.restore()
        else:
            media = self._icon_pixmap("play")
            if not media.isNull():
                painter.drawPixmap(
                    int(thumb.center().x() - media.width() / 2),
                    int(thumb.center().y() - media.height() / 2),
                    media,
                )
        painter.setPen(QPen(self.color("border"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(thumb.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)

        # Right-side zones: row actions, status, readiness, metadata pills.
        actions = self.action_rects(QRectF(option.rect))
        right = actions["override"].left() - 8
        center_y = row.center().y()

        status_text = owner.tr(f"status_{item.status}")
        status_width = self.fm_badge.horizontalAdvance(status_text) + 16
        status_rect = QRectF(right - status_width, center_y - 10, status_width, 20)
        right = status_rect.left() - 6

        readiness_text, readiness_token = self._readiness(item)
        readiness_width = self.fm_badge.horizontalAdvance(readiness_text) + 16
        readiness_rect = QRectF(right - readiness_width, center_y - 10, readiness_width, 20)

        text_left = thumb.right() + 12
        pills = [
            (text, self._pill_width(text))
            for _key, text in self.row_pills(item)
        ]
        show_readiness = True
        free = max(0.0, readiness_rect.left() - 10 - text_left)
        if self._pills_width(pills) > free - 84:
            # Metadata pills are the row's primary signal; drop the badge first.
            show_readiness = False
            free = max(0.0, status_rect.left() - 6 - text_left)
        while pills and self._pills_width(pills) > free - 84:
            pills.pop()
        right = status_rect.left() - 6 if not show_readiness else readiness_rect.left() - 10
        pill_width = self._pills_width(pills)
        pill_left = right - pill_width if pills else right
        text_right = pill_left - 12 if pills else right
        text_width = max(0.0, text_right - text_left)
        filename_rect = QRectF(text_left, row.top() + 8, text_width, 18)
        caption_rect = QRectF(text_left, row.top() + 28, text_width, 16)

        filename = self.fm_filename.elidedText(
            item.path.name, Qt.TextElideMode.ElideMiddle, int(text_width)
        )
        painter.setFont(self.font_filename)
        painter.setPen(self.color("text"))
        painter.drawText(filename_rect, int(Qt.AlignmentFlag.AlignLeft), filename)

        caption, is_error = self._caption(item)
        caption = self.fm_caption.elidedText(caption, Qt.TextElideMode.ElideMiddle, int(text_width))
        painter.setFont(self.font_caption)
        painter.setPen(self.color("danger") if is_error else self.color("text2"))
        painter.drawText(caption_rect, int(Qt.AlignmentFlag.AlignLeft), caption)

        x = pill_left
        for text, width in pills:
            pill = QRectF(x, center_y - 9, width, 18)
            painter.setPen(QPen(self.color("border"), 1))
            painter.setBrush(self.color("surface_raised"))
            painter.drawRoundedRect(pill, 9, 9)
            painter.setFont(self.font_badge)
            painter.setPen(self.color("text2"))
            painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), text)
            x += width + 6

        if show_readiness:
            self._draw_pill(painter, readiness_rect, readiness_text, readiness_token)
        self._readiness_hits[item.item_id] = readiness_rect if show_readiness else None
        self._draw_pill(painter, status_rect, status_text, owner.status_token(item.status))

        if hovered or focused:
            for key in ("override", "forensic", "remove"):
                if key == "remove" and owner.busy:
                    continue
                area = actions[key]
                if hovered and owner.hover_action == key:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(self.color("surface_hover"))
                    painter.drawRoundedRect(area, radius, radius)
                self._draw_action(painter, key, area)

        painter.restore()

    def _pills_width(self, pills: list[tuple[str, float]]) -> float:
        return sum(width + 6 for _text, width in pills) - 6 if pills else 0.0

    def _pill_width(self, text: str) -> float:
        cached = self._pill_widths.get(text)
        if cached is not None:
            return cached
        width = self.fm_badge.horizontalAdvance(text) + 10
        if len(self._pill_widths) > 256:
            self._pill_widths.clear()
        self._pill_widths[text] = width
        return width

    def _icon_pixmap(self, name: str) -> QPixmap:
        cached = self._action_pixmaps.get(name)
        if cached is not None:
            return cached
        pixmap = get_icon(name, self._theme.is_dark).pixmap(QSize(14, 14))
        if pixmap.isNull():
            pixmap = QPixmap()
        self._action_pixmaps[name] = pixmap
        return pixmap

    def _draw_action(self, painter: QPainter, key: str, area: QRectF) -> None:
        if key == "remove":
            pen = QPen(
                self.color("danger" if self._owner.hover_action == key else "muted"), 1.6
            )
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            inset = 9.0
            painter.drawLine(
                int(area.left() + inset),
                int(area.top() + inset),
                int(area.right() - inset),
                int(area.bottom() - inset),
            )
            painter.drawLine(
                int(area.right() - inset),
                int(area.top() + inset),
                int(area.left() + inset),
                int(area.bottom() - inset),
            )
            return
        pixmap = self._icon_pixmap("zap" if key == "override" else "forensic")
        if pixmap.isNull():
            return
        painter.drawPixmap(
            int(area.center().x() - pixmap.width() / 2),
            int(area.center().y() - pixmap.height() / 2),
            pixmap,
        )

    def _draw_pill(self, painter: QPainter, rect: QRectF, text: str, token: str) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.fill(token))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setFont(self.font_badge)
        painter.setPen(self.color(token))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)

    def _readiness(self, item: QueueItem) -> tuple[str, str]:
        report = self._owner.readiness(item)
        if report is None:
            return self._owner.tr("readiness_unknown"), "muted"
        if report.status == "ready":
            token = "success"
        elif report.status == "review":
            token = "warn"
        elif report.status == "issues":
            token = "danger"
        else:
            token = "muted"
        text = f"{self._owner.tr(f'readiness_{report.status}')} {report.score}%"
        return text, token

    def _caption(self, item: QueueItem) -> tuple[str, bool]:
        if item.error:
            return item.error, True
        caption = str(item.path)
        overrides: list[str] = []
        if item.timescale is not None:
            overrides.append(f"{item.timescale} ts")
        if item.strategy is not None:
            overrides.append(item.strategy)
        if overrides:
            caption += "  " + self._owner.tr("override_status_active", details=", ".join(overrides))
        return caption, False


class QueueView(QWidget):
    """Queue panel: toolbar, drop card, model/view list, footer."""

    patch_requested = Signal()
    focus_changed = Signal(object)
    selection_changed = Signal()
    status_message = Signal(str)
    forensic_requested = Signal(Path)
    readiness_clicked = Signal(object)

    def __init__(
        self,
        controller: AppController,
        settings: Settings,
        theme_manager: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.settings = settings
        self._theme_manager = theme_manager
        self._theme: Theme = theme_manager.theme
        self._busy = False
        self._focused_path: Path | None = None
        self.hover_row = -1
        self.hover_remove = -1
        self.hover_action = ""
        self.hover_readiness = False
        self._known_ids: set[str] | None = None
        self._motion_window: QWidget | None = None
        self._readiness_cache: dict[str, tuple[int, str, ReadinessReport]] = {}
        self._thumbs: dict[str, QPixmap] = {}
        self._thumb_failed: set[str] = set()
        self._thumb_loader = ThumbnailLoader(self._ffmpeg_path, self)
        self._thumb_loader.ready.connect(self._on_thumb_ready)

        self._storage = QSettings("FPSPatcherStudio", "QtUI")
        self._preview_on = bool(settings.preview_player)
        settings.preview_player = self._preview_on

        self.setObjectName("QueueView")
        self.setAcceptDrops(True)
        self._build_ui()
        self._theme_manager.changed.connect(self.set_theme)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.applicationStateChanged.connect(self._on_app_state)
        self.set_theme(self._theme)
        self.refresh()

    def _on_app_state(self, _state: Qt.ApplicationState) -> None:
        self._update_drop_motion()

    # ---------- public API ----------
    def refresh(self) -> None:
        items = self.controller.items.items
        ids = [item.item_id for item in items]
        new_ids = (
            []
            if self._known_ids is None
            else [item_id for item_id in ids if item_id not in self._known_ids]
        )
        self._known_ids = set(ids)
        self.model.refresh()
        self._prune_readiness(items)
        self._prune_thumbs(items)
        self._request_thumbnails(items)
        if self._focused_path is not None and not any(i.path == self._focused_path for i in items):
            self._focused_path = None
        has_items = bool(items)
        self.drop_card.setVisible(not has_items)
        self.summary_label.setVisible(has_items)
        self.list_view.setVisible(has_items)
        self.summary_label.setText(self.tr("queue_collapsed", count=len(items)))
        self.retry_button.setVisible(any(i.status in ("failed", "skipped") for i in items))
        self.delegate.mark_new(new_ids, set(ids))
        self._sync_footer()
        self._sync_controls()
        self._update_drop_motion()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._sync_controls()
        self.list_view.viewport().update()
        self._update_drop_motion()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.drop_card.set_language(getattr(self.settings, "language", "en"))
        self.drop_card.set_theme(theme)
        self.add_files_button.setText(self.tr("add_files_btn"))
        self.add_folder_button.setText(self.tr("add_folder_btn"))
        self.retry_button.setText(self.tr("retry_failed"))
        self.clear_selection_button.setText(self.tr("clear_selection"))
        self.clear_all_button.setText(self.tr("clear_all"))
        self.apply_button.setText(self.tr("apply_selected"))
        self.list_view.setAccessibleDescription(
            ", ".join(
                self.tr(f"queue_{key}_action")
                for key in ("override", "forensic", "remove")
            )
        )
        self.refresh()
        self.preview_switch.set_theme(theme)
        self.delegate.set_theme(theme)
        self._divider.setStyleSheet(f"background: {theme.color('border')}; border: none;")
        self.setStyleSheet(
            f"QWidget#QueueView {{ background: {theme.color('bg')}; }}"
            f"QListView#QueueViewList {{"
            f"background: {theme.color('surface')};"
            f"border: 1px solid {theme.color('border')};"
            f"border-radius: {theme.radii.card}px;"
            f"padding: {theme.outer}px;"
            "}"
            f"QListView#QueueViewList:focus {{"
            f"border: 1px solid {theme.color('border_focus')};"
            "}"
        )
        self.add_folder_button.setIcon(get_icon("folder", theme.is_dark))
        reduce_motion = bool(getattr(self.settings, "reduce_motion", False))
        self.drop_card.set_reduce_motion(reduce_motion)
        self.delegate.set_reduce_motion(reduce_motion)
        self._update_drop_motion()
        self.refresh_profile()
        self.update()

    def _update_drop_motion(self) -> None:
        app = QApplication.instance()
        active = not isinstance(app, QApplication) or (
            app.applicationState() == Qt.ApplicationState.ApplicationActive
        )
        visible = self.drop_card.isVisible()
        self.drop_card.set_breathing(active and visible)

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        window = self.window()
        if window is not self._motion_window:
            if self._motion_window is not None:
                self._motion_window.removeEventFilter(self)
            self._motion_window = window
            window.installEventFilter(self)
        self._update_drop_motion()

    def hideEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.drop_card.set_breathing(False)
        super().hideEvent(event)

    def selected_paths(self) -> list[Path]:
        return [item.path for item in self.controller.items.selected()]

    def focused_path(self) -> Path | None:
        return self._focused_path

    @property
    def theme(self) -> Theme:
        return self._theme

    @property
    def busy(self) -> bool:
        return self._busy

    def tr(self, key: str, **kwargs: object) -> str:  # type: ignore[override]
        return t(key, getattr(self.settings, "language", "en"), **kwargs)

    def is_focused(self, item: QueueItem) -> bool:
        return self._focused_path is not None and item.path == self._focused_path

    @staticmethod
    def status_token(status: str) -> str:
        if status in ("done", "ready"):
            return "success"
        if status == "failed":
            return "danger"
        if status in ("skipped", "probing"):
            return "warn"
        if status == "patching":
            return "accent"
        return "muted"

    def readiness(self, item: QueueItem) -> ReadinessReport | None:
        if item.info is None:
            return None
        profile = getattr(self.settings, "platform_profile", "generic")
        cached = self._readiness_cache.get(item.item_id)
        if cached is not None and cached[0] == id(item.info) and cached[1] == profile:
            return cached[2]
        report = evaluate_readiness(item.info, profile)
        self._readiness_cache[item.item_id] = (id(item.info), profile, report)
        return report

    def target_timescale(self) -> int:
        preset = str(getattr(self.settings, "last_preset", "60 FPS"))
        if preset in FPS_PRESETS:
            return FPS_PRESETS[preset]
        try:
            return int(getattr(self.settings, "custom_timescale", 60000))
        except (TypeError, ValueError):
            return 60000

    def global_strategy(self) -> str:
        return migrate_strategy_name(str(getattr(self.settings, "strategy", "bxd-mobile")))[0]

    def strategy_label(self) -> str:
        preset = UI_PRESETS.get(self.global_strategy())
        return preset.label if preset is not None else self.global_strategy()

    def strategy_short_label(self, strategy: str | None) -> str:
        key = migrate_strategy_name(str(strategy or self.global_strategy()))[0]
        preset = UI_PRESETS.get(key)
        if preset is None:
            return key
        return preset.label.removeprefix("X1T ").removeprefix("For ")

    def refresh_profile(self) -> None:
        timescale = self.target_timescale()
        fps = _fps_text(timescale / 1000) if timescale else "—"
        if fps != "—":
            fps += " FPS"
        output_key = (
            "drop_profile_output_custom"
            if getattr(self.settings, "output_dir", "")
            else "drop_profile_output_same"
        )
        self.drop_card.set_profile(fps, self.strategy_label(), self.tr(output_key))
        self.list_view.viewport().update()

    def thumbnail(self, item_id: str) -> QPixmap | None:
        return self._thumbs.get(item_id)

    def _ffmpeg_path(self) -> Path | None:
        tools = self.controller.ffmpeg
        return tools.ffmpeg if tools is not None else None

    def _request_thumbnails(self, items: list[QueueItem]) -> None:
        if self._ffmpeg_path() is None:
            return
        for item in items:
            if item.item_id in self._thumbs or item.item_id in self._thumb_failed:
                continue
            self._thumb_loader.request(item.item_id, item.path)

    def _on_thumb_ready(self, item_id: str, data: bytes) -> None:
        self._thumb_loader.release(item_id)
        if not data:
            self._thumb_failed.add(item_id)
            return
        try:
            image = QImage.fromData(data)
        except ValueError:
            self._thumb_failed.add(item_id)
            return
        if image.isNull():
            self._thumb_failed.add(item_id)
            return
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            self._thumb_failed.add(item_id)
            return
        self._thumbs[item_id] = pixmap
        while len(self._thumbs) > _MAX_THUMBS:
            self._thumbs.pop(next(iter(self._thumbs)))
        self.list_view.viewport().update()

    def _prune_thumbs(self, items: list[QueueItem]) -> None:
        known = {item.item_id for item in items}
        self._thumbs = {
            key: value for key, value in self._thumbs.items() if key in known
        }
        self._thumb_failed &= known

    # ---------- construction ----------
    def _build_ui(self) -> None:
        theme = self._theme
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.outer)

        toolbar = QWidget(self)
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(theme.outer)
        self.add_files_button = text_button(self.tr("add_files_btn"), theme, self._browse_files)
        self.add_folder_button = text_button(self.tr("add_folder_btn"), theme, self._browse_folder)
        self.add_folder_button.setIcon(get_icon("folder", theme.is_dark))
        self.add_folder_button.setIconSize(QSize(14, 14))
        self.retry_button = text_button(self.tr("retry_failed"), theme, self._retry_failed)
        self.retry_button.setVisible(False)
        self.select_all_button = text_button(self.tr("select_all"), theme, self._toggle_select_all)
        self.clear_selection_button = text_button(
            self.tr("clear_selection"), theme, self._clear_selection
        )
        self.clear_all_button = text_button(self.tr("clear_all"), theme, self._clear_all)
        for widget in (
            self.add_files_button,
            self.add_folder_button,
            self.retry_button,
            self.select_all_button,
            self.clear_selection_button,
            self.clear_all_button,
        ):
            bar.addWidget(widget)
        bar.addStretch(1)
        root.addWidget(toolbar)

        self.drop_card = DropCard(theme, getattr(self.settings, "language", "en"), self)
        self.drop_card.browse_requested.connect(self._browse_files)
        self.drop_card.folder_requested.connect(self._browse_folder)
        root.addWidget(self.drop_card, 1)

        self.summary_label = QLabel(self)
        self.summary_label.setProperty("role", "caption")
        self.summary_label.setContentsMargins(theme.inner, 0, 0, 0)
        self.summary_label.setFixedHeight(22)
        self.summary_label.setVisible(False)
        root.addWidget(self.summary_label)

        self.model = QueueModel(self)
        self.delegate = QueueDelegate(self)
        self.list_view = QListView(self)
        self.list_view.setObjectName("QueueViewList")
        self.list_view.setModel(self.model)
        self.list_view.setItemDelegate(self.delegate)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setMouseTracking(True)
        self.list_view.viewport().setMouseTracking(True)
        self.list_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.list_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_view.setFrameShape(QFrame.Shape.NoFrame)
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_view.setAccessibleDescription(
            ", ".join(
                self.tr(f"queue_{key}_action")
                for key in ("override", "forensic", "remove")
            )
        )
        self.list_view.setVisible(False)
        self.list_view.viewport().installEventFilter(self)
        self.list_view.customContextMenuRequested.connect(self._show_context_menu)
        root.addWidget(self.list_view, 1)

        self._divider = hairline(theme)
        root.addWidget(self._divider)

        footer = QWidget(self)
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(theme.inner)
        self.preview_switch = Switch(theme, footer)
        self.preview_switch.setChecked(self._preview_on)
        self.preview_switch.toggled.connect(self._on_preview_toggled)
        foot.addWidget(self.preview_switch)
        self.preview_label = QLabel(self.tr("preview_player"), footer)
        self.preview_label.setProperty("role", "caption")
        foot.addWidget(self.preview_label)
        foot.addStretch(1)
        self.selected_count_label = QLabel(footer)
        self.selected_count_label.setProperty("role", "caption")
        foot.addWidget(self.selected_count_label)
        self.apply_button = text_button(
            self.tr("apply_selected"),
            theme,
            self.patch_requested.emit,
            variant="secondary",
            height=28,
        )
        foot.addWidget(self.apply_button)
        root.addWidget(footer)

    # ---------- state sync ----------
    def _sync_footer(self) -> None:
        items = self.controller.items.items
        selected = sum(1 for item in items if item.selected)
        self.selected_count_label.setText(
            self.tr("selected_count", selected=selected, total=len(items))
        )
        all_selected = bool(items) and selected == len(items)
        self.select_all_button.setText(self.tr("deselect_all" if all_selected else "select_all"))
        self.apply_button.setEnabled(not self._busy and selected > 0)

    def _sync_controls(self) -> None:
        for button in (
            self.add_files_button,
            self.add_folder_button,
            self.retry_button,
            self.select_all_button,
            self.clear_selection_button,
            self.clear_all_button,
        ):
            button.setEnabled(not self._busy)
        self.drop_card.browse_button.setEnabled(not self._busy)
        self._sync_footer()

    def _prune_readiness(self, items: list[QueueItem]) -> None:
        known = {item.item_id for item in items}
        self._readiness_cache = {
            key: value for key, value in self._readiness_cache.items() if key in known
        }

    # ---------- toolbar actions ----------
    def _browse_files(self) -> None:
        if self._busy:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            self.tr("browse_files"),
            "",
            "Video files (*.mp4 *.mov *.m4v);;All files (*)",
        )
        if files:
            self.add_paths([Path(path) for path in files])

    def _browse_folder(self) -> None:
        if self._busy:
            return
        folder = QFileDialog.getExistingDirectory(self, self.tr("browse_folder"))
        if folder:
            self.add_paths(self.files_in_folder(Path(folder)))

    def _retry_failed(self) -> None:
        if self._busy:
            return
        if self.controller.items.reset_failed():
            self.refresh()

    def _toggle_select_all(self) -> None:
        if self._busy:
            return
        items = self.controller.items.items
        self.controller.items.select_all(not (items and all(i.selected for i in items)))
        self.model.refresh()
        self._sync_footer()
        self.selection_changed.emit()

    def _clear_selection(self) -> None:
        if self._busy:
            return
        self.controller.items.select_all(False)
        self.model.refresh()
        self._sync_footer()
        self.selection_changed.emit()

    def _clear_all(self) -> None:
        if self._busy or not self.controller.items:
            return
        answer = QMessageBox.question(self, self.tr("clear_all"), self.tr("clear_confirm"))
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.controller.clear_queue()
        self._focused_path = None
        self.refresh()
        self.selection_changed.emit()
        self.focus_changed.emit(None)

    def _on_preview_toggled(self, checked: bool) -> None:
        self._preview_on = bool(checked)
        self.settings.preview_player = self._preview_on
        self._storage.setValue("ui/preview_player", self._preview_on)
        self._storage.sync()
        save_async = getattr(self.settings, "save_async", None)
        if callable(save_async):
            save_async()

    # ---------- queue mutations ----------
    def add_paths(self, paths: list[Path]) -> None:
        """Append supported files/folders, then refresh the model once."""
        if self._busy or not paths:
            return
        collected: list[Path] = []
        for path in paths:
            if path.is_dir():
                collected.extend(self.files_in_folder(path))
            else:
                collected.append(path)
        if not collected:
            return
        result = self.controller.add_files(collected)
        if result.added:
            self._focused_path = result.added[-1]
        self.refresh()
        self.selection_changed.emit()
        if result.added:
            self.focus_changed.emit(
                self.controller.items.get(self._focused_path) if self._focused_path else None
            )
            self.status_message.emit(self.tr("files_queued", count=len(result.added)))

    @staticmethod
    def files_in_folder(folder: Path) -> list[Path]:
        found: list[Path] = []
        for root, dirs, files in os.walk(folder):
            dirs.sort()
            for name in sorted(files):
                path = Path(root) / name
                if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    found.append(path)
        return found

    def _remove_item(self, path: Path) -> bool:
        if self._busy:
            return False
        removed = self.controller.items.remove(
            path, locked_path=self.controller.current_patching_path
        )
        if not removed:
            return False
        if self._focused_path == path:
            self._focused_path = None
            self.focus_changed.emit(None)
        self.refresh()
        self.selection_changed.emit()
        return True

    def _move_item(self, path: Path, delta: int) -> None:
        if self._busy:
            return
        items = self.controller.items.paths()
        if path not in items:
            return
        self.controller.items.move(path, items.index(path) + delta)
        self.refresh()
        self.selection_changed.emit()

    def _toggle_item(self, item: QueueItem, row: int) -> None:
        if self._busy:
            return
        self.controller.items.toggle(item.path)
        self.model.notify_row(row)
        self._sync_footer()
        self.selection_changed.emit()

    def _focus_row(self, row: int, *, open_player: bool) -> None:
        item = self.model.item_at(row)
        if item is None:
            return
        self._focused_path = item.path
        if item.info is not None:
            self.controller.current = item.info
        self.list_view.setCurrentIndex(self.model.index(row, 0))
        self.list_view.viewport().update()
        self.focus_changed.emit(item)
        if open_player:
            self._open_path(item.path)

    # ---------- context menu & actions ----------
    def _show_context_menu(self, pos: QPoint) -> None:
        index = self.list_view.indexAt(pos)
        if not index.isValid():
            return
        item = self.model.item_at(index.row())
        if item is None:
            return
        self._focus_row(index.row(), open_player=False)

        menu = QMenu(self)
        remove_action = menu.addAction(self.tr("delete_selected"))
        remove_action.setEnabled(not self._busy)
        open_folder = menu.addAction(self.tr("open_containing_folder"))
        open_output = menu.addAction(self.tr("open_output_file"))
        open_output.setEnabled(item.output is not None and item.output.exists())
        copy_path = menu.addAction(self.tr("copy_path"))
        menu.addSeparator()
        set_fps = menu.addAction(self.tr("set_fps"))
        preset_menu = menu.addMenu(self.tr("set_strategy"))
        preset_actions = {
            preset_menu.addAction(preset.label): key
            for key, preset in UI_PRESETS.items()
        }
        clear_override = menu.addAction(self.tr("override_clear_btn"))
        clear_override.setEnabled(
            item.timescale is not None or item.strategy is not None
        )
        menu.addSeparator()
        move_up = menu.addAction(self.tr("move_up"))
        move_down = menu.addAction(self.tr("move_down"))
        move_up.setEnabled(not self._busy)
        move_down.setEnabled(not self._busy)

        chosen = menu.exec(self.list_view.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is remove_action:
            self._remove_item(item.path)
        elif chosen is open_folder:
            self._open_path(item.path.parent)
        elif chosen is open_output and item.output is not None:
            self._open_path(item.output)
        elif chosen is copy_path:
            QApplication.clipboard().setText(str(item.path))
            self.status_message.emit(self.tr("copied_flash"))
        elif chosen is set_fps:
            value, accepted = QInputDialog.getInt(
                self,
                self.tr("set_fps"),
                self.tr("timescale_lbl"),
                item.timescale or 60000,
                1,
                2_147_483_647,
            )
            if accepted:
                self.controller.items.set_override(
                    item.path, timescale=value, strategy=item.strategy
                )
                self.model.refresh()
                self.selection_changed.emit()
        elif chosen in preset_actions:
            self.controller.items.set_override(
                item.path,
                timescale=item.timescale,
                strategy=preset_actions[chosen],
            )
            self.model.refresh()
            self.selection_changed.emit()
        elif chosen is clear_override:
            self.controller.items.set_override(item.path, timescale=None, strategy=None)
            self.model.refresh()
            self.selection_changed.emit()
        elif chosen is move_up:
            self._move_item(item.path, -1)
        elif chosen is move_down:
            self._move_item(item.path, 1)

    def _open_path(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError:
            pass

    # ---------- view events ----------
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt naming
        if watched is self._motion_window and event.type() in (
            QEvent.Type.WindowActivate,
            QEvent.Type.WindowDeactivate,
        ):
            self._update_drop_motion()
            return super().eventFilter(watched, event)
        if watched is not self.list_view.viewport():
            return super().eventFilter(watched, event)
        kind = event.type()
        if kind == QEvent.Type.MouseMove:
            self._update_hover(cast(QMouseEvent, event).position().toPoint())
        elif kind == QEvent.Type.Leave:
            self.hover_row = -1
            self.hover_remove = -1
            self.hover_action = ""
            self.hover_readiness = False
            QToolTip.hideText()
            self.list_view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            self.list_view.viewport().update()
        elif kind == QEvent.Type.MouseButtonPress:
            mouse = cast(QMouseEvent, event)
            if mouse.button() == Qt.MouseButton.LeftButton:
                return self._handle_click(mouse.position().toPoint())
        elif kind == QEvent.Type.MouseButtonDblClick:
            mouse = cast(QMouseEvent, event)
            if mouse.button() == Qt.MouseButton.LeftButton:
                index = self.list_view.indexAt(mouse.position().toPoint())
                item = self.model.item_at(index.row()) if index.isValid() else None
                if item is not None:
                    # A preview-enabled single click already opened it.
                    if not self._preview_on:
                        self._open_path(item.path)
                    return True
        return super().eventFilter(watched, event)

    def _handle_click(self, pos: QPoint) -> bool:
        index = self.list_view.indexAt(pos)
        if not index.isValid():
            return False
        item = self.model.item_at(index.row())
        if item is None:
            return False
        rect = QRectF(self.list_view.visualRect(index))
        actions = self.delegate.action_rects(rect)
        for key in ("override", "forensic", "remove"):
            if actions[key].contains(pos):
                if key == "remove":
                    self._remove_item(item.path)
                elif key == "forensic":
                    self.forensic_requested.emit(item.path)
                else:
                    self._show_context_menu(pos)
                return True
        badge = self.delegate.readiness_rect(item)
        if badge is not None and badge.contains(pos):
            self.readiness_clicked.emit(item)
            self._focus_row(index.row(), open_player=False)
            return True
        if self.delegate.checkbox_rect(rect).contains(pos):
            self._toggle_item(item, index.row())
            return True
        self._focus_row(index.row(), open_player=self._preview_on)
        return True

    def _action_at(self, rect: QRectF, pos: QPoint) -> str:
        for key, area in self.delegate.action_rects(rect).items():
            if area.contains(pos):
                if key == "remove" and self._busy:
                    return ""
                return key
        return ""

    def _update_hover(self, pos: QPoint) -> None:
        index = self.list_view.indexAt(pos)
        if not index.isValid():
            changed = self.hover_row != -1
            self.hover_row = -1
            self.hover_remove = -1
            self.hover_action = ""
            self.hover_readiness = False
            QToolTip.hideText()
            self.list_view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            if changed:
                self.list_view.viewport().update()
            return
        rect = QRectF(self.list_view.visualRect(index))
        item = self.model.item_at(index.row())
        badge = self.delegate.readiness_rect(item) if item is not None else None
        over_readiness = badge is not None and badge.contains(pos)
        action = "" if over_readiness else self._action_at(rect, pos)
        over_remove = action == "remove"
        over_check = self.delegate.checkbox_rect(rect).contains(pos)
        changed = (
            self.hover_row,
            self.hover_remove,
            self.hover_action,
            self.hover_readiness,
        ) != (
            index.row(),
            index.row() if over_remove else -1,
            action,
            over_readiness,
        )
        if over_readiness != self.hover_readiness:
            if over_readiness and item is not None:
                QToolTip.showText(
                    self.list_view.viewport().mapToGlobal(pos),
                    self.delegate.readiness_tooltip(item),
                )
            else:
                QToolTip.hideText()
        elif action != self.hover_action:
            if action:
                QToolTip.showText(
                    self.list_view.viewport().mapToGlobal(pos),
                    self.tr(f"queue_{action}_action"),
                )
            else:
                QToolTip.hideText()
        self.hover_row = index.row()
        self.hover_remove = index.row() if over_remove else -1
        self.hover_action = action
        self.hover_readiness = over_readiness
        interactive = bool(action) or over_check or over_readiness
        self.list_view.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor if interactive else Qt.CursorShape.ArrowCursor
        )
        if changed:
            self.list_view.viewport().update()

    # ---------- drag and drop ----------
    @staticmethod
    def collect_urls(urls: list[QUrl]) -> list[Path]:
        """Local files and recursively walked folders, supported types only."""
        collected: list[Path] = []
        seen: set[Path] = set()
        for url in urls:
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            candidates = QueueView.files_in_folder(path) if path.is_dir() else [path]
            for candidate in candidates:
                if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTENSIONS:
                    resolved = candidate.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        collected.append(candidate)
        return collected

    def _drag_urls_active(self, event: QDragEnterEvent | QDragMoveEvent) -> bool:
        if self._busy or not event.mimeData().hasUrls():
            return False
        return any(
            url.isLocalFile()
            and (
                Path(url.toLocalFile()).is_dir()
                or Path(url.toLocalFile()).suffix.lower() in SUPPORTED_EXTENSIONS
            )
            for url in event.mimeData().urls()
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._drag_urls_active(event):
            self.drop_card.set_drag_active(self.drop_card.isVisible())
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._drag_urls_active(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self.drop_card.set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self.drop_card.set_drag_active(False)
        if self._busy:
            event.ignore()
            return
        paths = self.collect_urls(event.mimeData().urls())
        if paths:
            event.acceptProposedAction()
            self.add_paths(paths)
        else:
            event.ignore()
