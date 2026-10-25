"""Qt-only motion helpers: easing, fades, height slides, glow and button fades."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import (
    Property,
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRectF,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPaintEvent
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QProgressBar,
    QPushButton,
    QWidget,
)

from .theme import Theme

EASE_OUT_CUBIC = QEasingCurve(QEasingCurve.Type.OutCubic)

_BUTTON_VARIANTS = frozenset({"primary", "secondary", "ghost", "icon"})
_TRANSPARENT = QColor(0, 0, 0, 0)


def _settings_of(source: object) -> object:
    return getattr(source, "settings", source)


def _reduce_motion(source: object) -> bool:
    return bool(getattr(_settings_of(source), "reduce_motion", False))


def duration(widget_or_settings: object, ms: int) -> int:
    """Return 0 when Reduce Motion is on for the widget's settings."""
    return 0 if _reduce_motion(widget_or_settings) else max(0, int(ms))


def animate(
    widget: QObject,
    prop: bytes,
    start: Any,
    end: Any,
    ms: int,
    parent: QObject | None = None,
) -> QPropertyAnimation:
    """Animate a Qt property, snapping to the end state under Reduce Motion."""
    animation = QPropertyAnimation(widget, prop, parent or widget)
    animation.setEasingCurve(EASE_OUT_CUBIC)
    if ms <= 0 or _reduce_motion(widget):
        animation.setDuration(0)
        animation.setStartValue(end)
        animation.setEndValue(end)
        widget.setProperty(prop.decode("ascii"), end)
        animation.start()
        return animation
    animation.setDuration(int(ms))
    animation.setStartValue(start)
    animation.setEndValue(end)
    animation.start()
    return animation


def animate_height(
    widget: QWidget,
    start: int,
    end: int,
    ms: int,
    reduce_motion: bool,
    on_finished: Callable[[], None] | None = None,
) -> QParallelAnimationGroup:
    """Slide minimum/maximum height together; the end state is always committed."""
    group = QParallelAnimationGroup(widget)
    for prop in (b"minimumHeight", b"maximumHeight"):
        animation = QPropertyAnimation(widget, prop, group)
        animation.setEasingCurve(EASE_OUT_CUBIC)
        animation.setStartValue(int(start))
        animation.setEndValue(int(end))
        animation.setDuration(0 if reduce_motion else max(0, int(ms)))
        group.addAnimation(animation)

    def settle() -> None:
        widget.setMinimumHeight(int(end))
        widget.setMaximumHeight(int(end))
        if on_finished is not None:
            on_finished()

    if reduce_motion or ms <= 0 or start == end:
        settle()
        return group
    group.finished.connect(settle)
    group.finished.connect(lambda: group.deleteLater())
    group.start()
    return group


def fade(
    widget: QWidget,
    start: float,
    end: float,
    ms: int,
    reduce_motion: bool,
    on_finished: Callable[[], None] | None = None,
) -> QPropertyAnimation | None:
    """Fade via a temporary opacity effect that is removed on finish."""
    if reduce_motion or ms <= 0:
        if isinstance(widget.graphicsEffect(), QGraphicsOpacityEffect):
            widget.setGraphicsEffect(None)
        if on_finished is not None:
            on_finished()
        return None

    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    effect.setOpacity(float(start))

    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(max(0, int(ms)))
    animation.setStartValue(float(start))
    animation.setEndValue(float(end))
    animation.setEasingCurve(EASE_OUT_CUBIC)

    def finish() -> None:
        effect.setEnabled(False)
        widget.setGraphicsEffect(None)
        if on_finished is not None:
            on_finished()
        animation.deleteLater()

    animation.finished.connect(finish)
    animation.start()
    return animation


def fade_in(
    widget: QWidget, ms: int = 140, reduce_motion: bool = False
) -> QPropertyAnimation | None:
    """Fade a widget in; the opacity effect never outlives the animation."""
    return fade(widget, 0.0, 1.0, ms, reduce_motion)


class MotionProgressBar(QProgressBar):
    """Progress bar with a 300 ms value slide and a moving busy highlight."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme: Theme | None = None
        self._busy = False
        self._reduce_motion = False
        self._offset = 0.0
        self._value_anim: QPropertyAnimation | None = None
        self._highlight = QVariantAnimation(self)
        self._highlight.setStartValue(0.0)
        self._highlight.setEndValue(1.0)
        self._highlight.setDuration(1500)
        self._highlight.setLoopCount(-1)
        self._highlight.setEasingCurve(QEasingCurve(QEasingCurve.Type.Linear))
        self._highlight.valueChanged.connect(self._set_offset)

    @Property(float)
    def offset(self) -> float:  # noqa: N802 - Qt property name
        return self._offset

    @offset.setter
    def offset(self, value: float) -> None:  # noqa: N802 - Qt property name
        self._set_offset(value)

    def _set_offset(self, value: object) -> None:
        self._offset = float(value)
        if self._busy and not self._reduce_motion:
            self.update()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def set_reduce_motion(self, enabled: bool) -> None:
        self._reduce_motion = bool(enabled)
        if self._reduce_motion:
            self.stop()
        elif self._busy and self.isVisible():
            self._highlight.start()

    def set_busy(self, busy: bool) -> None:
        busy = bool(busy)
        if busy == self._busy:
            if (
                busy
                and not self._reduce_motion
                and self.isVisible()
                and self._highlight.state() != QAbstractAnimation.State.Running
            ):
                self._highlight.start()
            return
        self._busy = busy
        if busy and not self._reduce_motion and self.isVisible():
            self._highlight.start()
        else:
            self._highlight.stop()
            self._offset = 0.0
        self.update()

    def animate_value(self, value: int, ms: int = 300) -> None:
        target = int(value)
        if self._value_anim is not None:
            self._value_anim.stop()
            self._value_anim.deleteLater()
            self._value_anim = None
        if self._reduce_motion or ms <= 0 or target == self.value():
            self.setValue(target)
            return
        animation = QPropertyAnimation(self, b"value", self)
        animation.setDuration(int(ms))
        animation.setStartValue(self.value())
        animation.setEndValue(target)
        animation.setEasingCurve(EASE_OUT_CUBIC)

        def finish() -> None:
            self._value_anim = None
            animation.deleteLater()

        animation.finished.connect(finish)
        self._value_anim = animation
        animation.start()

    def stop(self) -> None:
        if self._value_anim is not None:
            self._value_anim.stop()
            self._value_anim.deleteLater()
            self._value_anim = None
        self._highlight.stop()
        self._offset = 0.0

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not self._busy or self._reduce_motion or self._theme is None or self.value() <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if rect.width() <= 0 or rect.height() <= 0:
            painter.end()
            return
        ratio = (self.value() - self.minimum()) / max(1, self.maximum() - self.minimum())
        fill = QRectF(rect.left(), rect.top(), rect.width() * ratio, rect.height())
        if fill.width() <= 0:
            painter.end()
            return

        clip = QPainterPath()
        clip.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setClipPath(clip)
        painter.setClipRect(fill, Qt.ClipOperation.IntersectClip)

        width = max(10.0, rect.height() * 3.0)
        x = fill.left() + (fill.width() + width) * self._offset - width
        gradient = QLinearGradient(x, 0, x + width, 0)
        glow = QColor(self._theme.color("accent_light"))
        glow.setAlpha(110)
        clear = QColor(glow)
        clear.setAlpha(0)
        gradient.setColorAt(0.0, clear)
        gradient.setColorAt(0.5, glow)
        gradient.setColorAt(1.0, clear)
        painter.fillRect(QRectF(x, rect.top(), width, rect.height()), gradient)
        painter.end()


@dataclass
class _ButtonState:
    base: str
    hovered: bool = False
    pressed: bool = False
    target: str = "normal"
    current: tuple[QColor, QColor, QColor] | None = None
    animation: QVariantAnimation | None = field(default=None, repr=False)


class MotionController(QObject):
    """App-wide hover/press fades for variant buttons, plus a global stop switch."""

    def __init__(
        self,
        reduce_motion: bool = False,
        theme: Theme | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._reduce_motion = bool(reduce_motion)
        self._theme = theme
        self._states: dict[QPushButton, _ButtonState] = {}
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    @property
    def reduce_motion(self) -> bool:
        return self._reduce_motion

    def set_reduce_motion(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._reduce_motion:
            return
        self._reduce_motion = enabled
        if enabled:
            self.stop_all()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._restore_buttons()

    def stop_all(self) -> None:
        """Stop every animation owned by a widget and restore button styles."""
        self._restore_buttons()
        app = QApplication.instance()
        if app is not None:
            for animation in app.findChildren(QAbstractAnimation):
                animation.stop()
            for widget in app.allWidgets():
                if isinstance(widget.graphicsEffect(), QGraphicsOpacityEffect):
                    widget.setGraphicsEffect(None)

    def _restore_buttons(self) -> None:
        for button, state in list(self._states.items()):
            if state.animation is not None:
                state.animation.stop()
                state.animation.deleteLater()
                state.animation = None
            button.setStyleSheet(state.base)
            state.current = None
            state.target = "normal"
            state.hovered = False
            state.pressed = False
        self._states.clear()

    def _palette(self, variant: str, state: str) -> tuple[QColor, QColor, QColor] | None:
        if self._theme is None:
            return None
        color = self._theme.color
        if variant == "primary":
            background = {
                "normal": color("accent"),
                "hover": color("accent_hover"),
                "pressed": color("accent_pressed"),
            }[state]
            return QColor(background), QColor(background), QColor(color("on_accent"))
        if variant == "secondary":
            background = {
                "normal": color("surface"),
                "hover": color("surface_hover"),
                "pressed": color("surface_raised"),
            }[state]
            border = color("border_hover") if state == "hover" else color("border")
            return QColor(background), QColor(border), QColor(color("text"))
        if variant == "ghost":
            background = {
                "normal": _TRANSPARENT,
                "hover": QColor(color("surface_hover")),
                "pressed": QColor(color("surface_raised")),
            }[state]
            text = color("text") if state != "normal" else color("text2")
            return background, _TRANSPARENT, QColor(text)
        if variant == "icon":
            background = {
                "normal": _TRANSPARENT,
                "hover": QColor(color("surface_hover")),
                "pressed": QColor(color("surface_raised")),
            }[state]
            border = _TRANSPARENT if state == "normal" else QColor(color("border"))
            return background, border, QColor(color("text"))
        return None

    def _stylesheet(self, background: QColor, border: QColor, text: QColor) -> str:
        radius = self._theme.radii.control if self._theme is not None else 8
        return (
            "QPushButton {"
            f"background: {self._css_color(background)};"
            f"border: 1px solid {self._css_color(border)};"
            f"border-radius: {radius}px;"
            f"color: {self._css_color(text)};"
            "}"
        )

    @staticmethod
    def _css_color(color: QColor) -> str:
        if color.alpha() == 0:
            return "transparent"
        if color.alpha() < 255:
            return (
                f"rgba({color.red()}, {color.green()}, {color.blue()}, "
                f"{color.alphaF():.3f})"
            )
        return color.name()

    @staticmethod
    def _blend(start: QColor, end: QColor, progress: float) -> QColor:
        return QColor(
            round(start.red() + (end.red() - start.red()) * progress),
            round(start.green() + (end.green() - start.green()) * progress),
            round(start.blue() + (end.blue() - start.blue()) * progress),
            round(start.alpha() + (end.alpha() - start.alpha()) * progress),
        )

    def _animate_button(
        self, button: QPushButton, state: _ButtonState, target: str
    ) -> None:
        variant = str(button.property("variant"))
        colors = self._palette(variant, target)
        normal = self._palette(variant, "normal")
        if colors is None or normal is None:
            return
        if state.animation is not None:
            is_running = state.animation.state() == QAbstractAnimation.State.Running
            if is_running and state.target == target:
                return
            state.animation.stop()
            state.animation.deleteLater()
            state.animation = None
        if state.target == target and state.current is not None:
            return

        start = state.current or normal
        animation = QVariantAnimation(self)
        animation.setDuration(120)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(EASE_OUT_CUBIC)
        state.target = target

        def step(value: object) -> None:
            progress = float(value)
            background = self._blend(start[0], colors[0], progress)
            border = self._blend(start[1], colors[1], progress)
            text = self._blend(start[2], colors[2], progress)
            state.current = (background, border, text)
            button.setStyleSheet(
                state.base + self._stylesheet(background, border, text)
            )

        def finish() -> None:
            state.animation = None
            if target == "normal":
                button.setStyleSheet(state.base)
                state.current = None
            else:
                state.current = colors
            animation.deleteLater()

        animation.valueChanged.connect(step)
        animation.finished.connect(finish)
        state.animation = animation
        animation.start()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt naming
        kind = event.type()
        if kind == QEvent.Type.Destroy and isinstance(watched, QPushButton):
            state = self._states.pop(watched, None)
            if state is not None and state.animation is not None:
                state.animation.stop()
                state.animation.deleteLater()
                state.animation = None
            return False
        if not isinstance(watched, QPushButton):
            return False
        if self._reduce_motion or bool(watched.property("motionSkip")):
            return False
        variant = watched.property("variant")
        if variant not in _BUTTON_VARIANTS:
            return False

        state = self._states.get(watched)
        if kind == QEvent.Type.EnabledChange and not watched.isEnabled():
            if state is not None:
                self._animate_button(watched, state, "normal")
            return False
        if not watched.isEnabled():
            return False
        if kind == QEvent.Type.Enter:
            if state is None:
                state = _ButtonState(base=watched.styleSheet())
                self._states[watched] = state
            state.hovered = True
            self._animate_button(watched, state, "pressed" if state.pressed else "hover")
        elif kind == QEvent.Type.Leave:
            if state is not None:
                state.hovered = False
                state.pressed = False
                self._animate_button(watched, state, "normal")
        elif kind == QEvent.Type.MouseButtonPress:
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            if state is None:
                state = _ButtonState(base=watched.styleSheet())
                self._states[watched] = state
            state.pressed = True
            self._animate_button(watched, state, "pressed")
        elif kind == QEvent.Type.MouseButtonRelease:
            if event.button() != Qt.MouseButton.LeftButton or state is None:
                return False
            state.pressed = False
            self._animate_button(watched, state, "hover" if state.hovered else "normal")
        return False
