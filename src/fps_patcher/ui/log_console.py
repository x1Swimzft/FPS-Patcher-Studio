"""Read-only, colored, auto-scrolling log console with glass aesthetics."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from tkinter import filedialog
from typing import Any

import customtkinter as ctk

from ..core.diagnostic_logger import export_diagnostic_log, logs_dir
from ..core.models import LogLevel
from .strings import t
from .theme import (
    CONSOLE_LEVEL_COLORS,
    RADIUS_CARD,
    RADIUS_CONTROL,
    ThemeTokens,
    font_caption,
    font_mono,
    font_section,
    get_theme_manager,
)

MAX_LINES = 5000


class LogConsole(ctk.CTkFrame):
    def __init__(self, master: Any) -> None:
        self._theme_mgr = get_theme_manager()
        tokens = self._theme_mgr.tokens
        self.last_target_file: Path | None = None
        self.last_source_file: Path | None = None

        super().__init__(
            master,
            corner_radius=RADIUS_CARD,
            fg_color=tokens.surface,
            border_width=1,
            border_color=tokens.border,
        )
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        header.grid_columnconfigure(0, weight=1)

        self.console_title = ctk.CTkLabel(
            header,
            text=t("activity_console"),
            font=font_section(),
            text_color=tokens.text2,
        )
        self.console_title.grid(row=0, column=0, sticky="w")

        self.verbose = ctk.CTkSwitch(
            header,
            text=t("ffmpeg_logs"),
            font=font_caption(),
            text_color=tokens.text2,
            progress_color=tokens.accent,
        )
        self.verbose.grid(row=0, column=1, padx=(0, 8))

        self.btn_save_diag = ctk.CTkButton(
            header,
            text=t("save_diag_log"),
            width=125,
            height=24,
            corner_radius=RADIUS_CONTROL,
            font=font_caption(),
            fg_color=tokens.surface_raised,
            hover_color=tokens.accent,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.text,
            command=self._save_diagnostic_log,
        )
        self.btn_save_diag.grid(row=0, column=2, padx=(0, 4))

        self.btn_open_logs = ctk.CTkButton(
            header,
            text=t("open_logs_folder"),
            width=110,
            height=24,
            corner_radius=RADIUS_CONTROL,
            font=font_caption(),
            fg_color="transparent",
            hover_color=tokens.surface_raised,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.muted,
            command=self._open_logs_folder,
        )
        self.btn_open_logs.grid(row=0, column=3, padx=(0, 4))

        self.btn_clear = ctk.CTkButton(
            header,
            text=t("clear_logs"),
            width=50,
            height=24,
            corner_radius=RADIUS_CONTROL,
            font=font_caption(),
            fg_color="transparent",
            hover_color=tokens.surface_raised,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.muted,
            command=self.clear,
        )
        self.btn_clear.grid(row=0, column=4, padx=(0, 4))

        self.btn_copy = ctk.CTkButton(
            header,
            text=t("copy_logs"),
            width=50,
            height=24,
            corner_radius=RADIUS_CONTROL,
            font=font_caption(),
            fg_color="transparent",
            hover_color=tokens.surface_raised,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.muted,
            command=self._copy_all,
        )
        self.btn_copy.grid(row=0, column=5)

        self.box = ctk.CTkTextbox(
            self,
            font=font_mono(12),
            wrap="none",
            corner_radius=RADIUS_CONTROL,
            fg_color=tokens.console_bg,
            border_width=1,
            border_color=tokens.console_border,
            text_color=tokens.text,
        )
        self.box.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 12))
        self.box.configure(state="disabled")

        self._line_count = 0
        self._setup_tags()
        self._theme_mgr.subscribe(self.apply_theme)

    def apply_theme(self, tokens: ThemeTokens) -> None:
        self.configure(fg_color=tokens.surface, border_color=tokens.border)
        self.console_title.configure(text_color=tokens.text2)
        self.verbose.configure(text_color=tokens.text2, progress_color=tokens.accent)
        self.btn_save_diag.configure(
            fg_color=tokens.surface_raised,
            hover_color=tokens.accent,
            border_color=tokens.border,
            text_color=tokens.text,
        )
        self.btn_open_logs.configure(
            hover_color=tokens.surface_raised,
            border_color=tokens.border,
            text_color=tokens.muted,
        )
        self.btn_clear.configure(
            hover_color=tokens.surface_raised,
            border_color=tokens.border,
            text_color=tokens.muted,
        )
        self.btn_copy.configure(
            hover_color=tokens.surface_raised,
            border_color=tokens.border,
            text_color=tokens.muted,
        )
        self.box.configure(
            fg_color=tokens.console_bg,
            border_color=tokens.console_border,
            text_color=tokens.text,
        )

    def _setup_tags(self) -> None:
        txt = self.box._textbox
        for lvl, col in CONSOLE_LEVEL_COLORS.items():
            txt.tag_config(lvl, foreground=col)
        tokens = self._theme_mgr.tokens
        txt.tag_config("TIME", foreground=tokens.muted[1])

    def append(self, text: str, level: LogLevel = "INFO") -> None:
        self.box.configure(state="normal")
        txt = self.box._textbox

        if self._line_count >= MAX_LINES:
            txt.delete("1.0", "500.0")
            self._line_count -= 500

        ts = time.strftime("%H:%M:%S")
        txt.insert("end", f"[{ts}] ", "TIME")
        txt.insert("end", f"{text}\n", level)
        self._line_count += 1

        self.box.see("end")
        self.box.configure(state="disabled")

    def set_context_files(
        self, target: Path | None = None, source: Path | None = None
    ) -> None:
        if target is not None:
            self.last_target_file = target
        if source is not None:
            self.last_source_file = source

    def clear(self) -> None:
        self.box.configure(state="normal")
        self.box.delete("1.0", "end")
        self.box.configure(state="disabled")
        self._line_count = 0

    def get_lines(self) -> list[str]:
        text = self.box.get("1.0", "end-1c")
        return [line for line in text.splitlines() if line.strip()]

    def _copy_all(self) -> None:
        text = self.box.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(text)

    def _save_diagnostic_log(self) -> None:
        default_dir = str(logs_dir())
        stamp = time.strftime("%Y%m%d_%H%M%S")
        dest = filedialog.asksaveasfilename(
            title="Save Diagnostic Log",
            initialdir=default_dir,
            initialfile=f"user_diag_{stamp}.log",
            defaultextension=".log",
            filetypes=[
                ("Diagnostic Log (.log)", "*.log"),
                ("Diagnostic JSON (.json)", "*.json"),
            ],
        )
        if not dest:
            return
        mask_paths = True
        if self._theme_mgr.settings is not None:
            mask_paths = getattr(self._theme_mgr.settings, "mask_diagnostic_paths", True)
        saved = export_diagnostic_log(
            target_path=Path(dest),
            file_path=self.last_target_file,
            console_lines=self.get_lines(),
            orig_path=self.last_source_file,
            mask_paths=mask_paths,
        )
        self.append(f"Diagnostic report saved to: {saved.name}", "OK")

    def _open_logs_folder(self) -> None:
        d = logs_dir()
        if hasattr(os, "startfile"):
            os.startfile(str(d))
        else:
            subprocess.run(["xdg-open", str(d)], check=False)

