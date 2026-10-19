"""Displays probed video metadata with clean hierarchy and copy-on-click."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from ..core.models import VideoInfo
from .strings import t
from .theme import (
    ThemeTokens,
    font_body,
    font_caption,
    font_section,
    get_theme_manager,
)

FIELD_KEYS = (
    ("FPS", "field_fps"),
    ("Resolution", "field_resolution"),
    ("Codec", "field_codec"),
    ("Duration", "field_duration"),
    ("Timescale", "field_timescale"),
    ("Audio", "field_audio"),
    ("Queue", "field_queue"),
)
FIELDS = tuple(f[0] for f in FIELD_KEYS)


class InfoPanel(ctk.CTkFrame):
    def __init__(self, master: Any) -> None:
        self._theme_mgr = get_theme_manager()
        tokens = self._theme_mgr.tokens
        card_rad, _ = self._radii()

        super().__init__(
            master,
            corner_radius=card_rad,
            fg_color=tokens.surface,
            border_width=1,
            border_color=tokens.border,
        )
        self.grid_columnconfigure(1, weight=1)

        lang = self._lang()
        fsize = self._fsize()

        self.header_label = ctk.CTkLabel(
            self,
            text=t("source_metadata", lang),
            font=font_section(fsize),
            text_color=tokens.text,
        )
        self.header_label.grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 2))

        self._labels: dict[str, ctk.CTkLabel] = {}
        self._values: dict[str, ctk.CTkLabel] = {}
        row_idx = 1
        for name, key in FIELD_KEYS:
            lbl = ctk.CTkLabel(
                self,
                text=t(key, lang),
                font=font_caption(fsize),
                text_color=tokens.muted,
            )
            lbl.grid(row=row_idx, column=0, sticky="w", padx=(12, 8), pady=1)
            self._labels[name] = lbl

            val = ctk.CTkLabel(
                self,
                text=t("empty_val", lang),
                font=font_body(bold=(name == "FPS"), size_opt=fsize),
                text_color=tokens.text,
                anchor="e",
            )
            val.grid(row=row_idx, column=1, sticky="e", padx=(0, 12), pady=1)
            self._values[name] = val
            row_idx += 1

        self.files_count = ctk.CTkLabel(
            self,
            text=t("files_queued", lang, count=0),
            font=font_caption(fsize),
            text_color=tokens.muted,
        )
        self.files_count.grid(
            row=row_idx, column=0, columnspan=2, sticky="w", padx=12, pady=(4, 6)
        )

        self._theme_mgr.subscribe(self.apply_theme)

    def _lang(self) -> str:
        s = getattr(self._theme_mgr, "settings", None)
        return getattr(s, "language", "en") if s else "en"

    def _fsize(self) -> str:
        s = getattr(self._theme_mgr, "settings", None)
        return getattr(s, "font_size", "M") if s else "M"

    def _radii(self) -> tuple[int, int]:
        from .theme import get_corner_radii

        s = getattr(self._theme_mgr, "settings", None)
        style = getattr(s, "radius_style", "Normal") if s else "Normal"
        return get_corner_radii(style)

    def apply_theme(self, tokens: ThemeTokens) -> None:
        card_rad, _ = self._radii()
        fsize = self._fsize()
        lang = self._lang()
        self.configure(
            fg_color=tokens.surface,
            border_color=tokens.border,
            corner_radius=card_rad,
        )
        self.header_label.configure(
            text=t("source_metadata", lang),
            text_color=tokens.text,
            font=font_section(fsize),
        )
        for name, key in FIELD_KEYS:
            lbl = self._labels.get(name)
            if lbl:
                lbl.configure(
                    text=t(key, lang),
                    text_color=tokens.muted,
                    font=font_caption(fsize),
                )
        empty = t("empty_val", lang)
        for name, val in self._values.items():
            is_fps_val = name == "FPS" and val.cget("text") != empty
            val.configure(
                text_color=tokens.accent if is_fps_val else tokens.text,
                font=font_body(bold=(name == "FPS"), size_opt=fsize),
            )
        self.files_count.configure(text_color=tokens.muted, font=font_caption(fsize))

    def clear(self) -> None:
        lang = self._lang()
        fsize = self._fsize()
        tokens = self._theme_mgr.tokens
        empty = t("empty_val", lang)
        for val in self._values.values():
            val.configure(text=empty, font=font_body(size_opt=fsize), text_color=tokens.text)
        self.files_count.configure(text=t("files_queued", lang, count=0))

    def show_info(self, info: VideoInfo, queue_index: int = 1, queue_total: int = 1) -> None:
        tokens = self._theme_mgr.tokens
        lang = self._lang()
        fsize = self._fsize()
        empty = t("empty_val", lang)
        v = self._values
        fps_text = f"{info.fps:.2f}".rstrip("0").rstrip(".") if info.fps else empty
        v["FPS"].configure(
            text=f"{fps_text} fps" if info.fps else empty,
            font=font_body(bold=True, size_opt=fsize),
            text_color=tokens.accent,
        )

        if info.width and info.height:
            v["Resolution"].configure(text=f"{info.width} × {info.height}")
        else:
            v["Resolution"].configure(text=empty)

        v["Codec"].configure(text=info.codec or empty)
        v["Duration"].configure(text=f"{info.duration_s:.2f} s" if info.duration_s else empty)
        v["Timescale"].configure(text=str(info.timescale) if info.timescale else empty)
        v["Audio"].configure(text="present" if info.has_audio else "none")
        v["Queue"].configure(text=f"{queue_index} / {queue_total}")

        self.files_count.configure(text=t("batch_files", lang, count=queue_total))
