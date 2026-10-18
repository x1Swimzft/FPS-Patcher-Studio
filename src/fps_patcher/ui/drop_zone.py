"""Drag-and-drop target with Browse fallback and glass styling."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog
from typing import Any

import customtkinter as ctk
from tkinterdnd2 import DND_FILES

from ..core.models import SUPPORTED_EXTENSIONS
from .strings import t
from .theme import (
    RADIUS_CARD,
    RADIUS_CONTROL,
    STATUS_SUCCESS_BG,
    STATUS_SUCCESS_BORDER,
    STATUS_SUCCESS_TEXT,
    ThemeTokens,
    font_body,
    font_caption,
    font_title,
    get_theme_manager,
)


class DropZone(ctk.CTkFrame):
    def __init__(self, master: Any, on_files: Callable[[list[Path]], None]) -> None:
        self._theme_mgr = get_theme_manager()
        tokens = self._theme_mgr.tokens

        super().__init__(
            master,
            border_width=1,
            border_color=tokens.border,
            corner_radius=RADIUS_CARD,
            fg_color=tokens.surface,
        )
        self._on_files = on_files
        self._is_active = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure((0, 4), weight=1)

        self.icon = ctk.CTkLabel(
            self,
            text="📥",
            font=ctk.CTkFont(size=38),
            text_color=tokens.muted,
        )
        self.icon.grid(row=1, column=0, pady=(0, 4))

        self.label = ctk.CTkLabel(
            self,
            text=t("drop_title"),
            font=font_title(),
            text_color=tokens.text,
        )
        self.label.grid(row=2, column=0, pady=(0, 2))

        self.sub = ctk.CTkLabel(
            self,
            text=t("drop_sub"),
            font=font_caption(),
            text_color=tokens.text2,
        )
        self.sub.grid(row=3, column=0, pady=(0, 10))

        self.btn = ctk.CTkButton(
            self,
            text=t("browse_files"),
            font=font_body(bold=True),
            width=130,
            height=32,
            corner_radius=RADIUS_CONTROL,
            command=self._browse,
            fg_color=tokens.accent,
            hover_color=tokens.accent_hover,
            border_width=0,
            text_color="#FFFFFF",
        )
        self.btn.grid(row=4, column=0, pady=(0, 6))

        self.bind("<Button-1>", lambda _: self._browse())
        self.icon.bind("<Button-1>", lambda _: self._browse())
        self.label.bind("<Button-1>", lambda _: self._browse())
        self.sub.bind("<Button-1>", lambda _: self._browse())

        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<DropEnter>>", self._on_enter)
        self.dnd_bind("<<DropLeave>>", self._on_leave)
        self.dnd_bind("<<Drop>>", self._on_drop)

        self._theme_mgr.subscribe(self.apply_theme)

    def apply_theme(self, tokens: ThemeTokens) -> None:
        if not self._is_active:
            self.configure(fg_color=tokens.surface, border_color=tokens.border)
            self.icon.configure(text_color=tokens.muted)
            self.label.configure(text_color=tokens.text)
            self.sub.configure(text_color=tokens.text2)
            self.btn.configure(
                fg_color=tokens.accent,
                hover_color=tokens.accent_hover,
                text_color="#FFFFFF",
            )

    def _browse(self) -> None:
        files = filedialog.askopenfilenames(
            title="Select video files",
            filetypes=[
                ("Video files", "*.mp4;*.mov;*.m4v"),
                ("MP4 files", "*.mp4"),
                ("MOV files", "*.mov"),
                ("All files", "*.*"),
            ],
        )
        if files:
            self._on_files([Path(p) for p in files])

    def _on_enter(self, _event: Any) -> None:
        self._is_active = True
        tokens = self._theme_mgr.tokens
        self.configure(
            fg_color=tokens.surface_drop_hover,
            border_color=tokens.border_focus,
            border_width=2,
        )
        self.label.configure(text=t("drag_active"), text_color=tokens.accent)
        self.icon.configure(text_color=tokens.accent)

    def _on_leave(self, _event: Any) -> None:
        self._is_active = False
        tokens = self._theme_mgr.tokens
        self.configure(
            fg_color=tokens.surface,
            border_color=tokens.border,
            border_width=1,
        )
        self.label.configure(text=t("drop_title"), text_color=tokens.text)
        self.icon.configure(text_color=tokens.muted)

    def _on_drop(self, event: Any) -> None:
        self._on_leave(event)
        raw = getattr(event, "data", "")
        paths: list[Path] = []
        for token in self.tk.splitlist(raw):
            p = Path(token)
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                paths.append(p)
            elif p.is_dir():
                paths.extend(
                    sorted(
                        f
                        for f in p.iterdir()
                        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
                    )
                )
        if paths:
            self._flash_success()
            self._on_files(paths)

    def _flash_success(self) -> None:
        self.configure(
            fg_color=STATUS_SUCCESS_BG,
            border_color=STATUS_SUCCESS_BORDER,
        )
        self.label.configure(text_color=STATUS_SUCCESS_TEXT)
        tokens = self._theme_mgr.tokens
        self.after(
            300,
            lambda: (
                self.configure(
                    fg_color=tokens.surface,
                    border_color=tokens.border,
                ),
                self.label.configure(text=t("drop_title"), text_color=tokens.text),
            ),
        )
