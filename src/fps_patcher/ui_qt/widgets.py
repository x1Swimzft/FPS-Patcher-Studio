"""Small shared Qt widgets used by the shell, inspector, queue and settings."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .icons import get_icon
from .theme import Theme


def repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_prop(widget: QWidget, name: str, value: object) -> None:
    widget.setProperty(name, value)
    repolish(widget)


def text_role(label: QLabel, role: str) -> QLabel:
    label.setProperty("role", role)
    return label


def card_caption(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setProperty("role", "cardCaption")
    return label


def hairline(theme: Theme) -> QFrame:
    line = QFrame()
    line.setObjectName("Hairline")
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {theme.color('border')}; border: none;")
    return line


def icon_button(
    name: str,
    tooltip: str,
    theme: Theme,
    on_click: Callable[[], None] | None = None,
    *,
    accessible_name: str | None = None,
    parent: QWidget | None = None,
) -> QPushButton:
    button = QPushButton(parent)
    button.setProperty("variant", "icon")
    button.setIcon(get_icon(name, theme.is_dark))
    button.setIconSize(QSize(16, 16))
    button.setFixedSize(theme.icon_button_size, theme.icon_button_size)
    button.setToolTip(tooltip)
    button.setAccessibleName(accessible_name or tooltip)
    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    if on_click is not None:
        button.clicked.connect(on_click)
    return button


def text_button(
    text: str,
    theme: Theme,
    on_click: Callable[[], None] | None = None,
    *,
    variant: str = "secondary",
    height: int | None = None,
) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("variant", variant)
    if height is not None:
        button.setFixedHeight(height)
    else:
        button.setMinimumHeight(
            theme.primary_height if variant == "primary" else theme.button_height
        )
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    if on_click is not None:
        button.clicked.connect(on_click)
    return button


class Card(QFrame):
    """Rounded inset card with a vertical body layout."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        self.set_theme(theme)

    def set_theme(self, theme: Theme) -> None:
        self.setStyleSheet(
            "QFrame#Card {"
            f"background: {theme.color('surface')};"
            f"border: 1px solid {theme.color('border')};"
            f"border-radius: {theme.card_radius}px;"
            "}"
        )


class InsetRow(QWidget):
    """A 32px inset-grouped row: label on the left, value/popup on the right."""

    def __init__(
        self,
        label: str,
        theme: Theme,
        right: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.inner, 0, theme.inner, 0)
        layout.setSpacing(theme.spacing)
        self.label = QLabel(label)
        self.label.setProperty("role", "caption")
        layout.addWidget(self.label)
        layout.addStretch(1)
        self.right = right
        if right is not None:
            layout.addWidget(right, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setFixedHeight(32)
        self._line = hairline(theme)
        self._line.setParent(self)
        self._line.setGeometry(0, 31, self.width(), 1)
        self._line.show()
        self.set_theme(theme)

    def set_last(self, last: bool = True) -> None:
        self._line.setVisible(not last)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._line.setGeometry(0, self.height() - 1, self.width(), 1)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._line.setStyleSheet(f"background: {theme.color('border')}; border: none;")


class CardGroup(QWidget):
    """Uppercase caption above a rounded inset card."""

    def __init__(self, caption: str, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.outer)
        self.caption = card_caption(caption)
        layout.addWidget(self.caption)
        self.card = Card(theme)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        self.card.body.addLayout(self.body)
        layout.addWidget(self.card)
        self._rows: list[InsetRow] = []

    def add_row(self, label: str, right: QWidget | None = None) -> InsetRow:
        if self._rows:
            self._rows[-1].set_last(True)
        row = InsetRow(label, self._theme, right, self.card)
        self._rows.append(row)
        self.body.addWidget(row)
        return row

    def finish(self) -> None:
        if self._rows:
            self._rows[-1].set_last(True)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.caption.setStyleSheet(f"color: {theme.color('text2')};")
        self.card.set_theme(theme)
        for row in self._rows:
            row.set_theme(theme)


class ElidedLabel(QLabel):
    """Single-line label that elides instead of forcing a wide layout."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        super().setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        self._full = text
        self.setToolTip(text)
        self.update()

    def fullText(self) -> str:  # noqa: N802 - Qt naming
        return self._full

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setPen(QColor(self.palette().color(self.foregroundRole())))
        painter.setFont(self.font())
        text = self.fontMetrics().elidedText(
            self._full, Qt.TextElideMode.ElideRight, max(0, self.width())
        )
        painter.drawText(self.rect(), int(self.alignment()), text)
        painter.end()


class SegmentedControl(QWidget):
    """Compact macOS-style segmented control with a sliding thumb."""

    valueChanged = Signal(str)

    def __init__(
        self,
        items: list[str],
        theme: Theme,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._items = list(items)
        self._index = 0
        self._theme = theme
        self._hover = -1
        self._thumb = 0.0
        self.setFixedHeight(theme.segmented_height)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(" / ".join(items))

    @property
    def value(self) -> str:
        return self._items[self._index] if self._items else ""

    def set_items(self, items: list[str], value: str | None = None) -> None:
        self._items = list(items)
        if value in self._items:
            self._index = self._items.index(value)
        self._index = max(0, min(self._index, len(self._items) - 1))
        self._thumb = float(self._index)
        self.setAccessibleName(" / ".join(items))
        self.update()

    def set_value(self, value: str) -> None:
        if value not in self._items:
            return
        index = self._items.index(value)
        if index == self._index:
            return
        self._index = index
        self._thumb = float(index)
        self.valueChanged.emit(value)
        self.update()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not self._items:
            return
        width = self.width() / len(self._items)
        index = max(0, min(len(self._items) - 1, int(event.position().x() // width)))
        self.set_value(self._items[index])
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right) and self._items:
            delta = -1 if event.key() == Qt.Key.Key_Left else 1
            index = max(0, min(len(self._items) - 1, self._index + delta))
            self.set_value(self._items[index])
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event: QPaintEvent) -> None:
        if not self._items:
            return
        theme = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = theme.control_radius
        painter.setPen(QPen(QColor(theme.color("border")), 1))
        painter.setBrush(QColor(theme.color("surface_raised")))
        painter.drawRoundedRect(rect, radius, radius)

        width = rect.width() / len(self._items)
        thumb = QRectF(
            rect.left() + width * self._index + 2,
            rect.top() + 2,
            width - 4,
            rect.height() - 4,
        )
        painter.setPen(QPen(QColor(theme.color("accent_dim_border")), 1))
        painter.setBrush(QColor(theme.color("accent_dim")))
        painter.drawRoundedRect(thumb, max(2, radius - 2), max(2, radius - 2))

        font = QFont(self.font())
        font.setPixelSize(theme.fonts.body)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        for index, item in enumerate(self._items):
            area = QRectF(rect.left() + width * index, rect.top(), width, rect.height())
            painter.setPen(
                QColor(
                    theme.color("accent_light")
                    if index == self._index
                    else theme.color("text2")
                )
            )
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, item)

        if self.hasFocus():
            focus = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            painter.setPen(QPen(QColor(theme.color("border_focus")), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(focus, radius, radius)
        painter.end()


class Switch(QAbstractButton):
    """macOS-style 38x22 toggle switch."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setCheckable(True)
        self.setFixedSize(38, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        theme = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.setPen(QPen(QColor(theme.color("border")), 1))
        painter.setBrush(
            QColor(theme.color("accent") if self.isChecked() else theme.color("surface_hover"))
        )
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        diameter = track.height() - 4
        x = track.right() - diameter - 2 if self.isChecked() else track.left() + 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(x, track.top() + 2, diameter, diameter))
        if self.hasFocus():
            painter.setPen(QPen(QColor(theme.color("border_focus")), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track.adjusted(1, 1, -1, -1), 10, 10)
        painter.end()


class Popover(QFrame):
    """Small popup card anchored above/below a widget."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("Card")
        self._theme = theme
        self.setStyleSheet(
            "QFrame#Card {"
            f"background: {theme.color('surface_raised')};"
            f"border: 1px solid {theme.color('border')};"
            f"border-radius: {theme.card_radius}px;"
            "}"
            "QLabel { background: transparent; }"
        )
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(theme.inner, theme.inner, theme.inner, theme.inner)
        self.body.setSpacing(theme.outer)

    def show_for(self, anchor: QWidget) -> None:
        self.adjustSize()
        pos = anchor.mapToGlobal(
            QPoint(anchor.width() // 2 - self.width() // 2, -self.height() - 6)
        )
        self.move(pos)
        self.show()
