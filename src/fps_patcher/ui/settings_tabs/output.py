"""Output settings tab component."""

from __future__ import annotations

from tkinter import filedialog
from typing import Any

import customtkinter as ctk

from ...config import Settings, render_filename_template
from ..theme import (
    MacSwitch,
    attach_focus_ring,
    font_caption,
    font_mono,
    font_section,
)


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
            border_width=1,
            text_color=tokens.text,
        )
        self.out_dir_entry.insert(0, draft.output_dir)
        self.out_dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        attach_focus_ring(self.out_dir_entry)

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
            border_width=1,
            text_color=tokens.text,
        )
        self.tpl_entry.insert(0, draft.filename_template)
        self.tpl_entry.pack(fill="x", pady=(0, 4))
        self.tpl_entry.bind("<KeyRelease>", self._update_template_preview)
        attach_focus_ring(self.tpl_entry)

        self.tpl_preview_lbl = ctk.CTkLabel(
            self.frame,
            text="",
            font=font_caption(),
            text_color=tokens.text2,
        )
        self.tpl_preview_lbl.pack(anchor="w", pady=(0, 12))
        self._update_template_preview()

        # Switches
        self.open_done_switch = MacSwitch(
            self.frame,
            text=self._tr("open_when_done"),
            font=font_caption(),
            text_color=tokens.text,
        )
        if draft.open_when_done:
            self.open_done_switch.select()
        self.open_done_switch.pack(anchor="w", pady=(4, 4))

        self.preserve_mtime_switch = MacSwitch(
            self.frame,
            text=self._tr("preserve_mtime"),
            font=font_caption(),
            text_color=tokens.text,
        )
        if draft.preserve_mtime:
            self.preserve_mtime_switch.select()
        self.preserve_mtime_switch.pack(anchor="w", pady=(4, 8))

        # Watch folder & Explorer context menu (Phase 2)
        ctk.CTkLabel(
            self.frame,
            text=self._tr("watch_folder_section"),
            font=font_section(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(8, 2))
        ctk.CTkLabel(
            self.frame,
            text=self._tr("watch_folder_hint"),
            font=font_caption(),
            text_color=tokens.muted,
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(0, 4))

        watch_row = ctk.CTkFrame(self.frame, fg_color="transparent")
        watch_row.pack(fill="x", pady=(0, 6))
        self.watch_entry = ctk.CTkEntry(
            watch_row,
            font=font_caption(),
            fg_color=tokens.surface_raised,
            border_color=tokens.border,
            border_width=1,
            text_color=tokens.text,
            placeholder_text=self._tr("watch_folder_dir"),
        )
        self.watch_entry.insert(0, draft.watch_folder)
        self.watch_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        attach_focus_ring(self.watch_entry)
        ctk.CTkButton(
            watch_row,
            text=self._tr("browse"),
            width=70,
            height=28,
            font=font_caption(),
            command=self._browse_watch_folder,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.text,
        ).pack(side="left", padx=2)

        self.watch_switch = MacSwitch(
            self.frame,
            text=self._tr("watch_folder_enable"),
            font=font_caption(),
            text_color=tokens.text,
        )
        if draft.watch_folder_enabled:
            self.watch_switch.select()
        self.watch_switch.pack(anchor="w", pady=(4, 4))

        self.explorer_switch = MacSwitch(
            self.frame,
            text=self._tr("explorer_menu_enable"),
            font=font_caption(),
            text_color=tokens.text,
        )
        if draft.explorer_menu:
            self.explorer_switch.select()
        self.explorer_switch.pack(anchor="w", pady=(4, 8))

    def _browse_output_dir(self) -> None:
        folder = filedialog.askdirectory(parent=self.dialog)
        if folder:
            self.out_dir_entry.delete(0, "end")
            self.out_dir_entry.insert(0, folder)

    def _browse_watch_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self.dialog)
        if folder:
            self.watch_entry.delete(0, "end")
            self.watch_entry.insert(0, folder)

    def _update_template_preview(self, event: Any = None) -> None:
        tpl = self.tpl_entry.get().strip() or "{name}_{fps}fps"
        rendered = render_filename_template(tpl, "sample_clip", 60)
        self.tpl_preview_lbl.configure(text=self._tr("template_preview", preview=f"{rendered}.mp4"))

    def harvest(self, draft: Settings) -> None:
        draft.output_dir = self.out_dir_entry.get().strip()
        draft.filename_template = self.tpl_entry.get().strip() or "{name}_{fps}fps"
        draft.open_when_done = bool(self.open_done_switch.get())
        draft.preserve_mtime = bool(self.preserve_mtime_switch.get())
        draft.watch_folder = self.watch_entry.get().strip()
        draft.watch_folder_enabled = bool(self.watch_switch.get())
        draft.explorer_menu = bool(self.explorer_switch.get())
