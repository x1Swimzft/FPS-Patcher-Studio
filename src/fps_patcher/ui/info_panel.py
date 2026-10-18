"""Displays probed video metadata with clean hierarchy and copy-on-click."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from ..core.models import VideoInfo
from .strings import t
from .theme import (
    RADIUS_CARD,
    ThemeTokens,
    font_big_stat,
    font_body,
    font_caption,
    font_section,
    get_theme_manager,
)

FIELDS = ("FPS", "Resolution", "Codec", "Duration", "Timescale", "Audio", "Queue")


class InfoPanel(ctk.CTkFrame):
    def __init__(self, master: Any) -> None:
        self._theme_mgr = get_theme_manager()
        tokens = self._theme_mgr.tokens

        super().__init__(
            master,
            corner_radius=RADIUS_CARD,
            fg_color=tokens.surface,
            border_width=1,
            border_color=tokens.border,
        )
        self.grid_columnconfigure(1, weight=1)

        self.header_label = ctk.CTkLabel(
            self,
            text=t("source_metadata"),
            font=font_section(),
            text_color=tokens.text2,
        )
        self.header_label.grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 6))

        self._labels: dict[str, ctk.CTkLabel] = {}
        self._values: dict[str, ctk.CTkLabel] = {}
        row_idx = 1
        for name in FIELDS:
            lbl = ctk.CTkLabel(
                self,
                text=name,
                font=font_caption(),
                text_color=tokens.text2,
            )
            lbl.grid(row=row_idx, column=0, sticky="w", padx=(14, 10), pady=2)
            self._labels[name] = lbl

            val = ctk.CTkLabel(
                self,
                text="—",
                font=font_body(bold=(name == "FPS")),
                text_color=tokens.text,
                anchor="e",
            )
            val.grid(row=row_idx, column=1, sticky="e", padx=(0, 14), pady=2)
            self._values[name] = val
            row_idx += 1

        self.files_count = ctk.CTkLabel(
            self,
            text="0 files queued",
            font=font_caption(),
            text_color=tokens.muted,
        )
        self.files_count.grid(
            row=row_idx, column=0, columnspan=2, sticky="w", padx=14, pady=(10, 8)
        )

        self._theme_mgr.subscribe(self.apply_theme)

    def apply_theme(self, tokens: ThemeTokens) -> None:
        self.configure(fg_color=tokens.surface, border_color=tokens.border)
        self.header_label.configure(text_color=tokens.text2)
        for lbl in self._labels.values():
            lbl.configure(text_color=tokens.text2)
        for _name, val in self._values.items():
            val.configure(text_color=tokens.text)
        self.files_count.configure(text_color=tokens.muted)

    def clear(self) -> None:
        for val in self._values.values():
            val.configure(text="—", font=font_body())
        self.files_count.configure(text="0 files queued")

    def show_info(self, info: VideoInfo, queue_index: int = 1, queue_total: int = 1) -> None:
        tokens = self._theme_mgr.tokens
        v = self._values
        fps_text = f"{info.fps:.2f}".rstrip("0").rstrip(".") if info.fps else "—"
        v["FPS"].configure(text=f"{fps_text} fps", font=font_big_stat(), text_color=tokens.accent)

        if info.width and info.height:
            v["Resolution"].configure(text=f"{info.width} × {info.height}")
        else:
            v["Resolution"].configure(text="—")

        v["Codec"].configure(text=info.codec or "—")
        v["Duration"].configure(text=f"{info.duration_s:.2f} s" if info.duration_s else "—")
        v["Timescale"].configure(text=str(info.timescale) if info.timescale else "—")
        v["Audio"].configure(text="present" if info.has_audio else "none")
        v["Queue"].configure(text=f"{queue_index} / {queue_total}")

        self.files_count.configure(
            text=f"Batch: {queue_total} file{'s' if queue_total != 1 else ''}"
        )
