"""Root window: CTk + tkdnd wrapper, layout, event dispatch, and glass backdrop."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk
from tkinterdnd2 import TkinterDnD

from .. import APP_NAME, __version__
from ..app.controller import AppController
from ..app.queue_model import InputQueue
from ..config import Settings, app_data_dir
from ..core.models import (
    Event,
    LogEvent,
    PatchDoneEvent,
    ProbeDoneEvent,
    ProgressEvent,
    QueueChangedEvent,
)
from ..core.strategies import strategy_requires_ffmpeg
from .control_panel import ControlPanel
from .input_list import InputList
from .log_console import LogConsole
from .settings_window import SettingsWindow
from .strings import t
from .theme import (
    RADIUS_CARD,
    RADIUS_CONTROL,
    RADIUS_PILL,
    STATUS_MUTED_BG,
    STATUS_MUTED_TEXT,
    STATUS_SUCCESS_BG,
    STATUS_SUCCESS_TEXT,
    ThemeTokens,
    apply_window_backdrop,
    font_caption,
    font_title,
    get_theme_manager,
)

log = logging.getLogger("fps_patcher.ui.main_window")

POLL_MS = 50


class MainWindow(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)
        self.settings = settings
        self.controller = AppController(settings)
        self._last_output: Path | None = None
        self._forensic_win: Any = None
        self._settings_win: Any = None
        self._theme_mgr = get_theme_manager(settings)

        ctk.set_appearance_mode(settings.appearance)
        self.title(f"{APP_NAME} v{__version__}")

        if settings.remember_geometry and settings.geometry:
            try:
                self.geometry(settings.geometry)
            except Exception:
                self.geometry("1000x720")
        else:
            self.geometry("1000x720")

        self.minsize(900, 640)
        tokens = self._theme_mgr.tokens
        self.configure(fg_color=tokens.bg)

        if settings.always_on_top:
            self.attributes("-topmost", True)

        # Apply real window backdrop with tint suppression
        apply_window_backdrop(
            self,
            glass=settings.glass,
            alpha=settings.window_alpha,
            backdrop_mode=settings.glass_mode,
            tint_strength=settings.tint_strength,
        )

        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()

        # Input List (Screenshot 2 Target Design) replaces single drop zone & info panel
        self.input_list = InputList(
            self,
            controller=self.controller,
            on_start_patch_selected=lambda: self._start_patch(only_selected=True),
        )
        self.input_list.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=16, pady=(10, 6))

        # Restore persisted queue if present
        queue_save_file = app_data_dir() / "queue.json"
        if queue_save_file.exists():
            restored = InputQueue.load(queue_save_file, migrate_legacy=True)
            if len(restored) > 0:
                self.controller.items = restored
                self.controller.queue = restored.paths()
                self.input_list.render()

        self.console = LogConsole(self)
        self.console.grid(row=2, column=0, sticky="nsew", padx=(16, 8), pady=(6, 16))
        if queue_save_file.exists() and self.controller.items.migrated_overrides:
            for fname, old_s, new_s in self.controller.items.migrated_overrides:
                self.console.append(
                    f"[CONFIG] Queue item '{fname}' preset migrated: '{old_s}' -> '{new_s}'",
                    "INFO",
                )

        self.controls = ControlPanel(
            self,
            settings,
            on_patch=lambda ts, strat: self._start_patch(ts, strat, only_selected=True),
            on_cancel=self._handle_cancel,
            on_strategy_change=self._refresh_state,
        )
        self.controls.grid(row=2, column=1, sticky="nsew", padx=(8, 16), pady=(6, 16))

        # Drag and drop files & folders support
        self.drop_target_register("DND_Files")
        self.dnd_bind("<<Drop>>", self._on_window_drop)

        self._setup_window_dragging()

        # Keyboard shortcuts (F11)
        self.bind("<Control-comma>", lambda _: self._open_settings())
        self.bind("<Control-a>", lambda _: self._kbd_select_all())
        self.bind("<Control-A>", lambda _: self._kbd_select_all())
        self.bind("<Delete>", lambda _: self.controller.remove_selected())
        self.bind("<Control-o>", lambda _: self.input_list._browse_files())
        self.bind("<Control-O>", lambda _: self.input_list._browse_files())
        self.bind("<Return>", lambda _: self._kbd_apply_selected())

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._theme_mgr.subscribe(self._on_theme_updated)

        self._init_ffmpeg()
        self.after(POLL_MS, self._poll)

    # ---------- window drag handling ----------
    def _setup_window_dragging(self) -> None:
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_active = False

        # bind_all catches clicks on any internal canvas/frame/label in CustomTkinter
        self.bind_all("<ButtonPress-1>", self._on_drag_start, add="+")
        self.bind_all("<B1-Motion>", self._on_drag_motion, add="+")
        self.bind_all("<ButtonRelease-1>", self._on_drag_release, add="+")

    def _is_interactive_widget(self, widget: Any) -> bool:
        """Check if widget or any parent is an interactive control."""
        curr = widget
        interactive_names = (
            "button",
            "entry",
            "combobox",
            "optionmenu",
            "switch",
            "slider",
            "scrollbar",
            "text",
            "textbox",
        )
        while curr is not None:
            cname = getattr(curr, "__class__", type(curr)).__name__.lower()
            if any(name in cname for name in interactive_names):
                return True
            curr = getattr(curr, "master", None)
        return False

    def _on_drag_start(self, event: Any) -> None:
        widget = getattr(event, "widget", None)
        if widget is None or self._is_interactive_widget(widget):
            self._drag_active = False
            return

        self._drag_active = True
        self._drag_start_x = event.x_root - self.winfo_x()
        self._drag_start_y = event.y_root - self.winfo_y()

    def _on_drag_motion(self, event: Any) -> None:
        if not self._drag_active:
            return
        new_x = event.x_root - self._drag_start_x
        new_y = event.y_root - self._drag_start_y
        self.geometry(f"+{new_x}+{new_y}")

    def _on_drag_release(self, event: Any) -> None:
        self._drag_active = False

    # ---------- layout ----------
    def _build_header(self) -> None:
        tokens = self._theme_mgr.tokens
        self.header_bar = ctk.CTkFrame(
            self,
            height=46,
            fg_color=tokens.surface,
            border_width=1,
            border_color=tokens.border,
            corner_radius=RADIUS_CARD,
        )
        self.header_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(14, 2))
        self.header_bar.grid_columnconfigure(1, weight=1)

        # Left branding: Accent glowing dot + Title
        brand_frame = ctk.CTkFrame(self.header_bar, fg_color="transparent")
        brand_frame.grid(row=0, column=0, sticky="w", padx=(16, 0), pady=8)

        self.brand_dot = ctk.CTkLabel(
            brand_frame,
            text="●",
            font=ctk.CTkFont(size=14),
            text_color=tokens.accent,
        )
        self.brand_dot.pack(side="left", padx=(0, 6))

        self.brand_title = ctk.CTkLabel(
            brand_frame,
            text=APP_NAME,
            font=font_title(),
            text_color=tokens.text,
        )
        self.brand_title.pack(side="left")

        # Right action items
        right_frame = ctk.CTkFrame(self.header_bar, fg_color="transparent")
        right_frame.grid(row=0, column=2, sticky="e", padx=(0, 12), pady=6)

        # Forensic button
        self.forensic_btn = ctk.CTkButton(
            right_frame,
            text=t("forensic_btn", self.settings.language),
            height=32,
            corner_radius=RADIUS_CONTROL,
            command=self._open_forensic,
            fg_color=tokens.surface_raised,
            hover_color=tokens.border,
            text_color=tokens.text,
            border_width=1,
            border_color=tokens.border,
            font=font_caption(),
        )
        self.forensic_btn.pack(side="left", padx=(0, 8))

        # FFmpeg status pill badge
        self.ff_badge = ctk.CTkLabel(
            right_frame,
            text=t("checking_ffmpeg", self.settings.language),
            corner_radius=RADIUS_PILL,
            padx=12,
            height=28,
            font=font_caption(),
            fg_color=STATUS_MUTED_BG,
            text_color=STATUS_MUTED_TEXT,
        )
        self.ff_badge.pack(side="left", padx=(0, 8))

        # FFmpeg folder picker ghost button
        self.ffmpeg_pick_btn = ctk.CTkButton(
            right_frame,
            text=t("ffmpeg_folder_btn", self.settings.language),
            width=115,
            height=32,
            corner_radius=RADIUS_CONTROL,
            command=self._pick_ffmpeg,
            fg_color="transparent",
            hover_color=tokens.surface_raised,
            text_color=tokens.text,
            border_width=1,
            border_color=tokens.border,
            font=font_caption(),
        )
        self.ffmpeg_pick_btn.pack(side="left", padx=(0, 8))

        # Open output folder button
        self.open_btn = ctk.CTkButton(
            right_frame,
            text=t("open_output_btn", self.settings.language),
            width=100,
            height=32,
            corner_radius=RADIUS_CONTROL,
            state="disabled",
            command=self._open_output,
            fg_color="transparent",
            hover_color=tokens.surface_raised,
            text_color=tokens.text,
            border_width=1,
            border_color=tokens.border,
            font=font_caption(),
        )
        self.open_btn.pack(side="left", padx=(0, 8))

        # ⚙ Settings Icon Button (Replacing old inline switch)
        self.settings_btn = ctk.CTkButton(
            right_frame,
            text=t("settings_btn", self.settings.language),
            width=90,
            height=32,
            corner_radius=RADIUS_CONTROL,
            command=self._open_settings,
            fg_color=tokens.surface_raised,
            hover_color=tokens.border,
            text_color=tokens.text,
            border_width=1,
            border_color=tokens.border,
            font=font_caption(),
        )
        self.settings_btn.pack(side="left", padx=(0, 4))

    def _on_theme_updated(self, tokens: ThemeTokens) -> None:
        """Dynamically update main window appearance and backdrop."""
        self.configure(fg_color=tokens.bg)
        self.header_bar.configure(fg_color=tokens.surface, border_color=tokens.border)
        self.brand_dot.configure(text_color=tokens.accent)
        self.brand_title.configure(text_color=tokens.text)
        self.forensic_btn.configure(
            fg_color=tokens.surface_raised,
            hover_color=tokens.border,
            text_color=tokens.text,
            border_color=tokens.border,
        )
        self.ffmpeg_pick_btn.configure(
            hover_color=tokens.surface_raised,
            text_color=tokens.text,
            border_color=tokens.border,
        )
        self.open_btn.configure(
            hover_color=tokens.surface_raised,
            text_color=tokens.text,
            border_color=tokens.border,
        )
        self.settings_btn.configure(
            fg_color=tokens.surface_raised,
            hover_color=tokens.border,
            text_color=tokens.text,
            border_color=tokens.border,
        )
        apply_window_backdrop(
            self,
            glass=self.settings.glass,
            alpha=self.settings.window_alpha,
            backdrop_mode=self.settings.glass_mode,
            tint_strength=self.settings.tint_strength,
        )

    def _open_settings(self) -> None:
        if self._settings_win is None or not self._settings_win.winfo_exists():
            self._settings_win = SettingsWindow(
                self, self.settings, on_applied=self._on_settings_applied
            )
        else:
            self._settings_win.focus()

    def _on_settings_applied(self, settings: Settings) -> None:
        self.settings = settings
        if settings.always_on_top:
            self.attributes("-topmost", True)
        else:
            self.attributes("-topmost", False)

        apply_window_backdrop(
            self,
            glass=settings.glass,
            alpha=settings.window_alpha,
            backdrop_mode=settings.glass_mode,
            tint_strength=settings.tint_strength,
        )
        self._init_ffmpeg()

    def _open_forensic(self) -> None:
        from .forensic_window import ForensicWindow

        if self._forensic_win is None or not self._forensic_win.winfo_exists():
            self._forensic_win = ForensicWindow(self)
        else:
            self._forensic_win.focus()

    # ---------- ffmpeg ----------
    def _init_ffmpeg(self) -> None:
        paths = self.controller.init_ffmpeg()
        if paths:
            self.ff_badge.configure(
                text=t("ffmpeg_ok", self.settings.language),
                fg_color=STATUS_SUCCESS_BG,
                text_color=STATUS_SUCCESS_TEXT,
            )
        else:
            self.ff_badge.configure(
                text="○ Direct mode ready",
                fg_color=STATUS_MUTED_BG,
                text_color=STATUS_MUTED_TEXT,
            )
        self._refresh_state()

    def _pick_ffmpeg(self) -> None:
        chosen = filedialog.askdirectory(title="Folder containing ffmpeg.exe and ffprobe.exe")
        if chosen:
            self.settings.ffmpeg_dir = chosen
            self._init_ffmpeg()

    # ---------- actions ----------
    def _start_patch(
        self, timescale: int | None = None, strategy: str | None = None, only_selected: bool = True
    ) -> None:
        eff_ts = timescale if timescale is not None else self.controls._read_timescale() or 60000
        eff_strat = strategy if strategy is not None else self.controls.get_strategy()
        self.controls.set_batch_progress(0, 0, "Starting patch...", "Starting batch...")
        self.controller.start_patch(eff_ts, eff_strat, only_selected=only_selected)
        self._refresh_state()

    def _kbd_select_all(self) -> None:
        self.input_list._toggle_select_all()

    def _kbd_apply_selected(self) -> None:
        self._start_patch(only_selected=True)

    def _on_window_drop(self, event: Any) -> None:
        data = getattr(event, "data", "")
        if not data:
            return
        import re

        from ..core.models import SUPPORTED_EXTENSIONS

        # Split paths safely from TkinterDnD data string (supports brace quoted paths)
        raw_paths = [p.strip("{}") for p in re.findall(r'\{[^}]+\}|\S+', data)]
        collected: list[Path] = []
        for p_str in raw_paths:
            p = Path(p_str)
            if p.is_dir():
                for root, _, files in os.walk(p):
                    for fn in files:
                        if Path(fn).suffix.lower() in SUPPORTED_EXTENSIONS:
                            collected.append(Path(root) / fn)
            elif p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                collected.append(p)

        if collected:
            self.controller.add_files(collected)
            self.input_list.render()

    def _handle_cancel(self) -> None:
        if self.settings.confirm_cancel:
            from tkinter import messagebox

            if not messagebox.askyesno(
                "Confirm Cancel",
                t("confirm_cancel_run", self.settings.language),
                parent=self,
            ):
                return
        self.controller.cancel()

    def _open_output(self) -> None:
        if not self._last_output:
            return
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(self._last_output)])
        else:
            subprocess.Popen(["xdg-open", str(self._last_output.parent)])

    def _refresh_state(self) -> None:
        has_items = bool(self.controller.queue or self.controller.current)
        strategy = self.controls.get_strategy()
        needs_ff = strategy_requires_ffmpeg(strategy)
        can_patch = has_items and (not needs_ff or self.controller.ffmpeg is not None)
        self.controls.set_state(
            can_patch=can_patch,
            busy=self.controller.busy,
        )

    # ---------- event loop ----------
    def _poll(self) -> None:
        try:
            self.controller.drain(self._handle)
            self._refresh_state()
        except Exception:
            log.exception("Unhandled error in UI poll loop")
        finally:
            self.after(POLL_MS, self._poll)

    def _handle(self, event: Event) -> None:
        if isinstance(event, LogEvent):
            self.console.append(event.message, event.level)
        elif isinstance(event, ProgressEvent):
            file_name = event.current_file.name if event.current_file else "File"
            file_pct = int(event.file_fraction * 100)
            overall_pct = int(event.fraction * 100)
            file_text = f"[{event.file_index}/{event.total_files}] {file_name}: {file_pct}%"
            batch_text = f"Batch progress ({event.file_index}/{event.total_files}): {overall_pct}%"
            self.controls.set_batch_progress(
                event.file_fraction,
                event.fraction,
                file_text,
                batch_text,
            )
        elif isinstance(event, QueueChangedEvent):
            self.input_list.render()
        elif isinstance(event, ProbeDoneEvent):
            self.input_list.render()
            if self.controller.queue:
                self.console.set_context_files(target=self.controller.queue[-1])
            if event.info:
                if event.queue_count > 1:
                    msg = (
                        f"Batch queued ({event.queue_count} files). "
                        f"1st clip: {event.info.fps:.3f} FPS"
                    )
                    self.console.append(msg, "OK")
                else:
                    self.console.append(f"Detected {event.info.fps:.3f} FPS", "OK")
            elif event.error:
                self.console.append(f"Probe failed: {event.error}", "ERROR")
        elif isinstance(event, PatchDoneEvent):
            self.input_list.render()
            if event.cancelled:
                self.controls.set_batch_progress(0, 0, "Cancelled", "Batch cancelled")
                self.console.append(f"Operation cancelled: {event.error}", "WARN")
                self._refresh_state()
            elif event.batch_results:
                self._last_output = event.batch_results[-1].output
                src_p = self.controller.queue[-1] if self.controller.queue else None
                self.console.set_context_files(target=self._last_output, source=src_p)
                self.open_btn.configure(state="normal")
                done_count = len(event.batch_results)
                n_exp = sum(1 for r in event.batch_results if r.experimental)
                n_ok = done_count - n_exp
                suffix = f" ({n_exp} experimental)" if n_exp else ""
                self.controls.set_batch_progress(
                    1.0,
                    1.0,
                    f"Done{suffix}: {done_count}/{event.total_files} files",
                    f"Completed{suffix}: {done_count}/{event.total_files} files",
                )
                self.console.append(
                    f"Batch finished: {done_count}/{event.total_files} files patched{suffix}.",
                    "WARN" if n_exp else "OK",
                )
                self._refresh_state()
                # F7: Batch summary dialog at end
                if event.total_files > 1 or event.failed or n_exp:
                    summary_msg = t(
                        "batch_summary_msg",
                        self.settings.language,
                        ok=n_ok,
                        failed=len(event.failed),
                        total=event.total_files,
                    )
                    if n_exp:
                        summary_msg += "\n" + t(
                            "batch_summary_experimental",
                            self.settings.language,
                            experimental=n_exp,
                        )
                    messagebox.showinfo(
                        t("batch_summary_title", self.settings.language),
                        summary_msg,
                        parent=self,
                    )
                if self.settings.open_when_done and self._last_output:
                    self._open_output()
            elif event.result:
                self._last_output = event.result.output
                src_p = self.controller.queue[-1] if self.controller.queue else None
                self.console.set_context_files(target=self._last_output, source=src_p)
                self.open_btn.configure(state="normal")
                self.controls.set_batch_progress(1.0, 1.0, "Done: 100%", "Batch completed")
                self._refresh_state()
                if self.settings.open_when_done and self._last_output:
                    self._open_output()
            else:
                self.controls.set_batch_progress(0, 0, "Failed", "Batch failed")
                self.console.append(f"Patch failed: {event.error}", "ERROR")
                for line in event.stderr_tail:
                    self.console.append(line, "WARN")
                self._refresh_state()
                if event.total_files > 1 or event.failed:
                    summary_msg = t(
                        "batch_summary_msg",
                        self.settings.language,
                        ok=len(event.batch_results),
                        failed=len(event.failed),
                        total=event.total_files,
                    )
                    messagebox.showerror(
                        t("batch_summary_title", self.settings.language),
                        summary_msg,
                        parent=self,
                    )

    def _on_close(self) -> None:
        self.controller.cancel()
        try:
            if self.settings.remember_geometry:
                self.settings.geometry = self.geometry()
            self.settings.save()
            # Save queue persistence
            self.controller.items.save(app_data_dir() / "queue.json")
        finally:
            self.destroy()
