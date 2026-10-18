"""FFmpeg locator and execution settings tab component."""

from __future__ import annotations

import subprocess
from pathlib import Path
from tkinter import filedialog
from typing import Any

import customtkinter as ctk

from ...config import Settings
from ...core.ffmpeg_locator import locate
from ..theme import font_caption, font_mono, font_section


class FFmpegTab:
    def __init__(self, parent: ctk.CTkFrame, dialog: Any) -> None:
        self.dialog = dialog
        self.frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._build_ui()

    def _tr(self, key: str, **kwargs: object) -> str:
        return str(self.dialog._tr(key, **kwargs))

    def _build_ui(self) -> None:
        tokens = self.dialog._theme_mgr.tokens
        draft: Settings = self.dialog._draft

        ctk.CTkLabel(
            self.frame,
            text=self._tr("ffmpeg_dir"),
            font=font_section(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(0, 4))

        ff_row = ctk.CTkFrame(self.frame, fg_color="transparent")
        ff_row.pack(fill="x", pady=(0, 8))

        self.ff_dir_entry = ctk.CTkEntry(
            ff_row,
            font=font_caption(),
            fg_color=tokens.surface_raised,
            border_color=tokens.border,
            text_color=tokens.text,
        )
        self.ff_dir_entry.insert(0, draft.ffmpeg_dir)
        self.ff_dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            ff_row,
            text=self._tr("browse"),
            width=60,
            height=28,
            font=font_caption(),
            command=self._browse_ffmpeg_dir,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.text,
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            ff_row,
            text=self._tr("auto_detect"),
            width=80,
            height=28,
            font=font_caption(),
            command=self._autodetect_ffmpeg,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.text,
        ).pack(side="left", padx=2)

        # Test FFmpeg button and result label
        test_row = ctk.CTkFrame(self.frame, fg_color="transparent")
        test_row.pack(fill="x", pady=(0, 12))

        ctk.CTkButton(
            test_row,
            text=self._tr("test_ffmpeg"),
            width=100,
            height=28,
            font=font_caption(),
            command=self._test_ffmpeg,
            fg_color=tokens.accent,
            hover_color=tokens.accent_hover,
            text_color="#FFFFFF",
        ).pack(side="left", padx=(0, 10))

        self.ff_test_res = ctk.CTkLabel(
            test_row,
            text="",
            font=font_caption(),
            text_color=tokens.muted,
        )
        self.ff_test_res.pack(side="left")

        # Switches
        self.check_on_start_switch = ctk.CTkSwitch(
            self.frame,
            text=self._tr("check_on_start"),
            font=font_caption(),
            text_color=tokens.text,
            progress_color=tokens.accent,
        )
        if draft.check_ffmpeg_on_start:
            self.check_on_start_switch.select()
        self.check_on_start_switch.pack(anchor="w", pady=4)

        self.show_ff_out_switch = ctk.CTkSwitch(
            self.frame,
            text=self._tr("show_output_console"),
            font=font_caption(),
            text_color=tokens.text,
            progress_color=tokens.accent,
        )
        if draft.show_ffmpeg_output:
            self.show_ff_out_switch.select()
        self.show_ff_out_switch.pack(anchor="w", pady=4)

        # Extra args
        ctk.CTkLabel(
            self.frame,
            text=self._tr("extra_args"),
            font=font_section(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(12, 2))
        ctk.CTkLabel(
            self.frame,
            text=self._tr("extra_args_warn"),
            font=font_caption(),
            text_color=tokens.warn,
        ).pack(anchor="w", pady=(0, 4))

        self.extra_ff_entry = ctk.CTkEntry(
            self.frame,
            font=font_mono(),
            fg_color=tokens.surface_raised,
            border_color=tokens.border,
            text_color=tokens.text,
        )
        self.extra_ff_entry.insert(0, draft.extra_ffmpeg_args)
        self.extra_ff_entry.pack(fill="x", pady=(0, 8))

    def _browse_ffmpeg_dir(self) -> None:
        folder = filedialog.askdirectory(parent=self.dialog)
        if folder:
            self.ff_dir_entry.delete(0, "end")
            self.ff_dir_entry.insert(0, folder)

    def _autodetect_ffmpeg(self) -> None:
        paths = locate()
        if paths and paths.ffmpeg:
            self.ff_dir_entry.delete(0, "end")
            self.ff_dir_entry.insert(0, str(paths.ffmpeg.parent))
            self.ff_test_res.configure(
                text="✔ Auto-detected", text_color=self.dialog._theme_mgr.tokens.success
            )
        else:
            self.ff_test_res.configure(
                text="✖ Not found in PATH", text_color=self.dialog._theme_mgr.tokens.danger
            )

    def _test_ffmpeg(self) -> None:
        folder = self.ff_dir_entry.get().strip()
        custom = Path(folder) if folder else None
        paths = locate(custom)
        if paths and paths.ffmpeg and paths.ffmpeg.exists():
            try:
                res = subprocess.run(
                    [str(paths.ffmpeg), "-version"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                first = res.stdout.splitlines()[0] if res.stdout else "FFmpeg OK"
                self.ff_test_res.configure(
                    text=f"✔ {first[:35]}",
                    text_color=self.dialog._theme_mgr.tokens.success,
                )
            except Exception as e:
                self.ff_test_res.configure(
                    text=f"✖ {e}", text_color=self.dialog._theme_mgr.tokens.danger
                )
        else:
            self.ff_test_res.configure(
                text="✖ Executable not found", text_color=self.dialog._theme_mgr.tokens.danger
            )

    def harvest(self, draft: Settings) -> None:
        draft.ffmpeg_dir = self.ff_dir_entry.get().strip()
        draft.check_ffmpeg_on_start = bool(self.check_on_start_switch.get())
        draft.show_ffmpeg_output = bool(self.show_ff_out_switch.get())
        draft.extra_ffmpeg_args = self.extra_ff_entry.get().strip()
