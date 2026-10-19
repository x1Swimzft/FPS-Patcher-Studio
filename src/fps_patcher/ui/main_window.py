"""Root window: CTk + tkdnd wrapper, layout, event dispatch, and glass backdrop."""

from __future__ import annotations

import contextlib
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
from .icons import get_icon
from .info_panel import InfoPanel
from .input_list import InputList
from .log_console import LogConsole
from .settings_window import SettingsWindow
from .strings import t
from .theme import (
    RADIUS_PILL,
    STATUS_DANGER_BG,
    STATUS_DANGER_TEXT,
    STATUS_MUTED_BG,
    STATUS_MUTED_TEXT,
    STATUS_SUCCESS_BG,
    STATUS_SUCCESS_TEXT,
    ThemeTokens,
    apply_window_backdrop,
    font_badge,
    font_body,
    font_caption,
    font_title,
    get_corner_radii,
    get_theme_manager,
    update_title_bar_theme,
)

log = logging.getLogger("fps_patcher.ui.main_window")

POLL_MS = 50
INSPECTOR_WIDTH = 340

__all__ = ["MainWindow", "update_title_bar_theme"]


class MainWindow(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)
        self.settings = settings
        self.controller = AppController(settings)
        self._last_output: Path | None = None
        self._forensic_win: Any = None
        self._settings_win: Any = None
        self._applied_ui_scale: int = 100
        self._theme_mgr = get_theme_manager(settings)
        self._window_has_focus: bool = True
        self._focus_debounce_timer: str | None = None

        ctk.set_appearance_mode(settings.appearance)
        self._apply_ui_scale(settings.ui_scale)
        self.title(APP_NAME)

        if settings.remember_geometry and settings.geometry:
            try:
                self.geometry(settings.geometry)
            except Exception:
                self.geometry("1120x760")
        else:
            self.geometry("1120x760")

        self.minsize(920, 640)
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
        self._refresh_theme(tokens)

        # Layout grid:
        # Row 0: Unified toolbar (~52px)
        # Row 1: Main split (Col 0 = File Queue, Col 1 = ~340px Inspector, minsize 340px)
        # Row 2: Bottom collapsible Activity Console
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0, minsize=INSPECTOR_WIDTH)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1, minsize=340)
        self.grid_rowconfigure(2, weight=0)

        self._build_header()

        # Left column: File Queue
        self.input_list = InputList(
            self,
            controller=self.controller,
            on_start_patch_selected=lambda: self._start_patch(only_selected=True),
        )
        if hasattr(self.input_list, "set_on_focus_change"):
            self.input_list.set_on_focus_change(self._on_queue_focus_changed)
        self.input_list.grid(row=1, column=0, sticky="nsew", padx=(12, 8), pady=10)

        # Right column: Inspector (~340px fixed) with scrollable body + pinned footer
        self.inspector_container = ctk.CTkFrame(
            self,
            width=INSPECTOR_WIDTH,
            corner_radius=0,
            fg_color=tokens.inspector_bg,
            border_width=1,
            border_color=tokens.border,
        )
        self.inspector_container.grid(row=1, column=1, sticky="nsew", padx=0, pady=0)
        self.inspector_container.grid_propagate(False)
        self.inspector_container.grid_columnconfigure(0, weight=1)
        self.inspector_container.grid_rowconfigure(0, weight=1)
        self.inspector_container.grid_rowconfigure(1, weight=0)
        self.inspector_container.grid_rowconfigure(2, weight=0)

        self.inspector_pane = ctk.CTkScrollableFrame(
            self.inspector_container,
            width=INSPECTOR_WIDTH - 16,
            corner_radius=0,
            fg_color=tokens.inspector_bg,
            border_width=0,
        )
        self.inspector_pane.grid(row=0, column=0, sticky="nsew", padx=2, pady=(2, 0))
        self.inspector_pane.grid_columnconfigure(0, weight=1)

        self.inspector_footer_divider = ctk.CTkFrame(
            self.inspector_container,
            height=1,
            fg_color=tokens.border,
            corner_radius=0,
        )
        self.inspector_footer_divider.grid(row=1, column=0, sticky="ew")

        self.inspector_footer = ctk.CTkFrame(
            self.inspector_container,
            corner_radius=0,
            fg_color=tokens.inspector_bg,
            border_width=0,
        )
        self.inspector_footer.grid(row=2, column=0, sticky="ew", padx=1, pady=(0, 1))

        self.controls = ControlPanel(
            self.inspector_pane,
            settings,
            on_patch=lambda ts, strat: self._start_patch(ts, strat, only_selected=True),
            on_cancel=self._handle_cancel,
            on_strategy_change=self._refresh_state,
            on_override_change=self._on_item_override_changed,
            footer_master=self.inspector_footer,
        )
        self.controls.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 2))

        self.info_panel = InfoPanel(self.inspector_pane)
        self.info_panel.grid(row=1, column=0, sticky="ew", padx=6, pady=(2, 6))

        # Restore persisted queue if present
        queue_save_file = app_data_dir() / "queue.json"
        if queue_save_file.exists():
            restored = InputQueue.load(queue_save_file, migrate_legacy=True)
            if len(restored) > 0:
                self.controller.items = restored
                self.controller.queue = restored.paths()
                self.input_list.render()
                self._sync_info_panel()

        # Bottom row: Activity Console drawer
        self.console = LogConsole(self, on_repair_mobile=self._repair_for_mobile_from_console)
        self.console.grid(row=2, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        if queue_save_file.exists() and self.controller.items.migrated_overrides:
            for fname, old_s, new_s in self.controller.items.migrated_overrides:
                self.console.append(
                    f"[CONFIG] Queue item '{fname}' preset migrated: '{old_s}' -> '{new_s}'",
                    "INFO",
                )

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

        # Window focus tracking (<FocusIn>, <FocusOut>)
        self.bind("<FocusIn>", self._on_window_focus_in, add="+")
        self.bind("<FocusOut>", self._on_window_focus_out, add="+")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._theme_mgr.subscribe(self._on_theme_updated)

        self._init_ffmpeg()
        self.after(POLL_MS, self._poll)

    # ---------- window focus awareness ----------
    def _on_window_focus_in(self, event: Any) -> None:
        if self._focus_debounce_timer is not None:
            self.after_cancel(self._focus_debounce_timer)
            self._focus_debounce_timer = None
        self._update_window_focus(True)

    def _on_window_focus_out(self, event: Any) -> None:
        if self._focus_debounce_timer is not None:
            self.after_cancel(self._focus_debounce_timer)
        self._focus_debounce_timer = self.after(35, self._debounced_check_focus)

    def _debounced_check_focus(self) -> None:
        self._focus_debounce_timer = None
        try:
            focused = self.focus_get() is not None
        except Exception:
            focused = False
        self._update_window_focus(focused)

    def _update_window_focus(self, focused: bool) -> None:
        if getattr(self, "_window_has_focus", None) == focused:
            return
        self._window_has_focus = focused
        if hasattr(self, "input_list") and hasattr(self.input_list, "set_window_focused"):
            self.input_list.set_window_focused(focused)

    def set_window_focused(self, focused: bool) -> None:
        """Explicitly set window focus state (used by OS listeners or tests)."""
        self._update_window_focus(focused)

    @property
    def is_window_focused(self) -> bool:
        return getattr(self, "_window_has_focus", True)

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
            "checkbox",
            "segmentedbutton",
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

    # ---------- layout: unified toolbar (~52px) ----------
    def _build_header(self) -> None:
        tokens = self._theme_mgr.tokens
        _, ctrl_rad = get_corner_radii(self.settings.radius_style)
        fsize = self.settings.font_size
        lang = self.settings.language

        self.header_bar = ctk.CTkFrame(
            self,
            height=52,
            fg_color=tokens.toolbar_bg,
            border_width=0,
            corner_radius=0,
        )
        self.header_bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.header_bar.grid_propagate(False)
        self.header_bar.grid_columnconfigure(1, weight=1)
        self.header_bar.grid_rowconfigure(0, weight=1)

        # Left branding: OS title bar already shows APP_NAME; toolbar shows version badge
        brand_frame = ctk.CTkFrame(self.header_bar, fg_color="transparent")
        brand_frame.grid(row=0, column=0, sticky="w", padx=(16, 0), pady=8)

        self.brand_title = ctk.CTkLabel(
            brand_frame,
            text=t("app_title", lang),
            font=font_title(fsize),
            text_color=tokens.text,
        )

        self.version_badge = ctk.CTkLabel(
            brand_frame,
            text=f"v{__version__}",
            font=font_badge(fsize),
            fg_color=tokens.accent_light,
            text_color=tokens.accent,
            corner_radius=6,
            padx=8,
            height=22,
        )
        self.version_badge.pack(side="left")
        # Compatibility alias
        self.brand_dot = self.version_badge

        # Right toolbar items
        right_frame = ctk.CTkFrame(self.header_bar, fg_color="transparent")
        right_frame.grid(row=0, column=2, sticky="e", padx=(0, 14), pady=8)

        # 1. FFmpeg status pill (click/right-click to pick folder; checking / ready / not found)
        self._ff_state = "checking"
        self.ff_badge = ctk.CTkButton(
            right_frame,
            text=t("checking_ffmpeg", lang),
            corner_radius=RADIUS_PILL,
            height=28,
            width=120,
            font=font_badge(fsize),
            fg_color=STATUS_MUTED_BG,
            hover_color=tokens.surface_hover,
            text_color=STATUS_MUTED_TEXT,
            border_width=0,
            command=self._pick_ffmpeg,
        )
        self.ff_badge.pack(side="left", padx=(0, 6))
        self.ff_badge.bind("<Button-3>", self._show_ffmpeg_menu)
        # Compatibility alias for ffmpeg_pick_btn
        self.ffmpeg_pick_btn = self.ff_badge

        # 2. Forensic / X1T button (soft tinted)
        self.forensic_btn = ctk.CTkButton(
            right_frame,
            text=t("forensic_btn", lang),
            image=get_icon("forensic", (15, 15)),
            compound="left",
            height=28,
            width=120,
            corner_radius=ctrl_rad,
            command=self._open_forensic,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            border_width=0,
            font=font_caption(fsize),
        )
        self.forensic_btn.pack(side="left", padx=(0, 6))

        # 3. Output Folder button (soft tinted)
        self.open_btn = ctk.CTkButton(
            right_frame,
            text=t("open_output_btn", lang),
            image=get_icon("folder", (15, 15)),
            compound="left",
            height=28,
            width=120,
            corner_radius=ctrl_rad,
            command=self._open_output,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            border_width=0,
            font=font_caption(fsize),
        )
        self.open_btn.pack(side="left", padx=(0, 6))

        # 4. Settings icon button
        settings_ico = get_icon("settings", (16, 16))
        self.settings_btn = ctk.CTkButton(
            right_frame,
            text="" if settings_ico else "⚙",
            image=settings_ico,
            width=30,
            height=28,
            corner_radius=ctrl_rad,
            command=self._open_settings,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            border_width=0,
            font=font_body(size_opt=fsize),
        )
        self.settings_btn.pack(side="left", padx=(0, 6))

        # 5. Dark / Light toggle button (reads/writes settings.appearance; right-click for System)
        theme_ico = self._appearance_icon_image()
        self.theme_toggle_btn = ctk.CTkButton(
            right_frame,
            text="" if theme_ico else self._appearance_icon(),
            image=theme_ico,
            width=30,
            height=28,
            corner_radius=ctrl_rad,
            command=self._toggle_appearance,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            border_width=0,
            font=font_body(size_opt=fsize),
        )
        self.theme_toggle_btn.pack(side="left")
        self.theme_toggle_btn.bind("<Button-3>", self._show_appearance_menu)

        # Bottom 1px hairline border for toolbar
        self.header_divider = ctk.CTkFrame(
            self.header_bar,
            height=1,
            fg_color=tokens.border,
            corner_radius=0,
        )
        self.header_divider.grid(row=1, column=0, columnspan=3, sticky="ew")

    def _appearance_icon(self) -> str:
        is_dark = ctk.get_appearance_mode().lower() == "dark"
        return "☀" if is_dark else "☾"

    def _appearance_icon_image(self) -> ctk.CTkImage | None:
        is_dark = ctk.get_appearance_mode().lower() == "dark"
        return get_icon("sun" if is_dark else "moon", (16, 16))

    def _toggle_appearance(self) -> None:
        is_dark = ctk.get_appearance_mode().lower() == "dark"
        self.settings.appearance = "light" if is_dark else "dark"
        self._theme_mgr.apply(self.settings)
        self.settings.save()

    def _set_appearance_mode(self, mode: str) -> None:
        self.settings.appearance = mode
        self._theme_mgr.apply(self.settings)
        self.settings.save()

    def _show_appearance_menu(self, event: Any) -> None:
        from tkinter import Menu

        lang = self.settings.language
        menu = Menu(self, tearoff=0)
        menu.add_command(
            label=t("mode_light", lang),
            command=lambda: self._set_appearance_mode("light"),
        )
        menu.add_command(
            label=t("mode_dark", lang),
            command=lambda: self._set_appearance_mode("dark"),
        )
        menu.add_command(
            label=t("mode_system", lang),
            command=lambda: self._set_appearance_mode("system"),
        )
        menu.post(event.x_root, event.y_root)

    def _show_ffmpeg_menu(self, event: Any) -> None:
        from tkinter import Menu

        lang = self.settings.language
        menu = Menu(self, tearoff=0)
        menu.add_command(
            label=t("ffmpeg_folder_btn", lang),
            command=self._pick_ffmpeg,
        )
        menu.post(event.x_root, event.y_root)

    def _apply_ff_badge_style(self, tokens: ThemeTokens) -> None:
        lang = self.settings.language
        fsize = self.settings.font_size
        if self._ff_state == "ready":
            self.ff_badge.configure(
                text=t("ffmpeg_ok", lang),
                fg_color=STATUS_SUCCESS_BG,
                hover_color=tokens.surface_hover,
                text_color=STATUS_SUCCESS_TEXT,
                font=font_badge(fsize),
            )
        elif self._ff_state == "not_found":
            self.ff_badge.configure(
                text=t("ffmpeg_not_found", lang),
                fg_color=STATUS_DANGER_BG,
                hover_color=tokens.surface_hover,
                text_color=STATUS_DANGER_TEXT,
                font=font_badge(fsize),
            )
        else:
            self.ff_badge.configure(
                text=t("checking_ffmpeg", lang),
                fg_color=STATUS_MUTED_BG,
                hover_color=tokens.surface_hover,
                text_color=STATUS_MUTED_TEXT,
                font=font_badge(fsize),
            )

    def _refresh_theme(self, tokens: ThemeTokens | None = None) -> None:
        """Update window title bar and theme styling."""
        if tokens is None:
            tokens = self._theme_mgr.tokens
        is_dark = ctk.get_appearance_mode().lower() == "dark"
        caption_bg = tokens.toolbar_bg[1] if is_dark else tokens.toolbar_bg[0]
        update_title_bar_theme(self, is_dark=is_dark, bg_color=caption_bg)

    def update_title_bar_theme(
        self, is_dark: bool | None = None, bg_color: str | None = None
    ) -> None:
        """Instance method to update title bar theme."""
        if is_dark is None:
            is_dark = ctk.get_appearance_mode().lower() == "dark"
        if bg_color is None:
            tokens = self._theme_mgr.tokens
            bg_color = tokens.toolbar_bg[1] if is_dark else tokens.toolbar_bg[0]
        update_title_bar_theme(self, is_dark=is_dark, bg_color=bg_color)

    def _apply_ui_scale(self, ui_scale: int) -> None:
        import contextlib

        clamped = max(90, min(150, int(ui_scale)))
        if clamped == self._applied_ui_scale:
            return
        self._applied_ui_scale = clamped
        with contextlib.suppress(Exception):
            ctk.set_widget_scaling(clamped / 100.0)

    def _on_theme_updated(self, tokens: ThemeTokens) -> None:
        """Dynamically update main window appearance and backdrop."""
        self._refresh_theme(tokens)
        _, ctrl_rad = get_corner_radii(self.settings.radius_style)
        fsize = self.settings.font_size
        lang = self.settings.language

        self.configure(fg_color=tokens.bg)
        self.header_bar.configure(fg_color=tokens.toolbar_bg)
        self.header_divider.configure(fg_color=tokens.border)
        self.inspector_container.configure(
            fg_color=tokens.inspector_bg,
            border_color=tokens.border,
        )
        self.inspector_pane.configure(fg_color=tokens.inspector_bg)
        self.inspector_footer_divider.configure(fg_color=tokens.border)
        self.inspector_footer.configure(fg_color=tokens.inspector_bg)

        self.brand_title.configure(
            text=t("app_title", lang),
            text_color=tokens.text,
            font=font_title(fsize),
        )
        self.version_badge.configure(
            fg_color=tokens.accent_light,
            text_color=tokens.accent,
            font=font_badge(fsize),
        )
        self._apply_ff_badge_style(tokens)

        self.forensic_btn.configure(
            text=t("forensic_btn", lang),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.open_btn.configure(
            text=t("open_output_btn", lang),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.settings_btn.configure(
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            corner_radius=ctrl_rad,
            font=font_body(size_opt=fsize),
        )
        theme_ico = self._appearance_icon_image()
        self.theme_toggle_btn.configure(
            text="" if theme_ico else self._appearance_icon(),
            image=theme_ico,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            corner_radius=ctrl_rad,
            font=font_body(size_opt=fsize),
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
        self._apply_ui_scale(settings.ui_scale)
        if settings.always_on_top:
            self.attributes("-topmost", True)
        else:
            self.attributes("-topmost", False)

        self._refresh_theme()
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
        self._ff_state = "checking"
        self._apply_ff_badge_style(self._theme_mgr.tokens)
        paths = self.controller.init_ffmpeg()
        self._ff_state = "ready" if paths else "not_found"
        self._apply_ff_badge_style(self._theme_mgr.tokens)
        self._refresh_state()
        self._probe_pending_queue_items()

    def _probe_pending_queue_items(self) -> None:
        """Probe any restored/pending queue items whose metadata has not been populated yet."""
        import threading

        from ..core.errors import FPSPatcherError
        from ..core.prober import probe

        pending_paths = [
            it.path
            for it in self.controller.items.items
            if it.info is None and it.status == "pending"
        ]
        if not pending_paths:
            return

        ffprobe_path = self.controller.ffmpeg.ffprobe if self.controller.ffmpeg else None

        def probe_restored() -> None:
            for path in pending_paths:
                if self.controller.items.get(path) is None:
                    continue
                self.controller.items.set_status(path, "probing")
                self.controller.emit(QueueChangedEvent("probing"))
                try:
                    info = probe(path, ffprobe_path)
                    self.controller.items.set_info(path, info)
                except FPSPatcherError as exc:
                    self.controller.items.set_info(path, None, str(exc))
                    self.controller.emit(LogEvent(f"Probe failed {path.name}: {exc}", "ERROR"))
                self.controller.emit(QueueChangedEvent("probed"))

        threading.Thread(target=probe_restored, daemon=True).start()

    def _pick_ffmpeg(self) -> None:
        chosen = filedialog.askdirectory(title="Folder containing ffmpeg.exe and ffprobe.exe")
        if chosen:
            self.settings.ffmpeg_dir = chosen
            self._init_ffmpeg()

    def _repair_for_mobile_from_console(self, candidate: Path | None = None) -> None:
        target = candidate
        if target is None or not target.exists():
            focused = getattr(self.input_list, "_focused_path", None)
            if focused is not None and focused.exists():
                target = focused
            elif self.controller.items.selected():
                target = self.controller.items.selected()[0].path
            elif self.controller.queue:
                target = self.controller.queue[-1]
        if target is None or not target.exists():
            chosen = filedialog.askopenfilename(
                title=t("repair_for_mobile", self.settings.language),
                filetypes=[("Video files", "*.mp4 *.mov *.m4v"), ("All files", "*.*")],
            )
            if not chosen:
                return
            target = Path(chosen)
        self.controller.repair_file_for_mobile(target)

    # ---------- info panel & override sync ----------
    def _on_item_override_changed(
        self, item_path: Path, timescale: int | None, strategy: str | None
    ) -> None:
        self.controller.items.set_override(
            item_path,
            timescale=timescale,
            strategy=strategy,
        )
        self.input_list.render()
        self._sync_info_panel(item_path)

    def _on_queue_focus_changed(self, item_path: Path | None) -> None:
        self._sync_info_panel(item_path)

    def _sync_info_panel(self, focus_path: Path | None = None) -> None:
        items = self.controller.items.items
        if not items:
            self.info_panel.clear()
            self.controls.set_focused_item(None)
            return
        if focus_path is None:
            focus_path = getattr(self.input_list, "_focused_path", None)
        target_idx = 0
        if focus_path is not None:
            for idx, it in enumerate(items):
                if it.path == focus_path:
                    target_idx = idx
                    break
        else:
            # Prefer last item with probed info
            for idx in range(len(items) - 1, -1, -1):
                if items[idx].info is not None:
                    target_idx = idx
                    break
        target_item = items[target_idx]
        self.controls.set_focused_item(target_item)
        if target_item.info is not None:
            self.info_panel.show_info(
                target_item.info,
                queue_index=target_idx + 1,
                queue_total=len(items),
            )
        else:
            self.info_panel.clear()

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
            self._sync_info_panel()

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
        if self._last_output and self._last_output.exists():
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", str(self._last_output)])
            else:
                subprocess.Popen(["xdg-open", str(self._last_output.parent)])
            return
        target_dir: Path | None = None
        if self.settings.output_dir:
            p = Path(self.settings.output_dir)
            if p.exists():
                target_dir = p
        if target_dir is None and self.controller.queue:
            target_dir = self.controller.queue[-1].parent
        if target_dir and target_dir.exists():
            if hasattr(os, "startfile"):
                os.startfile(str(target_dir))
            else:
                subprocess.Popen(["xdg-open", str(target_dir)])

    def _refresh_state(self) -> None:
        has_items = bool(self.controller.queue or self.controller.current)
        strategy = self.controls.get_strategy()
        needs_ff = strategy_requires_ffmpeg(strategy)
        can_patch = has_items and (not needs_ff or self.controller.ffmpeg is not None)
        busy = self.controller.busy
        if (
            getattr(self, "_last_can_patch", None) != can_patch
            or getattr(self, "_last_busy", None) != busy
        ):
            self._last_can_patch = can_patch
            self._last_busy = busy
            self.controls.set_state(
                can_patch=can_patch,
                busy=busy,
            )
            self.input_list.set_state(busy=busy)

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
            self._sync_info_panel()
        elif isinstance(event, ProbeDoneEvent):
            self.input_list.render()
            self._sync_info_panel()
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
            self._sync_info_panel()
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
        if self._focus_debounce_timer is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._focus_debounce_timer)
            self._focus_debounce_timer = None
        self.controller.cancel()
        try:
            if self.settings.remember_geometry:
                self.settings.geometry = self.geometry()
            self.settings.save()
            # Save queue persistence
            self.controller.items.save(app_data_dir() / "queue.json")
        finally:
            self.destroy()
