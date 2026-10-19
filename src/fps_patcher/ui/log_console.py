"""Collapsible Apple HIG Activity Console drawer with thread-safe batched logging."""

from __future__ import annotations

import collections
import contextlib
import os
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from tkinter import Menu, filedialog
from typing import Any

import customtkinter as ctk

from ..core.diagnostic_logger import export_diagnostic_log, logs_dir
from ..core.models import LogLevel
from .icons import get_icon
from .strings import t
from .theme import (
    CONSOLE_LEVEL_COLORS,
    RADIUS_PILL,
    ThemeTokens,
    font_caption,
    font_mono,
    font_section,
    get_corner_radii,
    get_theme_manager,
)

MAX_LINES = 2000
COLLAPSED_HEIGHT = 40
EXPANDED_HEIGHT = 210
BATCH_INTERVAL_MS = 20

_CMD_PREFIXES = ("$ ", "> ", "Command:", "command:", "ffmpeg ", "ffprobe ", "[CMD]")
_DIM_PREFIXES = (
    "[DIM]",
    "[DEBUG]",
    "frame=",
    "size=",
    "Stream #",
    "Metadata:",
    "Duration:",
    "  configuration:",
    "  lib",
)


def classify_log_level(text: str, level: str = "INFO") -> str:
    """Classify log message and level into console tag (INFO/OK/WARN/ERROR/CMD/DIM/DEBUG)."""
    norm = (level or "INFO").strip().upper()
    if norm == "COMMAND":
        return "CMD"
    if norm in ("OK", "WARN", "ERROR", "CMD", "DIM", "DEBUG"):
        return norm

    stripped = text.lstrip()
    if stripped.startswith(_CMD_PREFIXES):
        return "CMD"
    if stripped.startswith(_DIM_PREFIXES):
        return "DIM"
    return "INFO"


def trim_lines_buffer(lines: list[str], max_lines: int) -> tuple[list[str], int]:
    """Cap a list of lines to ``max_lines`` (minimum 1), returning ``(kept, dropped_count)``."""
    cap = max(1, int(max_lines))
    if len(lines) <= cap:
        return list(lines), 0
    dropped = len(lines) - cap
    return list(lines[dropped:]), dropped


class LogConsole(ctk.CTkFrame):
    def __init__(
        self,
        master: Any,
        on_repair_mobile: Callable[[Path | None], None] | None = None,
    ) -> None:
        self._theme_mgr = get_theme_manager()
        tokens = self._theme_mgr.tokens
        self.last_target_file: Path | None = None
        self.last_source_file: Path | None = None
        self._on_repair_mobile = on_repair_mobile

        self._lock = threading.Lock()
        self._pending_batch: collections.deque[tuple[str, str, str]] = collections.deque()
        self._flush_scheduled = False
        self._last_flush_mono = 0.0
        self._lines_history: list[str] = []
        self._line_count = 0
        self._expanded = True
        self._copy_reset_job: str | None = None

        super().__init__(
            master,
            height=EXPANDED_HEIGHT,
            corner_radius=0,
            fg_color=tokens.console_bg,
            border_width=0,
        )
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)

        lang = self._lang()
        fsize = self._fsize()
        _, ctrl_rad = self._radii()

        # Top 1px hairline border
        self.top_divider = ctk.CTkFrame(
            self,
            height=1,
            fg_color=tokens.console_border,
            corner_radius=0,
        )
        self.top_divider.grid(row=0, column=0, sticky="ew")

        # ── Always-visible Drawer Header (~40px) ──
        self.header = ctk.CTkFrame(
            self,
            height=COLLAPSED_HEIGHT - 1,
            fg_color=tokens.console_bg,
            corner_radius=0,
        )
        self.header.grid(row=1, column=0, sticky="ew", padx=12, pady=0)
        self.header.grid_propagate(False)
        self.header.grid_columnconfigure(0, weight=1)
        self.header.grid_rowconfigure(0, weight=1)

        # Left cluster: Chevron + Title + Line counter pill
        left_cluster = ctk.CTkFrame(self.header, fg_color="transparent")
        left_cluster.grid(row=0, column=0, sticky="w", pady=4)

        chev_name = "chevron_down" if self._expanded else "chevron_right"
        chev_ico = get_icon(chev_name, (12, 12), force_dark=True)
        self.chevron_btn = ctk.CTkButton(
            left_cluster,
            text="" if chev_ico else ("▾" if self._expanded else "▸"),
            image=chev_ico,
            width=24,
            height=24,
            corner_radius=6,
            fg_color="transparent",
            hover_color=tokens.console_border,
            text_color="#E4E4E7",
            font=font_section(fsize),
            command=self.toggle_drawer,
        )
        self.chevron_btn.pack(side="left", padx=(0, 4))

        self.console_title = ctk.CTkLabel(
            left_cluster,
            text=t("activity_console", lang),
            font=font_section(fsize),
            text_color="#F4F4F5",
            cursor="hand2",
        )
        self.console_title.pack(side="left", padx=(0, 8))
        self.console_title.bind("<Button-1>", lambda _e: self.toggle_drawer())

        self.line_badge = ctk.CTkLabel(
            left_cluster,
            text=self._format_line_count(0),
            font=font_caption(fsize),
            fg_color=tokens.console_border,
            text_color="#A1A1AA",
            corner_radius=RADIUS_PILL,
            padx=8,
            height=20,
            cursor="hand2",
        )
        self.line_badge.pack(side="left")
        self.line_badge.bind("<Button-1>", lambda _e: self.toggle_drawer())

        # Right cluster: FFmpeg logs switch, Copy, Clear, Save Log, Open Logs, Repair, Overflow
        right_cluster = ctk.CTkFrame(self.header, fg_color="transparent")
        right_cluster.grid(row=0, column=1, sticky="e", pady=4)

        self.verbose = ctk.CTkSwitch(
            right_cluster,
            text=t("ffmpeg_logs", lang),
            font=font_caption(fsize),
            text_color="#A1A1AA",
            progress_color=tokens.accent,
            button_color="#F4F4F5",
            fg_color=tokens.console_border,
            width=36,
            height=20,
            command=self._on_verbose_toggled,
        )
        if self._get_show_ffmpeg_output():
            self.verbose.select()
        self.verbose.pack(side="left", padx=(0, 10))

        self.btn_copy = ctk.CTkButton(
            right_cluster,
            text=t("copy_logs", lang),
            width=56,
            height=26,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.console_border,
            hover_color="#38383E",
            border_width=0,
            text_color="#E4E4E7",
            command=self._copy_all,
        )
        self.btn_copy.pack(side="left", padx=(0, 6))

        self.btn_clear = ctk.CTkButton(
            right_cluster,
            text=t("clear_logs", lang),
            width=56,
            height=26,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.console_border,
            hover_color="#38383E",
            border_width=0,
            text_color="#E4E4E7",
            command=self.clear,
        )
        self.btn_clear.pack(side="left", padx=(0, 6))

        # "Save Log" calls existing diagnostic-log function (_save_diagnostic_log)
        self.btn_save_diag = ctk.CTkButton(
            right_cluster,
            text=t("save_log", lang),
            width=82,
            height=26,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.console_border,
            hover_color=tokens.accent,
            border_width=0,
            text_color="#F4F4F5",
            command=self._save_diagnostic_log,
        )
        self.btn_save_diag.pack(side="left", padx=(0, 6))

        # Kept as attributes for compatibility; reachable via overflow menu (btn_more)
        self.btn_open_logs = ctk.CTkButton(
            right_cluster,
            text=t("open_logs_folder", lang),
            width=112,
            height=26,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color="transparent",
            hover_color=tokens.console_border,
            border_width=1,
            border_color=tokens.console_border,
            text_color="#A1A1AA",
            command=self._open_logs_folder,
        )

        self.btn_repair_mobile = ctk.CTkButton(
            right_cluster,
            text=t("repair_for_mobile", lang),
            width=116,
            height=26,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color="transparent",
            hover_color=tokens.console_border,
            border_width=1,
            border_color=tokens.console_border,
            text_color="#A1A1AA",
            command=self._repair_for_mobile,
        )

        more_ico = get_icon("more", (16, 16), force_dark=True)
        self.btn_more = ctk.CTkButton(
            right_cluster,
            text="" if more_ico else "⋯",
            image=more_ico,
            width=28,
            height=26,
            corner_radius=ctrl_rad,
            font=font_section(fsize),
            fg_color=tokens.console_border,
            hover_color="#38383E",
            border_width=0,
            text_color="#E4E4E7",
            command=self._show_overflow_btn_menu,
        )
        self.btn_more.pack(side="left")

        # ── Terminal Textbox Body ──
        self.box = ctk.CTkTextbox(
            self,
            font=font_mono(self._get_console_font_size()),
            wrap="none",
            corner_radius=0,
            fg_color=tokens.console_bg,
            border_width=0,
            text_color="#E4E4E7",
        )
        self.box.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self.box.configure(state="disabled")

        self._setup_tags()
        self._theme_mgr.subscribe(self.apply_theme)

        # Periodic background drain in case worker threads call append() directly
        self.after(50, self._poll_worker_batch)

    # ---------- settings helpers ----------
    def _settings(self) -> Any:
        return self._theme_mgr.settings

    def _lang(self) -> str:
        s = self._settings()
        return str(s.language) if s and hasattr(s, "language") else "en"

    def _format_line_count(self, count: int) -> str:
        return t(
            "console_line_one" if count == 1 else "console_lines",
            self._lang(),
            count=count,
        )

    def _fsize(self) -> str:
        s = self._settings()
        return str(s.font_size) if s and hasattr(s, "font_size") else "Default"

    def _radii(self) -> tuple[int, int]:
        s = self._settings()
        style = str(s.radius_style) if s and hasattr(s, "radius_style") else "Normal"
        return get_corner_radii(style)

    def _get_console_font_size(self) -> int:
        s = self._settings()
        if s is not None and hasattr(s, "console_font_size"):
            return max(8, min(24, int(s.console_font_size)))
        return 12

    def _get_max_lines(self) -> int:
        s = self._settings()
        if s is not None and hasattr(s, "max_log_lines"):
            return max(100, min(20000, int(s.max_log_lines)))
        return MAX_LINES

    def _get_log_timestamps(self) -> bool:
        s = self._settings()
        if s is not None and hasattr(s, "log_timestamps"):
            return bool(s.log_timestamps)
        return True

    def _get_log_autoscroll(self) -> bool:
        s = self._settings()
        if s is not None and hasattr(s, "log_autoscroll"):
            return bool(s.log_autoscroll)
        return True

    def _get_log_to_file(self) -> bool:
        s = self._settings()
        if s is not None and hasattr(s, "log_to_file"):
            return bool(s.log_to_file)
        return False

    def _get_show_ffmpeg_output(self) -> bool:
        s = self._settings()
        if s is not None and hasattr(s, "show_ffmpeg_output"):
            return bool(s.show_ffmpeg_output)
        return False

    def _get_reduce_motion(self) -> bool:
        s = self._settings()
        if s is not None and hasattr(s, "reduce_motion"):
            return bool(s.reduce_motion)
        return False

    # ---------- drawer expand / collapse ----------
    @property
    def is_expanded(self) -> bool:
        return self._expanded

    def toggle_drawer(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        chev_name = "chevron_down" if self._expanded else "chevron_right"
        chev_ico = get_icon(chev_name, (12, 12), force_dark=True)
        self.chevron_btn.configure(
            image=chev_ico,
            text="" if chev_ico else ("▾" if self._expanded else "▸"),
        )
        if self._expanded:
            self.box.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))
            if self._get_reduce_motion():
                self.configure(height=EXPANDED_HEIGHT)
            else:
                self.configure(height=125)
                self.after(16, lambda: self.configure(height=EXPANDED_HEIGHT))
        else:
            self.box.grid_remove()
            self.configure(height=COLLAPSED_HEIGHT)

    # ---------- theme & settings sync ----------
    def apply_theme(self, tokens: ThemeTokens) -> None:
        lang = self._lang()
        fsize = self._fsize()
        _, ctrl_rad = self._radii()

        self.configure(fg_color=tokens.console_bg)
        self.top_divider.configure(fg_color=tokens.console_border)
        self.header.configure(fg_color=tokens.console_bg)

        chev_name = "chevron_down" if self._expanded else "chevron_right"
        chev_ico = get_icon(chev_name, (12, 12), force_dark=True)
        self.chevron_btn.configure(
            image=chev_ico,
            text="" if chev_ico else ("▾" if self._expanded else "▸"),
            hover_color=tokens.console_border,
            font=font_section(fsize),
        )
        self.console_title.configure(
            text=t("activity_console", lang),
            font=font_section(fsize),
        )
        self.line_badge.configure(
            text=self._format_line_count(self._line_count),
            fg_color=tokens.console_border,
            font=font_caption(fsize),
        )
        self.verbose.configure(
            text=t("ffmpeg_logs", lang),
            progress_color=tokens.accent,
            fg_color=tokens.console_border,
            font=font_caption(fsize),
        )
        if self._get_show_ffmpeg_output():
            self.verbose.select()
        else:
            self.verbose.deselect()

        self.btn_copy.configure(
            text=t("copy_logs", lang),
            fg_color=tokens.console_border,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.btn_clear.configure(
            text=t("clear_logs", lang),
            fg_color=tokens.console_border,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.btn_save_diag.configure(
            text=t("save_log", lang),
            fg_color=tokens.console_border,
            hover_color=tokens.accent,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.btn_open_logs.configure(
            text=t("open_logs_folder", lang),
            hover_color=tokens.console_border,
            border_color=tokens.console_border,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.btn_repair_mobile.configure(
            text=t("repair_for_mobile", lang),
            hover_color=tokens.console_border,
            border_color=tokens.console_border,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.btn_more.configure(
            fg_color=tokens.console_border,
            corner_radius=ctrl_rad,
            font=font_section(fsize),
        )
        self.box.configure(
            fg_color=tokens.console_bg,
            font=font_mono(self._get_console_font_size()),
        )
        self._setup_tags()
        self._enforce_max_lines()

    def _setup_tags(self) -> None:
        txt = self.box._textbox
        for lvl, col in CONSOLE_LEVEL_COLORS.items():
            txt.tag_config(lvl, foreground=col)
            txt.tag_config(lvl.lower(), foreground=col)
        txt.tag_config("COMMAND", foreground=CONSOLE_LEVEL_COLORS.get("CMD", "#60A5FA"))
        txt.tag_config("command", foreground=CONSOLE_LEVEL_COLORS.get("CMD", "#60A5FA"))
        txt.tag_config("TIME", foreground="#52525B")

    # ---------- logging & thread-safe batching ----------
    def _is_at_bottom(self) -> bool:
        try:
            yview = self.box._textbox.yview()
            return bool(yview[1] >= 0.97)
        except Exception:
            return True

    def append(self, text: str, level: LogLevel | str = "INFO") -> None:
        """Thread-safe log append. Worker threads enqueue without touching Tk widgets."""
        norm_level = (level or "INFO").strip().upper()
        if norm_level == "DEBUG" and not bool(self.verbose.get()):
            return

        tag = classify_log_level(text, norm_level)
        ts = time.strftime("%H:%M:%S") if self._get_log_timestamps() else ""

        with self._lock:
            self._pending_batch.append((ts, text, tag))

        if threading.current_thread() is not threading.main_thread():
            return

        now = time.monotonic()
        if (now - self._last_flush_mono) >= (BATCH_INTERVAL_MS / 1000.0):
            self._flush_pending()
        elif not self._flush_scheduled:
            self._flush_scheduled = True
            self.after(BATCH_INTERVAL_MS, self._flush_pending)

    def append_batch(self, entries: list[tuple[str, LogLevel | str]]) -> None:
        """Append multiple (text, level) entries in a single batch."""
        show_debug = bool(self.verbose.get())
        use_ts = self._get_log_timestamps()
        ts = time.strftime("%H:%M:%S") if use_ts else ""
        with self._lock:
            for text, level in entries:
                norm_level = (level or "INFO").strip().upper()
                if norm_level == "DEBUG" and not show_debug:
                    continue
                tag = classify_log_level(text, norm_level)
                self._pending_batch.append((ts, text, tag))

        if threading.current_thread() is threading.main_thread():
            self._flush_pending()

    def _poll_worker_batch(self) -> None:
        with self._lock:
            has_items = bool(self._pending_batch)
        if has_items:
            self._flush_pending()
        with contextlib.suppress(Exception):
            if self.winfo_exists():
                self.after(50, self._poll_worker_batch)

    def _flush_pending(self) -> None:
        self._flush_scheduled = False
        with self._lock:
            if not self._pending_batch:
                return
            batch = list(self._pending_batch)
            self._pending_batch.clear()

        self._last_flush_mono = time.monotonic()
        was_at_bottom = self._is_at_bottom()
        max_lines = self._get_max_lines()

        # Trim batch itself if a single burst exceeds max_lines
        if len(batch) > max_lines:
            batch = batch[-max_lines:]

        self.box.configure(state="normal")
        txt = self.box._textbox

        file_lines_to_write: list[str] = []
        for ts, text, tag in batch:
            if ts:
                txt.insert("end", f"[{ts}] ", "TIME")
                formatted = f"[{ts}] {text}"
            else:
                formatted = text
            txt.insert("end", f"{text}\n", tag)
            self._lines_history.append(formatted)
            file_lines_to_write.append(formatted)
            self._line_count += 1

        self._enforce_max_lines_unlocked(txt, max_lines)

        if self._get_log_autoscroll() and was_at_bottom:
            self.box.see("end")

        self.box.configure(state="disabled")
        self.line_badge.configure(
            text=self._format_line_count(self._line_count)
        )

        if self._get_log_to_file() and file_lines_to_write:
            self._write_session_log(file_lines_to_write)

    def _enforce_max_lines(self) -> None:
        max_lines = self._get_max_lines()
        if self._line_count <= max_lines:
            return
        self.box.configure(state="normal")
        self._enforce_max_lines_unlocked(self.box._textbox, max_lines)
        self.box.configure(state="disabled")
        self.line_badge.configure(
            text=self._format_line_count(self._line_count)
        )

    def _enforce_max_lines_unlocked(self, txt: Any, max_lines: int) -> None:
        self._lines_history, dropped = trim_lines_buffer(self._lines_history, max_lines)
        if self._line_count > max_lines:
            excess = self._line_count - max_lines
            txt.delete("1.0", f"{excess + 1}.0")
            self._line_count = max_lines
        elif dropped > 0:
            txt.delete("1.0", f"{dropped + 1}.0")
            self._line_count = len(self._lines_history)

    def _write_session_log(self, lines: list[str]) -> None:
        with contextlib.suppress(OSError):
            d = logs_dir()
            d.mkdir(parents=True, exist_ok=True)
            log_file = d / "console_session.log"
            with log_file.open("a", encoding="utf-8") as fh:
                for ln in lines:
                    fh.write(ln + "\n")

    # ---------- public API ----------
    def set_context_files(
        self, target: Path | None = None, source: Path | None = None
    ) -> None:
        if target is not None:
            self.last_target_file = target
        if source is not None:
            self.last_source_file = source

    def clear(self) -> None:
        with self._lock:
            self._pending_batch.clear()
        self.box.configure(state="normal")
        self.box.delete("1.0", "end")
        self.box.configure(state="disabled")
        self._lines_history.clear()
        self._line_count = 0
        self.line_badge.configure(text=self._format_line_count(0))

    def get_lines(self) -> list[str]:
        if threading.current_thread() is threading.main_thread():
            self._flush_pending()
        text = self.box.get("1.0", "end-1c")
        return [line for line in text.splitlines() if line.strip()]

    # ---------- actions & overflow menu ----------
    def _on_verbose_toggled(self) -> None:
        s = self._settings()
        if s is not None and hasattr(s, "show_ffmpeg_output"):
            s.show_ffmpeg_output = bool(self.verbose.get())

    def _copy_all(self) -> None:
        self._flush_pending()
        text = self.box.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(text)
        lang = self._lang()
        self.btn_copy.configure(text=t("copied_flash", lang))
        if self._copy_reset_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._copy_reset_job)
        self._copy_reset_job = self.after(
            900,
            lambda: self.btn_copy.configure(text=t("copy_logs", self._lang())),
        )

    def _save_diagnostic_log(self) -> None:
        self._flush_pending()
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

    def _repair_for_mobile(self) -> None:
        target = self.last_target_file or self.last_source_file
        if self._on_repair_mobile is not None:
            self._on_repair_mobile(target)
            return
        if target is None or not target.exists():
            chosen = filedialog.askopenfilename(
                title=t("repair_for_mobile", self._lang()),
                filetypes=[("Video files", "*.mp4 *.mov *.m4v"), ("All files", "*.*")],
            )
            if not chosen:
                return
            target = Path(chosen)
        from ..core.bxd_patcher import repair_for_mobile

        try:
            out_path = target.with_name(f"{target.stem}_mobile_repaired{target.suffix}")
            repair_for_mobile(target, out_path)
            self.append(f"Repaired for mobile: {out_path.name}", "OK")
        except Exception as exc:
            self.append(f"Mobile repair failed: {exc}", "ERROR")

    def _show_overflow_btn_menu(self) -> None:
        lang = self._lang()
        menu = Menu(self, tearoff=0)
        menu.add_command(
            label=t("save_diag_log", lang),
            command=self._save_diagnostic_log,
        )
        menu.add_command(
            label=t("open_logs_folder", lang),
            command=self._open_logs_folder,
        )
        menu.add_command(
            label=f"🔧 {t('repair_for_mobile', lang)}",
            command=self._repair_for_mobile,
        )
        menu.add_separator()
        menu.add_command(
            label=f"{'✓ ' if bool(self.verbose.get()) else ''}{t('ffmpeg_logs', lang)}",
            command=self._toggle_verbose_from_menu,
        )
        x = self.btn_more.winfo_rootx()
        y = self.btn_more.winfo_rooty() - 90
        menu.post(x, max(0, y))

    def _toggle_verbose_from_menu(self) -> None:
        self.verbose.toggle()
        self._on_verbose_toggled()
