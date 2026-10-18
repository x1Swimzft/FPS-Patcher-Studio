"""Output settings tab component."""

from __future__ import annotations

from tkinter import filedialog
from typing import Any

import customtkinter as ctk

from ...config import Settings, render_filename_template
from ..theme import font_caption, font_mono, font_section


class OutputTab:
    def __init__(self, parent: ctk.CTkFrame, dialog: Any) -> None:
        self.dialog = dialog
        self.frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._build_ui()

    def _tr(self, key: str, **kwargs: object) -> str:
        return str(self.dialog._tr(key, **kwargs))

    def _build_ui(self) -> None:
        tokens = self.dialog._theme_mgr.tokens
        draft: Settings = self.dialog._draft

        # Output dir
        ctk.CTkLabel(
            self.frame,
            text=self._tr("default_output_dir"),
            font=font_section(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(
            self.frame,
            text=self._tr("leave_empty_source"),
            font=font_caption(),
            text_color=tokens.muted,
        ).pack(anchor="w", pady=(0, 4))

        out_row = ctk.CTkFrame(self.frame, fg_color="transparent")
        out_row.pack(fill="x", pady=(0, 12))

        self.out_dir_entry = ctk.CTkEntry(
            out_row,
            font=font_caption(),
            fg_color=tokens.surface_raised,
            border_color=tokens.border,
            text_color=tokens.text,
        )
        self.out_dir_entry.insert(0, draft.output_dir)
        self.out_dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            out_row,
            text=self._tr("browse"),
            width=70,
            height=28,
            font=font_caption(),
            command=self._browse_output_dir,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.text,
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            out_row,
            text=self._tr("reset"),
            width=50,
            height=28,
            font=font_caption(),
            command=lambda: (self.out_dir_entry.delete(0, "end")),
            fg_color="transparent",
            hover_color=tokens.surface_raised,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.muted,
        ).pack(side="left", padx=2)

        # Filename template
        ctk.CTkLabel(
            self.frame,
            text=self._tr("filename_template"),
            font=font_section(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(4, 2))
        ctk.CTkLabel(
            self.frame,
            text=self._tr("template_help"),
            font=font_caption(),
            text_color=tokens.muted,
        ).pack(anchor="w", pady=(0, 4))

        self.tpl_entry = ctk.CTkEntry(
            self.frame,
            font=font_mono(),
            fg_color=tokens.surface_raised,
            border_color=tokens.border,
            text_color=tokens.text,
        )
        self.tpl_entry.insert(0, draft.filename_template)
        self.tpl_entry.pack(fill="x", pady=(0, 4))
        self.tpl_entry.bind("<KeyRelease>", self._update_template_preview)

        self.tpl_preview_lbl = ctk.CTkLabel(
            self.frame,
            text="",
            font=font_caption(),
            text_color=tokens.text2,
        )
        self.tpl_preview_lbl.pack(anchor="w", pady=(0, 12))
        self._update_template_preview()

        # Switches
        self.open_done_switch = ctk.CTkSwitch(
            self.frame,
            text=self._tr("open_when_done"),
            font=font_caption(),
            text_color=tokens.text,
            progress_color=tokens.accent,
        )
        if draft.open_when_done:
            self.open_done_switch.select()
        self.open_done_switch.pack(anchor="w", pady=(4, 4))

        self.preserve_mtime_switch = ctk.CTkSwitch(
            self.frame,
            text=self._tr("preserve_mtime"),
            font=font_caption(),
            text_color=tokens.text,
            progress_color=tokens.accent,
        )
        if draft.preserve_mtime:
            self.preserve_mtime_switch.select()
        self.preserve_mtime_switch.pack(anchor="w", pady=(4, 8))

    def _browse_output_dir(self) -> None:
        folder = filedialog.askdirectory(parent=self.dialog)
        if folder:
            self.out_dir_entry.delete(0, "end")
            self.out_dir_entry.insert(0, folder)

    def _update_template_preview(self, event: Any = None) -> None:
        tpl = self.tpl_entry.get().strip() or "{name}_{fps}fps"
        rendered = render_filename_template(tpl, "sample_clip", 60)
        self.tpl_preview_lbl.configure(text=self._tr("template_preview", preview=f"{rendered}.mp4"))

    def harvest(self, draft: Settings) -> None:
        draft.output_dir = self.out_dir_entry.get().strip()
        draft.filename_template = self.tpl_entry.get().strip() or "{name}_{fps}fps"
        draft.open_when_done = bool(self.open_done_switch.get())
        draft.preserve_mtime = bool(self.preserve_mtime_switch.get())
