"""Root window: CTk + tkdnd wrapper, layout, event dispatch, and glass backdrop."""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk
from PIL import Image, ImageTk
from tkinterdnd2 import TkinterDnD

from .. import APP_NAME, APP_USER_MODEL_ID, __version__
from ..app import shell_integration
from ..app.controller import AppController
from ..app.queue_model import InputQueue
from ..app.quick_patch import QUICK_PATCH_TIMESCALE
from ..app.watcher import FolderWatcher
from ..config import Settings, app_data_dir
from ..core.models import (
    Event,
    FFmpegDownloadEvent,
    LogEvent,
    LogLevel,
    PatchDoneEvent,
    ProbeDoneEvent,
    ProgressEvent,
    QueueChangedEvent,
    UpdateAvailableEvent,
    UpdateDownloadEvent,
)
from ..core.notify import toast
from ..core.strategies import strategy_requires_ffmpeg
from .control_panel import ControlPanel
from .icons import get_asset_path, get_icon
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

POLL_MS_BUSY = 50
POLL_MS_IDLE = 200
POLL_MS = POLL_MS_BUSY
INSPECTOR_WIDTH = 340

__all__ = ["MainWindow", "update_title_bar_theme"]


class MainWindow(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)
        self.settings = settings
        self.controller = AppController(settings)
        self._last_output: Path | None = None
        self._watcher: FolderWatcher | None = None
        self._watch_inbox: queue.Queue[Path] = queue.Queue()
        self._watch_batch_active: bool = False
        self._forensic_win: Any = None
        self._settings_win: Any = None
        self._applied_ui_scale: int = 100
        self._theme_mgr = get_theme_manager(settings)
        self._window_has_focus: bool = True
        self._focus_debounce_timer: str | None = None
        self._is_minimized: bool = False
        self._last_window_dims: tuple[int, int] | None = None
        self._pending_minimized_logs: list[tuple[str, LogLevel | str]] = []
        self._pending_minimized_progress: ProgressEvent | None = None
        self._pending_minimized_queue_dirty: bool = False
        self._pending_minimized_info_panel_dirty: bool = False

        ctk.set_appearance_mode(settings.appearance)
        self._apply_ui_scale(settings.ui_scale)
        self.title(APP_NAME)
        self._set_app_icon()

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
        is_dark = ctk.get_appearance_mode().lower() == "dark"
        win_bg = tokens.bg[1] if is_dark else tokens.bg[0]
        apply_window_backdrop(
            self,
            glass=settings.glass,
            alpha=settings.window_alpha,
            backdrop_mode=settings.glass_mode,
            tint_strength=settings.tint_strength,
            bg_color=win_bg,
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

        # Window lifecycle & geometry guards (<Map>, <Unmap>, <Configure>)
        self.bind("<Map>", self._on_window_map, add="+")
        self.bind("<Unmap>", self._on_window_unmap, add="+")
        self.bind("<Configure>", self._on_window_configure, add="+")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._theme_mgr.subscribe(self._on_theme_updated)

        self._update_info: Any = None
        self._configure_debounce_timer: Any = None
        self._init_ffmpeg()
        self._sync_watcher()
        self._sync_explorer_menu()
        self.controller.check_for_updates_background(__version__)
        self.after(POLL_MS, self._poll)

    # ---------- window focus awareness ----------
    def _on_window_focus_in(self, event: Any) -> None:
        if self._focus_debounce_timer is not None:
            self.after_cancel(self._focus_debounce_timer)
            self._focus_debounce_timer = None
        self._update_window_focus(True)
        if hasattr(self, "after"):
            self.after(16, self._force_win32_repaint)
            self.after(80, self._force_win32_repaint)

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

    def _force_win32_repaint(self) -> None:
        """Invalidate the window and its children so Win32 repaints them from WM_PAINT."""
        if sys.platform != "win32":
            return
        # RDW_INVALIDATE (0x1) | RDW_ERASE (0x4) | RDW_ALLCHILDREN (0x80) |
        # RDW_UPDATENOW (0x100) | RDW_FRAME (0x400) = 0x0585
        flags = 0x0001 | 0x0004 | 0x0080 | 0x0100 | 0x0400
        with contextlib.suppress(Exception):
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            ctypes.windll.user32.RedrawWindow(hwnd, None, None, flags)
            ctypes.windll.user32.RedrawWindow(self.winfo_id(), None, None, flags)

    # ---------- window map / unmap & resize debouncing ----------
    @property
    def is_minimized(self) -> bool:
        try:
            return self._is_minimized or str(self.state()).lower() == "iconic"
        except Exception:
            return False

    def _on_window_unmap(self, event: Any) -> None:
        if event.widget == self:
            self._is_minimized = True

    def _on_window_map(self, event: Any) -> None:
        if event.widget == self:
            was_minimized = self._is_minimized
            self._is_minimized = False
            if was_minimized:
                self._flush_coalesced_ui_sync()
            if hasattr(self, "after"):
                self.after(16, self._force_win32_repaint)
                self.after(80, self._force_win32_repaint)

    def _on_window_configure(self, event: Any) -> None:
        if event.widget != self:
            return
        w, h = event.width, event.height
        if w <= 1 or h <= 1:
            return
        if getattr(self, "_last_window_dims", None) == (w, h):
            return
        self._last_window_dims = (w, h)
        if hasattr(self, "after") and hasattr(self, "after_cancel"):
            timer = getattr(self, "_configure_debounce_timer", None)
            if timer is not None:
                with contextlib.suppress(Exception):
                    self.after_cancel(timer)
            self._configure_debounce_timer = self.after(80, self._on_window_resized)

    def _on_window_resized(self) -> None:
        self._configure_debounce_timer = None
        if not self.is_minimized:
            self._force_win32_repaint()

    def _flush_coalesced_ui_sync(self) -> None:
        """Single coalesced repaint upon restoring from minimized/iconic state."""
        tokens = self._theme_mgr.tokens
        is_dark = ctk.get_appearance_mode().lower() == "dark"
        win_bg = tokens.bg[1] if is_dark else tokens.bg[0]
        apply_window_backdrop(
            self,
            glass=self.settings.glass,
            alpha=self.settings.window_alpha,
            backdrop_mode=self.settings.glass_mode,
            tint_strength=self.settings.tint_strength,
            bg_color=win_bg,
        )
        self._refresh_theme(tokens)

        if self._pending_minimized_logs:
            self.console.append_batch(self._pending_minimized_logs)
            self._pending_minimized_logs.clear()

        if self._pending_minimized_progress is not None:
            p = self._pending_minimized_progress
            self._pending_minimized_progress = None
            f_name = p.current_file.name if p.current_file else "File"
            f_pct = int(p.file_fraction * 100)
            ov_pct = int(p.fraction * 100)
            f_txt = f"[{p.file_index}/{p.total_files}] {f_name}: {f_pct}%"
            b_txt = f"Batch progress ({p.file_index}/{p.total_files}): {ov_pct}%"
            self.controls.set_batch_progress(p.file_fraction, p.fraction, f_txt, b_txt)

        if self._pending_minimized_queue_dirty:
            self._pending_minimized_queue_dirty = False
            self.input_list.render()

        if self._pending_minimized_info_panel_dirty:
            self._pending_minimized_info_panel_dirty = False
            self._sync_info_panel()

        self._refresh_state()
        self._force_win32_repaint()

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

    def _set_app_icon(self) -> None:
        """Apply app icon to window title bar and Windows taskbar."""
        if sys.platform == "win32":
            with contextlib.suppress(AttributeError, OSError):
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)

        ico_path = get_asset_path("app.ico")
        if ico_path.is_file():
            with contextlib.suppress(Exception):
                self.iconbitmap(str(ico_path))

        png_path = get_asset_path("app_icon.png")
        if png_path.is_file():
            with contextlib.suppress(Exception), Image.open(png_path) as im:
                self._app_icon_photo: Any = ImageTk.PhotoImage(im.resize((64, 64)))
                self.iconphoto(False, self._app_icon_photo)

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

        self.btn_update = ctk.CTkButton(
            brand_frame,
            text="",
            height=22,
            font=font_badge(fsize),
            fg_color=tokens.accent,
            hover_color=tokens.accent_hover,
            text_color="#FFFFFF",
            corner_radius=6,
            command=self._on_update_clicked,
        )

        # Right toolbar items
        right_frame = ctk.CTkFrame(self.header_bar, fg_color="transparent")
        right_frame.grid(row=0, column=2, sticky="e", padx=(0, 14), pady=8)

        # 1. FFmpeg status pill (click/right-click to pick folder; checking / ready / not found)
        self._ff_state = "checking"
        self._ff_download_text = ""
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
            command=self._on_ff_badge_click,
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
        self.settings.save_async()

    def _set_appearance_mode(self, mode: str) -> None:
        self.settings.appearance = mode
        self._theme_mgr.apply(self.settings)
        self.settings.save_async()

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

    def _on_ff_badge_click(self) -> None:
        if self._ff_state == "downloading":
            return
        if self._ff_state == "not_found":
            self.controller.start_ffmpeg_download()
            return
        self._pick_ffmpeg()

    def _show_ffmpeg_menu(self, event: Any) -> None:
        from tkinter import Menu

        lang = self.settings.language
        menu = Menu(self, tearoff=0)
        menu.add_command(
            label=t("ffmpeg_download_btn", lang),
            command=self.controller.start_ffmpeg_download,
        )
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
                text=f"{t('ffmpeg_not_found', lang)} · {t('ffmpeg_download_btn', lang)}",
                fg_color=STATUS_DANGER_BG,
                hover_color=tokens.surface_hover,
                text_color=STATUS_DANGER_TEXT,
                font=font_badge(fsize),
            )
        elif self._ff_state == "downloading":
            self.ff_badge.configure(
                text=self._ff_download_text or t("ffmpeg_downloading", lang, percent=0),
                fg_color=STATUS_MUTED_BG,
                hover_color=tokens.surface_hover,
                text_color=STATUS_MUTED_TEXT,
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
        is_dark = ctk.get_appearance_mode().lower() == "dark"
        win_bg = tokens.bg[1] if is_dark else tokens.bg[0]
        apply_window_backdrop(
            self,
            glass=self.settings.glass,
            alpha=self.settings.window_alpha,
            backdrop_mode=self.settings.glass_mode,
            tint_strength=self.settings.tint_strength,
            bg_color=win_bg,
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

        tokens = self._theme_mgr.tokens
        is_dark = ctk.get_appearance_mode().lower() == "dark"
        win_bg = tokens.bg[1] if is_dark else tokens.bg[0]
        self._refresh_theme()
        apply_window_backdrop(
            self,
            glass=settings.glass,
            alpha=settings.window_alpha,
            backdrop_mode=settings.glass_mode,
            tint_strength=settings.tint_strength,
            bg_color=win_bg,
        )
        self._init_ffmpeg()
        self._sync_watcher()
        self._sync_explorer_menu()

    def _sync_watcher(self) -> None:
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None
        if not self.settings.watch_folder_enabled:
            return
        folder = Path(self.settings.watch_folder) if self.settings.watch_folder else None
        if folder is None or not folder.is_dir():
            self.console.append("Watch folder is not configured or missing.", "WARN")
            return
        self._watcher = FolderWatcher(folder, self._watch_inbox.put)
        self._watcher.start()
        self.console.append(f"Watching folder: {folder}", "INFO")

    def _sync_explorer_menu(self) -> None:
        try:
            if self.settings.explorer_menu:
                shell_integration.install()
            else:
                shell_integration.uninstall()
        except Exception as exc:
            self.console.append(f"Explorer context menu update failed: {exc}", "ERROR")

    def _drain_watch_inbox(self) -> None:
        """Queue completed exports and patch only those paths, never the selection."""
        if self.controller.busy or self._watch_inbox.empty():
            return
        paths: list[Path] = []
        while True:
            try:
                paths.append(self._watch_inbox.get_nowait())
            except queue.Empty:
                break
        if not paths:
            return
        self.controller.add_files(paths, select=False)
        self.input_list.render()
        self.console.append(f"Watch folder: patching {len(paths)} file(s)", "INFO")
        self._watch_batch_active = True
        self.controller.start_patch(
            QUICK_PATCH_TIMESCALE,
            self.settings.strategy,
            only_selected=False,
            only_paths=paths,
        )
        if not self.controller.busy:
            self._watch_batch_active = False

    def _notify_watch_done(self, message: str) -> None:
        threading.Thread(target=toast, args=(message,), daemon=True).start()

    def _open_forensic(self) -> None:
        from .forensic_window import ForensicWindow

        if self._forensic_win is None or not self._forensic_win.winfo_exists():
            self._forensic_win = ForensicWindow(self)
        else:
            self._forensic_win.focus()

    # ---------- ffmpeg ----------
    def _init_ffmpeg(self) -> None:
        if self._ff_state == "downloading":
            return
        self._ff_state = "checking"
        self._ff_download_text = ""
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
        if item_path is None:
            timer = getattr(self, "_sync_info_timer", None)
            if timer is not None and hasattr(self, "after_cancel"):
                with contextlib.suppress(Exception):
                    self.after_cancel(timer)
                self._sync_info_timer = None
            self._sync_info_panel(None)
            return

        if hasattr(self, "after") and hasattr(self, "after_cancel"):
            timer = getattr(self, "_sync_info_timer", None)
            if timer is not None:
                with contextlib.suppress(Exception):
                    self.after_cancel(timer)
            self._sync_info_timer = self.after(35, lambda: self._sync_info_panel(item_path))
        else:
            self._sync_info_panel(item_path)

    def _sync_info_panel(self, focus_path: Path | None = None) -> None:
        self._sync_info_timer = None
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
            if not self.is_minimized:
                self.controls.set_state(
                    can_patch=can_patch,
                    busy=busy,
                )
                self.input_list.set_state(busy=busy)

    # ---------- event loop ----------
    def _poll(self) -> None:
        has_events = False
        try:
            self._drain_watch_inbox()
            events: list[Event] = []
            self.controller.drain(events.append)
            if events:
                has_events = True
                self._handle_batch(events)
            if not self.is_minimized:
                self._refresh_state()
        except Exception:
            log.exception("Unhandled error in UI poll loop")
        finally:
            is_busy = (
                self.controller.busy
                or has_events
                or getattr(self, "_ff_state", "") == "downloading"
            )
            interval = POLL_MS_BUSY if is_busy else POLL_MS_IDLE
            self.after(interval, self._poll)

    def _handle(self, event: Event) -> None:
        self._handle_batch([event])

    def _handle_batch(self, events: list[Event]) -> None:
        log_entries: list[tuple[str, LogLevel | str]] = []
        latest_progress: ProgressEvent | None = None
        queue_dirty = False
        info_panel_dirty = False

        for event in events:
            if isinstance(event, LogEvent):
                log_entries.append((event.message, event.level))
            elif isinstance(event, ProgressEvent):
                latest_progress = event
            elif isinstance(event, QueueChangedEvent):
                queue_dirty = True
                info_panel_dirty = True
            elif isinstance(event, FFmpegDownloadEvent):
                self._handle_ffmpeg_event(event)
            elif isinstance(event, UpdateAvailableEvent):
                self._update_info = event.info
                self._show_update_button(event.info)
            elif isinstance(event, UpdateDownloadEvent):
                self._handle_update_download_event(event)
            elif isinstance(event, ProbeDoneEvent):
                queue_dirty = True
                info_panel_dirty = True
                if self.controller.queue:
                    self.console.set_context_files(target=self.controller.queue[-1])
                if event.info:
                    if event.queue_count > 1:
                        msg = (
                            f"Batch queued ({event.queue_count} files). "
                            f"1st clip: {event.info.fps:.3f} FPS"
                        )
                        log_entries.append((msg, "OK"))
                    else:
                        log_entries.append((f"Detected {event.info.fps:.3f} FPS", "OK"))
                elif event.error:
                    log_entries.append((f"Probe failed: {event.error}", "ERROR"))
            elif isinstance(event, PatchDoneEvent):
                queue_dirty = True
                info_panel_dirty = True
                if self._watch_batch_active:
                    self._watch_batch_active = False
                    if event.cancelled:
                        self._notify_watch_done("Watch folder: patch cancelled")
                    elif event.failed:
                        self._notify_watch_done(
                            f"Watch folder: {len(event.failed)} file(s) failed"
                        )
                    else:
                        self._notify_watch_done(
                            f"Watch folder: {len(event.batch_results)} file(s) patched"
                        )
                if event.cancelled:
                    self.controls.set_batch_progress(0, 0, "Cancelled", "Batch cancelled")
                    log_entries.append((f"Operation cancelled: {event.error}", "WARN"))
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
                    done_msg = (
                        f"Batch finished: {done_count}/{event.total_files} files patched{suffix}."
                    )
                    log_entries.append((done_msg, "WARN" if n_exp else "OK"))
                    self._refresh_state()
                    # Batch summary dialog at end
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
                    log_entries.append((f"Patch failed: {event.error}", "ERROR"))
                    for line in event.stderr_tail:
                        log_entries.append((line, "WARN"))
                    self._refresh_state()

        if self.is_minimized:
            if log_entries:
                self._pending_minimized_logs.extend(log_entries)
            if latest_progress is not None:
                self._pending_minimized_progress = latest_progress
            if queue_dirty:
                self._pending_minimized_queue_dirty = True
            if info_panel_dirty:
                self._pending_minimized_info_panel_dirty = True
            return

        if log_entries:
            self.console.append_batch(log_entries)

        if latest_progress is not None:
            file_name = (
                latest_progress.current_file.name if latest_progress.current_file else "File"
            )
            file_pct = int(latest_progress.file_fraction * 100)
            overall_pct = int(latest_progress.fraction * 100)
            file_text = (
                f"[{latest_progress.file_index}/{latest_progress.total_files}] "
                f"{file_name}: {file_pct}%"
            )
            batch_text = (
                f"Batch progress ({latest_progress.file_index}/{latest_progress.total_files}): "
                f"{overall_pct}%"
            )
            self.controls.set_batch_progress(
                latest_progress.file_fraction,
                latest_progress.fraction,
                file_text,
                batch_text,
            )

        if queue_dirty:
            self.input_list.render()
        if info_panel_dirty:
            self._sync_info_panel()


    def _show_update_button(self, info: Any) -> None:
        if not hasattr(self, "btn_update"):
            return
        lang = self.settings.language
        text = t("update_available_btn", lang, version=getattr(info, "version", ""))
        self.btn_update.configure(text=text, state="normal")
        if not getattr(self.btn_update, "winfo_ismapped", lambda: False)():
            self.btn_update.pack(side="left", padx=(8, 0))

    def _on_update_clicked(self) -> None:
        if not self._update_info:
            return
        lang = self.settings.language
        notes = getattr(self._update_info, "notes", "").strip()
        if len(notes) > 400:
            notes = notes[:400] + "..."
        prompt = t(
            "update_dialog_prompt",
            lang,
            version=getattr(self._update_info, "version", ""),
            notes=notes if notes else "—",
        )
        if not messagebox.askyesno(t("update_dialog_title", lang), prompt):
            return
        self.btn_update.configure(
            text=t("update_downloading", lang, percent=0),
            state="disabled",
        )
        self.controller.start_update_download(self._update_info)

    def _handle_update_download_event(self, event: UpdateDownloadEvent) -> None:
        lang = self.settings.language
        if event.stage == "downloading":
            pct = event.percent
            self.btn_update.configure(
                text=t("update_downloading", lang, percent=pct),
                state="disabled",
            )
        elif event.stage == "done":
            self.btn_update.configure(
                text=t("update_ready_launch", lang),
                state="disabled",
            )
            if event.path:
                try:
                    from ..core.updater import launch_installer

                    launch_installer(event.path)
                    self._on_close()
                except Exception as exc:
                    messagebox.showerror(
                        t("app_title", lang),
                        t("update_failed", lang, error=str(exc)),
                    )
                    self._show_update_button(self._update_info)
        elif event.stage == "error":
            err_msg = event.error or "Unknown error"
            if "SHA-256" in err_msg:
                display_msg = t("update_sha256_failed", lang)
            else:
                display_msg = t("update_failed", lang, error=err_msg)
            messagebox.showerror(t("app_title", lang), display_msg)
            self._show_update_button(self._update_info)

    def _handle_ffmpeg_event(self, event: FFmpegDownloadEvent) -> None:
        if event.stage == "downloading":
            self._ff_state = "downloading"
            self._ff_download_text = t(
                "ffmpeg_downloading", self.settings.language, percent=event.percent
            )
            self._apply_ff_badge_style(self._theme_mgr.tokens)
        elif event.stage in ("extracting", "verifying"):
            self._ff_state = "downloading"
            self._ff_download_text = t("ffmpeg_extracting", self.settings.language)
            self._apply_ff_badge_style(self._theme_mgr.tokens)
        elif event.stage == "done":
            self._ff_state = "ready"
            self._ff_download_text = ""
            self._apply_ff_badge_style(self._theme_mgr.tokens)
            self._refresh_state()
            self._probe_pending_queue_items()
            self.console.append(t("ffmpeg_installed", self.settings.language), "OK")
        elif event.stage == "error":
            self._ff_state = "not_found"
            self._ff_download_text = ""
            self._apply_ff_badge_style(self._theme_mgr.tokens)

        if self._settings_win is not None and self._settings_win.winfo_exists():
            with contextlib.suppress(Exception):
                self._settings_win.tab_ffmpeg.on_download_event(event)

    def _on_close(self) -> None:
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None
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
