"""Qt icon loading from the existing dual-mode 32x32 RGBA PNG assets."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

_ASSETS = Path(__file__).resolve().parent.parent / "ui" / "assets"
_CACHE: dict[tuple[str, bool, str], QIcon] = {}


def icon_path(name: str, dark: bool) -> Path:
    mode = "dark" if dark else "light"
    return _ASSETS / f"{name}_{mode}.png"


def get_icon(name: str, dark: bool, tint: str | None = None) -> QIcon:
    """Return a cached QIcon, or an empty QIcon when the asset is missing."""
    key = (name, dark, tint or "")
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    path = icon_path(name, dark)
    result = QIcon()
    if path.is_file():
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            if tint:
                painter = QPainter(pixmap)
                painter.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_SourceIn
                )
                painter.fillRect(pixmap.rect(), QColor(tint))
                painter.end()
            result = QIcon(pixmap)
    _CACHE[key] = result
    return result


def clear_icon_cache() -> None:
    _CACHE.clear()
