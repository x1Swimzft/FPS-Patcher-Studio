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
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QEvent,
    QModelIndex,
    QObject,
    QPoint,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QUrl,
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
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ..app.queue_model import QueueItem
from ..core.models import SUPPORTED_EXTENSIONS
from ..core.platform_profiles import ReadinessReport, evaluate_readiness
from ..ui.strings import t
from .icons import get_icon
from .theme import UI_FONT_FAMILIES, Theme
from .widgets import Switch, hairline, text_button

if TYPE_CHECKING:
    from ..app.controller import AppController
    from ..config import Settings
    from .theme import ThemeManager

ROW_HEIGHT = 56
_INVALID_INDEX = QModelIndex()


def _format_duration(seconds: float) -> str:
    total = int(round(seconds or 0))
    if total <= 0:
        return "00:00"
    mins, secs = divmod(total, 60)
    hrs, mins = divmod(mins, 60)
    return f"{hrs:d}:{mins:02d}:{secs:02d}" if hrs else f"{mins:02d}:{secs:02d}"


def _format_meta(item: QueueItem) -> str:
    info = item.info
    if info is None:
        return "â€”"
    parts: list[str] = []
    if info.width and info.height:
        parts.append(f"{info.width}Ã—{info.height}")
    if info.duration_s:
        parts.append(_format_duration(info.duration_s))
    if info.fps:
        fps = f"{info.fps:.2f}".rstrip("0").rstrip(".")
        parts.append(f"{fps} fps")
    return " Â· ".join(parts) if parts else "â€”"


class DropCard(QWidget):
    """Dashed rounded drop target. Package 7 animates ``breath_phase``."""

    browse_requested = Signal()

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
        self.breath_phase = 0.0  # package 7 hook; no timer here

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.inner, theme.inner, theme.inner, theme.inner)
        layout.setSpacing(theme.outer)
        layout.addStretch(1)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)

        self.title_label = QLabel()
        self.title_label.setProperty("role", "title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel()
        self.subtitle_label.setProperty("role", "caption")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.subtitle_label)

        self.browse_button = text_button(
            t("browse_files", language), theme, self.browse_requested.emit, variant="primary"
        )
        self.browse_button.setFixedWidth(150)
        layout.addWidget(self.browse_button, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch(1)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_theme(theme)

    @Property(bool)
    def dragActive(self) -> bool:  # noqa: N802 - Qt property name
        return self._drag_active

    @dragActive.setter
    def dragActive(self, active: bool) -> None:  # noqa: N802 - Qt property name
        self.set_drag_active(active)

    def set_drag_active(self, active: bool) -> None:
        if active == self._drag_active:
            return
        self._drag_active = active
        self._refresh_text()
        self._refresh_icon()
        self.update()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._refresh_text()
        self._refresh_icon()
        self.update()

    def _refresh_text(self) -> None:
        key = "drag_active" if self._drag_active else "drop_title"
        self.title_label.setText(t(key, self._language))
        self.subtitle_label.setText(t("drop_sub", self._language))
        self.browse_button.setText(t("browse_files", self._language))

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

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            QColor(theme.color("surface_drop_hover" if self._drag_active else "surface"))
        )
        painter.drawRoundedRect(rect, radius, radius)

        pen = QPen(QColor(theme.color("accent" if self._drag_active else "border")))
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

    def rowCount(self, parent: QModelIndex = _INVALID_INDEX) -> int:
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        if role == self.ItemRole:
            return item
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return str(item.path)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
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
        self.set_theme(self._theme)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._colors = {}
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

    def remove_rect(self, rect: QRectF) -> QRectF:
        row = self.row_rect(rect)
        size = 22.0
        return QRectF(row.right() - 10 - size, row.center().y() - size / 2, size, size)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
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

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
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

        # Right-side zones: remove, status pill, readiness pill, meta.
        remove = self.remove_rect(QRectF(option.rect))
        right = remove.left() - 8
        center_y = row.center().y()

        status_text = owner.tr(f"status_{item.status}")
        status_width = self.fm_badge.horizontalAdvance(status_text) + 16
        status_rect = QRectF(right - status_width, center_y - 10, status_width, 20)
        right = status_rect.left() - 6

        readiness_text, readiness_token = self._readiness(item)
        readiness_width = self.fm_badge.horizontalAdvance(readiness_text) + 16
        readiness_rect = QRectF(right - readiness_width, center_y - 10, readiness_width, 20)
        right = readiness_rect.left() - 10

        text_left = check.right() + 12
        meta = _format_meta(item)
        meta_width = min(140.0, self.fm_caption.horizontalAdvance(meta))
        if meta_width < 40:
            meta_width = 0.0
        text_right = right - (meta_width + 12 if meta_width else 0.0)
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

        if meta_width:
            painter.setPen(self.color("muted"))
            painter.drawText(
                QRectF(right - meta_width, center_y - 8, meta_width, 16),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                meta,
            )

        self._draw_pill(painter, readiness_rect, readiness_text, readiness_token)
        self._draw_pill(painter, status_rect, status_text, owner.status_token(item.status))

        if owner.hover_remove == index.row() and not owner.busy:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.color("surface_hover"))
            painter.drawRoundedRect(remove, radius, radius)
            painter.setFont(self.font_caption)
            painter.setPen(self.color("muted"))
            painter.drawText(remove, int(Qt.AlignmentFlag.AlignCenter), "âœ•")

        painter.restore()

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
        self._readiness_cache: dict[str, tuple[int, str, ReadinessReport]] = {}

        self._storage = QSettings("FPSPatcherStudio", "QtUI")
        stored_preview = getattr(settings, "preview_player", None)
        if stored_preview is None:
            stored_preview = self._storage.value("ui/preview_player", False, type=bool)
        self._preview_on = bool(stored_preview)
        settings.preview_player = self._preview_on

        self.setObjectName("QueueView")
        self.setAcceptDrops(True)
        self._build_ui()
        self._theme_manager.changed.connect(self.set_theme)
        self.set_theme(self._theme)
        self.refresh()

    # ---------- public API ----------
    def refresh(self) -> None:
        items = self.controller.items.items
        self.model.refresh()
        self._prune_readiness(items)
        if self._focused_path is not None and not any(i.path == self._focused_path for i in items):
            self._focused_path = None
        has_items = bool(items)
        self.drop_card.setVisible(not has_items)
        self.summary_label.setVisible(has_items)
        self.list_view.setVisible(has_items)
        self.summary_label.setText(self.tr("queue_collapsed", count=len(items)))
        self.retry_button.setVisible(any(i.status in ("failed", "skipped") for i in items))
        self._sync_footer()
        self._sync_controls()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._sync_controls()
        self.list_view.viewport().update()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.drop_card.set_theme(theme)
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
        self.update()

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

    def tr(self, key: str, **kwargs: object) -> str:
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
        elif chosen is move_up:
            self._move_item(item.path, -1)
        elif chosen is move_down:
            self._move_item(item.path, 1)

    def _open_path(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError:
            pass

    # ---------- view events ----------
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt naming
        if watched is not self.list_view.viewport():
            return super().eventFilter(watched, event)
        kind = event.type()
        if kind == QEvent.Type.MouseMove:
            self._update_hover(event.position().toPoint())
        elif kind == QEvent.Type.Leave:
            self.hover_row = -1
            self.hover_remove = -1
            self.list_view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            self.list_view.viewport().update()
        elif kind == QEvent.Type.MouseButtonPress:
            mouse = event
            if mouse.button() == Qt.MouseButton.LeftButton:
                return self._handle_click(mouse.position().toPoint())
        elif kind == QEvent.Type.MouseButtonDblClick:
            mouse = event
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
        if self.delegate.remove_rect(rect).contains(pos):
            self._remove_item(item.path)
            return True
        if self.delegate.checkbox_rect(rect).contains(pos):
            self._toggle_item(item, index.row())
            return True
        self._focus_row(index.row(), open_player=self._preview_on)
        return True

    def _update_hover(self, pos: QPoint) -> None:
        index = self.list_view.indexAt(pos)
        if not index.isValid():
            changed = self.hover_row != -1
            self.hover_row = -1
            self.hover_remove = -1
            self.list_view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            if changed:
                self.list_view.viewport().update()
            return
        rect = QRectF(self.list_view.visualRect(index))
        over_remove = self.delegate.remove_rect(rect).contains(pos)
        over_check = self.delegate.checkbox_rect(rect).contains(pos)
        changed = (self.hover_row, self.hover_remove) != (
            index.row(),
            index.row() if over_remove else -1,
        )
        self.hover_row = index.row()
        self.hover_remove = index.row() if over_remove else -1
        interactive = over_remove or over_check
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
