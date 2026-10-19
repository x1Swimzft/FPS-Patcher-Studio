"""Icon asset loader and memory cache for CustomTkinter UI."""

from __future__ import annotations

import logging
from pathlib import Path

import customtkinter as ctk
from PIL import Image

_log = logging.getLogger(__name__)

_ASSETS_DIR = Path(__file__).with_name("assets")
_ICON_CACHE: dict[tuple[str, tuple[int, int], bool], ctk.CTkImage] = {}


def get_icon(
    name: str,
    size: tuple[int, int] = (16, 16),
    *,
    force_dark: bool = False,
) -> ctk.CTkImage | None:
    """Load a dual-mode (light/dark) icon and return as a cached CTkImage.

    Looks up ``<name>_light.png`` and ``<name>_dark.png`` in ``ui/assets/``.
    Returns ``None`` safely if loading fails.
    """
    cache_key = (name, (size[0], size[1]), force_dark)
    if cache_key in _ICON_CACHE:
        return _ICON_CACHE[cache_key]

    light_path = _ASSETS_DIR / f"{name}_light.png"
    dark_path = _ASSETS_DIR / f"{name}_dark.png"

    if not light_path.is_file() or not dark_path.is_file():
        _log.debug("Icon files missing for %r: %s, %s", name, light_path, dark_path)
        return None

    try:
        with Image.open(light_path) as limg:
            light_image = limg.copy()
        with Image.open(dark_path) as dimg:
            dark_image = dimg.copy()

        icon = ctk.CTkImage(
            light_image=dark_image if force_dark else light_image,
            dark_image=dark_image,
            size=(size[0], size[1]),
        )
        _ICON_CACHE[cache_key] = icon
        return icon
    except Exception as exc:
        _log.warning("Failed to load icon %r: %s", name, exc)
        return None


def clear_icon_cache() -> None:
    """Clear in-memory icon cache."""
    _ICON_CACHE.clear()
