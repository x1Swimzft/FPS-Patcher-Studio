"""Settings modal dialog with modular tab components, live preview, and persistence."""

from __future__ import annotations

import contextlib
import copy
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import customtkinter as ctk

from .. import APP_NAME
from ..config import Settings
from .icons import get_icon
from .settings_tabs import (
    AboutTab,
    AppearanceTab,
    BehaviorTab,
    ConsoleTab,
    FFmpegTab,
    OutputTab,
    PatchingTab,
)
from .strings import t
from .theme import (
    RADIUS_CARD,
    RADIUS_CONTROL,
    ThemeTokens,
    apply_window_backdrop,
    font_body,
    font_caption,
    font_title,
    get_theme_manager,
)


class SettingsWindow(ctk.CTkToplevel):
    def __init__(
        self,
        master: Any,
        settings: Settings,
        on_applied: Callable[[Settings], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.settings = settings
        # Working copy to allow Apply / Cancel
        self._draft = copy.deepcopy(settings)
        self._on_applied = on_applied
        self._theme_mgr = get_theme_manager(settings)

        self.title(f"{t('settings_btn', settings.language)} — {APP_NAME}")
        self.geometry("740x580")
        self.minsize(700, 520)
        self.resizable(True, True)

        # Modal setup
        self.transient(master)
        self.grab_set()

        # Backdrop styling
        apply_window_backdrop(
            self,
            glass=self._draft.glass,
            alpha=self._draft.window_alpha,
            backdrop_mode=self._draft.glass_mode,
            tint_strength=self._draft.tint_strength,
        )

        # Tab mapping
        self._tabs = [
            ("appearance", "tab_appearance", "🎨"),
            ("output", "tab_output", "📁"),
            ("patching", "tab_patching", ""),
            ("ffmpeg", "tab_ffmpeg", "🎬"),
            ("console", "tab_console", "📟"),
            ("behavior", "tab_behavior", "⚙"),
            ("about", "tab_about", "ℹ"),
        ]
        self._active_tab = "appearance"
        self._tab_buttons: dict[str, ctk.CTkButton] = {}
        self._tab_frames: dict[str, ctk.CTkFrame] = {}

        self._build_ui()
        self._theme_mgr.subscribe(self._on_theme_updated)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _tr(self, key: str, **kwargs: object) -> str:
        return t(key, self._draft.language, **kwargs)

    def _build_ui(self) -> None:
        tokens = self._theme_mgr.tokens
        self.configure(fg_color=tokens.bg)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left Sidebar (Navigation)
        self.sidebar = ctk.CTkFrame(
            self,
            width=180,
            corner_radius=RADIUS_CARD,
            fg_color=tokens.surface,
            border_width=1,
            border_color=tokens.border,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=(14, 6), pady=(14, 10))
        self.sidebar.grid_propagate(False)

        # Sidebar Title
        ctk.CTkLabel(
            self.sidebar,
            text=self._tr("settings_btn"),
            font=font_title(),
            text_color=tokens.text,
        ).pack(anchor="w", padx=16, pady=(16, 12))

        # Nav Buttons
        zap_ico = get_icon("zap", (15, 15))
        for key, str_key, icon in self._tabs:
            tab_ico = zap_ico if key == "patching" else None
            txt = self._tr(str_key)
            label_text = f"  {txt}" if tab_ico else (f"{icon}  {txt}" if icon else txt)
            btn = ctk.CTkButton(
                self.sidebar,
                text=label_text,
                image=tab_ico,
                compound="left",
                anchor="w",
                height=34,
                corner_radius=RADIUS_CONTROL,
                font=font_body(),
                fg_color="transparent",
                hover_color=tokens.surface_raised,
                text_color=tokens.text2,
                command=lambda k=key: self._switch_tab(k),
            )
            btn.pack(fill="x", padx=10, pady=2)
            self._tab_buttons[key] = btn

        # Right Content Container
        self.content_container = ctk.CTkFrame(
            self,
            corner_radius=RADIUS_CARD,
            fg_color=tokens.surface,
            border_width=1,
            border_color=tokens.border,
        )
        self.content_container.grid(row=0, column=1, sticky="nsew", padx=(6, 14), pady=(14, 10))
        self.content_container.grid_columnconfigure(0, weight=1)
        self.content_container.grid_rowconfigure(0, weight=1)

        # Bottom Buttons Bar
        bottom_bar = ctk.CTkFrame(self, fg_color="transparent", height=44)
        bottom_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 12))
        bottom_bar.grid_columnconfigure(1, weight=1)

        self.btn_reset_all = ctk.CTkButton(
            bottom_bar,
            text=self._tr("reset_defaults"),
            height=34,
            corner_radius=RADIUS_CONTROL,
            font=font_caption(),
            fg_color="transparent",
            hover_color=tokens.surface_raised,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.muted,
            command=self._reset_to_defaults,
        )
        self.btn_reset_all.grid(row=0, column=0, sticky="w")

        right_actions = ctk.CTkFrame(bottom_bar, fg_color="transparent")
        right_actions.grid(row=0, column=2, sticky="e")

        self.btn_apply = ctk.CTkButton(
            right_actions,
            text=self._tr("apply"),
            width=80,
            height=34,
            corner_radius=RADIUS_CONTROL,
            font=font_body(),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.text,
            command=self._on_apply,
        )
        self.btn_apply.pack(side="left", padx=4)

        self.btn_ok = ctk.CTkButton(
            right_actions,
            text=self._tr("ok"),
            width=80,
            height=34,
            corner_radius=RADIUS_CONTROL,
            font=font_body(bold=True),
            fg_color=tokens.accent,
            hover_color=tokens.accent_hover,
            text_color="#FFFFFF",
            command=self._on_ok,
        )
        self.btn_ok.pack(side="left", padx=4)

        self.btn_cancel = ctk.CTkButton(
            right_actions,
            text=self._tr("cancel"),
            width=80,
            height=34,
            corner_radius=RADIUS_CONTROL,
            font=font_body(),
            fg_color="transparent",
            hover_color=tokens.surface_raised,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.text2,
            command=self._on_cancel,
        )
        self.btn_cancel.pack(side="left", padx=4)

        # Build each tab frame via sub-components
        self.tab_appearance = AppearanceTab(self.content_container, self)
        self.tab_output = OutputTab(self.content_container, self)
        self.tab_patching = PatchingTab(self.content_container, self)
        self.tab_ffmpeg = FFmpegTab(self.content_container, self)
        self.tab_console = ConsoleTab(self.content_container, self)
        self.tab_behavior = BehaviorTab(self.content_container, self)
        self.tab_about = AboutTab(self.content_container, self)

        self._tab_frames["appearance"] = self.tab_appearance.frame
        self._tab_frames["output"] = self.tab_output.frame
        self._tab_frames["patching"] = self.tab_patching.frame
        self._tab_frames["ffmpeg"] = self.tab_ffmpeg.frame
        self._tab_frames["console"] = self.tab_console.frame
        self._tab_frames["behavior"] = self.tab_behavior.frame
        self._tab_frames["about"] = self.tab_about.frame

        self._switch_tab(self._active_tab)

    def _switch_tab(self, key: str) -> None:
        self._active_tab = key
        tokens = self._theme_mgr.tokens
        for k, btn in self._tab_buttons.items():
            if k == key:
                btn.configure(
                    fg_color=tokens.surface_raised,
                    text_color=tokens.accent,
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=tokens.text2,
                )

        for k, frm in self._tab_frames.items():
            if k == key:
                frm.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
            else:
                frm.grid_forget()

    def _reset_to_defaults(self) -> None:
        from tkinter import messagebox

        if messagebox.askyesno("Reset", self._tr("reset_confirm"), parent=self):
            self._draft = Settings()
            self._theme_mgr.apply(self._draft)
            self._on_apply()

    def _harvest_draft_values(self) -> None:
        self.tab_appearance.harvest(self._draft)
        self.tab_output.harvest(self._draft)
        self.tab_patching.harvest(self._draft)
        self.tab_ffmpeg.harvest(self._draft)
        self.tab_console.harvest(self._draft)
        self.tab_behavior.harvest(self._draft)
        self.tab_about.harvest(self._draft)

    def _on_apply(self) -> None:
        self._harvest_draft_values()
        for k, v in asdict(self._draft).items():
            setattr(self.settings, k, v)
        self.settings.save()
        self._theme_mgr.apply(self.settings)

        apply_window_backdrop(
            self,
            glass=self.settings.glass,
            alpha=self.settings.window_alpha,
            backdrop_mode=self.settings.glass_mode,
            tint_strength=self.settings.tint_strength,
        )

        if self._on_applied:
            self._on_applied(self.settings)

    def _on_ok(self) -> None:
        self._on_apply()
        self._on_cancel()

    def _on_cancel(self) -> None:
        self._theme_mgr.unsubscribe(self._on_theme_updated)
        self._theme_mgr.apply(self.settings)
        self.grab_release()
        self.destroy()

    def _on_theme_updated(self, tokens: ThemeTokens) -> None:
        with contextlib.suppress(Exception):
            self.configure(fg_color=tokens.bg)
            self.sidebar.configure(fg_color=tokens.surface, border_color=tokens.border)
            self.content_container.configure(fg_color=tokens.surface, border_color=tokens.border)
            self.btn_ok.configure(fg_color=tokens.accent, hover_color=tokens.accent_hover)
            self._switch_tab(self._active_tab)
