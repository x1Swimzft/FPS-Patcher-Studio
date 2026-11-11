"""Small shared Qt widgets used by the shell, inspector, queue and settings."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    Property,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPaintEvent,
    QPen,
    QTextLayout,
    QTextOption,
)
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
from .motion import animate, fade_in
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
    label = QLabel(text)
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
    """An inset-grouped row: label on the left, value/popup on the right."""

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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.spacing)
        self.label = QLabel(label)
        self.label.setProperty("role", "caption")
        layout.addWidget(self.label)
        layout.addStretch(1)
        self.right = right
        if right is not None:
            layout.addWidget(right, 0, Qt.AlignmentFlag.AlignVCenter)
        # Tall enough for Thai line boxes at the L scale without wasting space.
        self.setFixedHeight(max(40, theme.fonts.body + 26))
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
    """Caption above a flat body; the surrounding inspector is the card."""

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
        self.caption.setStyleSheet(f"color: {theme.color('muted')};")
        self.card.setStyleSheet(
            "QFrame#Card { background: transparent; border: none; }"
        )
        for row in self._rows:
            row.set_theme(theme)


class CollapsibleSection(QFrame):
    """Card with a clickable header and a body that fades in on expand."""

    toggled = Signal(bool)

    def __init__(
        self,
        title: str,
        theme: Theme,
        *,
        expanded: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._theme = theme
        self._expanded = bool(expanded)
        self.reduce_motion = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = QPushButton(title, self)
        self.header.setObjectName("SectionHeader")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.header.setIconSize(QSize(12, 12))
        self.header.clicked.connect(self.toggle)
        layout.addWidget(self.header)

        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(
            theme.inner, theme.outer, theme.inner, theme.outer
        )
        self.body_layout.setSpacing(theme.outer)
        layout.addWidget(self.body)
        self.set_theme(theme)

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool, *, emit: bool = True) -> None:
        expanded = bool(expanded)
        changed = expanded != self._expanded
        self._expanded = expanded
        self._sync(animate=changed)
        if changed and emit:
            self.toggled.emit(expanded)

    def set_reduce_motion(self, enabled: bool) -> None:
        self.reduce_motion = bool(enabled)

    def _sync(self, *, animate: bool = False) -> None:
        self.body.setVisible(self._expanded)
        if self._expanded and animate:
            fade_in(self.body, 160, self.reduce_motion)
        self.header.setProperty("expanded", "true" if self._expanded else "false")
        self.header.setIcon(
            get_icon(
                "chevron_down" if self._expanded else "chevron_right",
                self._theme.is_dark,
            )
        )
        repolish(self.header)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.setStyleSheet(
            "QFrame#Card {"
            f"background: {theme.color('surface')};"
            f"border: 1px solid {theme.color('border')};"
            f"border-radius: {theme.card_radius}px;"
            "}"
        )
        self._sync()


class SettingRow(QWidget):
    """Label and optional hint on the left, one control on the right."""

    def __init__(
        self,
        label: str,
        theme: Theme,
        control: QWidget | None = None,
        *,
        hint: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.inner, theme.outer, theme.inner, theme.outer)
        layout.setSpacing(theme.spacing)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        self.label = QLabel(label, self)
        self.label.setWordWrap(True)
        self.hint = QLabel(hint, self)
        self.hint.setProperty("role", "muted")
        self.hint.setWordWrap(True)
        self.hint.setVisible(bool(hint))
        text.addWidget(self.label)
        text.addWidget(self.hint)
        layout.addLayout(text, 1)

        self.control = control
        if control is not None:
            layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
            self.label.setCursor(Qt.CursorShape.PointingHandCursor)
            self.label.installEventFilter(self)

        self.setMinimumHeight(max(40, theme.fonts.body + 26))
        self._line = hairline(theme)
        self._line.setParent(self)
        self._line.setGeometry(0, self.height() - 1, self.width(), 1)
        self._line.show()
        self.set_theme(theme)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.label
            and event.type() == QEvent.Type.MouseButtonRelease
            and isinstance(self.control, QAbstractButton)
        ):
            self.control.click()
        return super().eventFilter(watched, event)

    def set_last(self, last: bool = True) -> None:
        self._line.setVisible(not last)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._line.setGeometry(0, self.height() - 1, self.width(), 1)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._line.setStyleSheet(f"background: {theme.color('border')}; border: none;")


class ConsequenceBadge(QFrame):
    """One-line semantic callout for a safety consequence."""

    _TOKENS = {
        "lossless": "success",
        "warning": "warn",
        "danger": "danger",
        "neutral": "text2",
    }

    def __init__(
        self,
        text: str,
        kind: str,
        theme: Theme,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if kind not in self._TOKENS:
            raise ValueError(f"unknown consequence kind: {kind!r}")
        self.kind = kind
        self.setObjectName("ConsequenceBadge")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.inner, theme.outer, theme.inner, theme.outer)
        self.label = WrapLabel(text, self)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.setAccessibleName(text)
        self.set_theme(theme)

    def set_state(self, text: str, kind: str, theme: Theme) -> None:
        """Replace the badge text and semantic kind in place."""
        if kind not in self._TOKENS:
            raise ValueError(f"unknown consequence kind: {kind!r}")
        self.kind = kind
        self.label.setText(text)
        self.setAccessibleName(text)
        self.set_theme(theme)

    def set_theme(self, theme: Theme) -> None:
        color = theme.color(self._TOKENS[self.kind])
        tint = QColor(color)
        tint.setAlphaF(0.10)
        fill = f"rgba({tint.red()}, {tint.green()}, {tint.blue()}, 0.10)"
        self.setStyleSheet(
            "QFrame#ConsequenceBadge {"
            f"background: {fill};"
            f"border: 1px solid {color};"
            f"border-radius: {theme.control_radius}px;"
            "}"
            "QLabel {"
            f"color: {color};"
            "background: transparent;"
            "border: none;"
            "}"
        )


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


class WrapLabel(QLabel):
    """Word-wrapped label that can break long unspaced Thai text."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setMinimumWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt naming
        return True

    def _layout(self, width: int) -> QTextLayout:
        layout = QTextLayout(self.text(), self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        y = 0.0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1, width))
            natural = line.naturalTextWidth()
            alignment = self.alignment()
            if alignment & Qt.AlignmentFlag.AlignHCenter:
                x = (width - natural) / 2
            elif alignment & Qt.AlignmentFlag.AlignRight:
                x = width - natural
            else:
                x = 0.0
            line.setPosition(QPointF(x, y))
            y += line.height()
        layout.endLayout()
        return layout

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt naming
        height = self._layout(width).boundingRect().height()
        return max(self.fontMetrics().height(), int(round(height)))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(1, self.fontMetrics().height())

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        natural = self.fontMetrics().horizontalAdvance(self.text()) + 2
        width = min(max(1, natural), 600)
        return QSize(width, self.heightForWidth(width))

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.translate(self.contentsRect().topLeft())
        self._layout(self.contentsRect().width()).draw(painter, QPointF(0, 0))
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
        self._thumb_anim: QPropertyAnimation | None = None
        self.reduce_motion = False
        self.setFixedHeight(theme.segmented_height)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(" / ".join(items))

    @property
    def value(self) -> str:
        return self._items[self._index] if self._items else ""

    @Property(float)
    def thumbPosition(self) -> float:  # noqa: N802 - Qt property name
        return self._thumb

    @thumbPosition.setter  # type: ignore[no-redef]
    def thumbPosition(self, position: float) -> None:  # noqa: N802 - Qt property name
        self._thumb = float(position)
        self.update()

    def set_reduce_motion(self, enabled: bool) -> None:
        self.reduce_motion = bool(enabled)

    def _stop_thumb(self) -> None:
        if self._thumb_anim is not None:
            self._thumb_anim.stop()
            self._thumb_anim.deleteLater()
            self._thumb_anim = None

    def set_items(self, items: list[str], value: str | None = None) -> None:
        self._items = list(items)
        if value in self._items:
            self._index = self._items.index(value)
        self._index = max(0, min(self._index, len(self._items) - 1))
        self._stop_thumb()
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
        self._stop_thumb()
        if self.reduce_motion or index == self._thumb:
            self._thumb = float(index)
            self.update()
        else:
            self._thumb_anim = animate(
                self, b"thumbPosition", self._thumb, float(index), 180
            )
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
            rect.left() + width * self._thumb + 2,
            rect.top() + 2,
            width - 4,
            rect.height() - 4,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.color("surface_hover")))
        painter.drawRoundedRect(thumb, max(2, radius - 2), max(2, radius - 2))

        font = QFont(self.font())
        font.setPixelSize(theme.fonts.body)
        for index, item in enumerate(self._items):
            area = QRectF(rect.left() + width * index, rect.top(), width, rect.height())
            selected = index == self._index
            font.setWeight(
                QFont.Weight.DemiBold if selected else QFont.Weight.Medium
            )
            painter.setFont(font)
            painter.setPen(QColor(theme.color("text" if selected else "text2")))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, item)

        if self.hasFocus():
            focus = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            painter.setPen(QPen(QColor(theme.color("border_focus")), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(focus, radius, radius)
        painter.end()


class Switch(QAbstractButton):
    """40x22 toggle switch with a semantic accent track."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._offset = 1.0 if self.isChecked() else 0.0
        self._offset_anim: QPropertyAnimation | None = None
        self.reduce_motion = False
        self.setCheckable(True)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.toggled.connect(self._animate_thumb)

    @Property(float)
    def thumbOffset(self) -> float:  # noqa: N802 - Qt property name
        return self._offset

    @thumbOffset.setter  # type: ignore[no-redef]
    def thumbOffset(self, value: float) -> None:  # noqa: N802 - Qt property name
        self._offset = float(value)
        self.update()

    def set_reduce_motion(self, enabled: bool) -> None:
        self.reduce_motion = bool(enabled)

    def _animate_thumb(self, checked: bool) -> None:
        target = 1.0 if checked else 0.0
        if self._offset == target:
            return
        if self._offset_anim is not None:
            self._offset_anim.stop()
            self._offset_anim.deleteLater()
        self._offset_anim = animate(self, b"thumbOffset", self._offset, target, 140)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        theme = self._theme
        checked = self.isChecked()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.setPen(
            QPen(QColor(theme.color("accent" if checked else "border_control")), 1)
        )
        painter.setBrush(
            QColor(theme.color("accent" if checked else "surface_hover"))
        )
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        diameter = track.height() - 4
        x = track.left() + 2 + (track.width() - diameter - 5) * self._offset
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            QColor(theme.color("on_accent" if checked else "text2"))
        )
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
