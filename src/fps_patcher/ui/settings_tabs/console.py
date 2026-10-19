"""Console and logging settings tab component."""

from __future__ import annotations

import os
import subprocess
from typing import Any

import customtkinter as ctk

from ...config import Settings, app_data_dir
from ..theme import (
    MacSwitch,
    attach_focus_ring,
    font_caption,
    font_mono,
    font_section,
)


class ConsoleTab:
    def __init__(self, parent: ctk.CTkFrame, dialog: Any) -> None:
        self.dialog = dialog
        self.frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._build_ui()

    def _tr(self, key: str, **kwargs: object) -> str:
        return str(self.dialog._tr(key, **kwargs))

    def _build_ui(self) -> None:
        tokens = self.dialog._theme_mgr.tokens
        draft: Settings = self.dialog._draft

        # Console font size
        ctk.CTkLabel(
            self.frame,
            text=self._tr("console_font_size"),
            font=font_section(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(0, 4))

        self.console_font_slider = ctk.CTkSlider(
            self.frame,
            from_=9,
            to=18,
            number_of_steps=9,
            progress_color=tokens.accent,
        )
        self.console_font_slider.set(draft.console_font_size)
        self.console_font_slider.pack(fill="x", pady=(0, 8))

        # Max log lines
        ctk.CTkLabel(
            self.frame,
            text=self._tr("max_log_lines"),
            font=font_section(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(4, 2))

        self.max_log_entry = ctk.CTkEntry(
            self.frame,
            font=font_mono(),
            fg_color=tokens.surface_raised,
            border_color=tokens.border,
            border_width=1,
            text_color=tokens.text,
        )
        self.max_log_entry.insert(0, str(draft.max_log_lines))
        self.max_log_entry.pack(fill="x", pady=(0, 8))
        attach_focus_ring(self.max_log_entry)

        # Switches
        self.log_ts_switch = MacSwitch(
            self.frame,
            text=self._tr("log_timestamps"),
            font=font_caption(),
            text_color=tokens.text,
        )
        if draft.log_timestamps:
            self.log_ts_switch.select()
        self.log_ts_switch.pack(anchor="w", pady=4)

        self.log_scroll_switch = MacSwitch(
            self.frame,
            text=self._tr("log_autoscroll"),
            font=font_caption(),
            text_color=tokens.text,
        )
        if draft.log_autoscroll:
            self.log_scroll_switch.select()
        self.log_scroll_switch.pack(anchor="w", pady=4)

        self.log_file_switch = MacSwitch(
            self.frame,
            text=self._tr("log_to_file"),
            font=font_caption(),
            text_color=tokens.text,
        )
        if draft.log_to_file:
            self.log_file_switch.select()
        self.log_file_switch.pack(anchor="w", pady=4)

        # Open logs folder
        ctk.CTkButton(
            self.frame,
            text=self._tr("open_log_folder"),
            height=32,
            font=font_caption(),
            command=self._open_logs_folder,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.text,
        ).pack(anchor="w", pady=(12, 4))

    def _open_logs_folder(self) -> None:
        p = app_data_dir()
        if hasattr(os, "startfile"):
            os.startfile(p)
        else:
            subprocess.run(["xdg-open", str(p)])

    def harvest(self, draft: Settings) -> None:
        import contextlib

        draft.console_font_size = int(self.console_font_slider.get())
        with contextlib.suppress(ValueError):
            draft.max_log_lines = int(self.max_log_entry.get().strip())
        draft.log_timestamps = bool(self.log_ts_switch.get())
        draft.log_autoscroll = bool(self.log_scroll_switch.get())
        draft.log_to_file = bool(self.log_file_switch.get())
