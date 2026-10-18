"""About and data settings tab component."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk

from ... import __version__
from ...config import Settings, app_data_dir
from ..theme import font_caption, font_title


class AboutTab:
    def __init__(self, parent: ctk.CTkFrame, dialog: Any) -> None:
        self.dialog = dialog
        self.frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._build_ui()

    def _tr(self, key: str, **kwargs: object) -> str:
        return str(self.dialog._tr(key, **kwargs))

    def _build_ui(self) -> None:
        tokens = self.dialog._theme_mgr.tokens

        ctk.CTkLabel(
            self.frame,
            text=self._tr("app_info", version=__version__),
            font=font_title(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(0, 2))

        ctk.CTkLabel(
            self.frame,
            text=self._tr("about_desc"),
            font=font_caption(),
            text_color=tokens.muted,
        ).pack(anchor="w", pady=(0, 16))

        # Action Buttons
        ctk.CTkButton(
            self.frame,
            text=self._tr("copy_diagnostics"),
            height=32,
            font=font_caption(),
            command=self._copy_diagnostics,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.text,
        ).pack(fill="x", pady=4)

        ctk.CTkButton(
            self.frame,
            text=self._tr("open_appdata"),
            height=32,
            font=font_caption(),
            command=self._open_logs_folder,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.text,
        ).pack(fill="x", pady=4)

        ctk.CTkButton(
            self.frame,
            text=self._tr("export_settings"),
            height=32,
            font=font_caption(),
            command=self._export_settings,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.text,
        ).pack(fill="x", pady=4)

        ctk.CTkButton(
            self.frame,
            text=self._tr("import_settings"),
            height=32,
            font=font_caption(),
            command=self._import_settings,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.text,
        ).pack(fill="x", pady=4)

    def _copy_diagnostics(self) -> None:
        draft = self.dialog._draft
        diag = {
            "app_version": __version__,
            "python": platform.python_version(),
            "os": platform.platform(),
            "architecture": platform.architecture()[0],
            "theme_preset": draft.theme_preset,
            "backdrop_mode": draft.glass_mode,
            "tint_strength": draft.tint_strength,
        }
        text = json.dumps(diag, indent=2)
        self.dialog.clipboard_clear()
        self.dialog.clipboard_append(text)
        messagebox.showinfo("Diagnostics", self._tr("diagnostics_copied"), parent=self.dialog)

    def _open_logs_folder(self) -> None:
        p = app_data_dir()
        if hasattr(os, "startfile"):
            os.startfile(p)
        else:
            subprocess.run(["xdg-open", str(p)])

    def _export_settings(self) -> None:
        self.dialog._harvest_draft_values()
        path = filedialog.asksaveasfilename(
            parent=self.dialog,
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json")],
        )
        if path:
            self.dialog._draft.save(Path(path))
            messagebox.showinfo(
                "Export", self._tr("export_success", path=path), parent=self.dialog
            )

    def _import_settings(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.dialog,
            filetypes=[("JSON Files", "*.json")],
        )
        if path:
            loaded = Settings.load(Path(path))
            self.dialog._draft = loaded
            self.dialog._theme_mgr.apply(self.dialog._draft)
            messagebox.showinfo("Import", self._tr("import_success"), parent=self.dialog)
            self.dialog.destroy()

    def harvest(self, draft: Settings) -> None:
        pass
