"""Appearance tab component for settings modal."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from ...config import BACKDROP_MODES, RADIUS_STYLES, THEME_PRESETS, Settings
from ..option_menu import MacOptionMenu
from ..theme import (
    MacSwitch,
    attach_focus_ring,
    font_caption,
    font_mono,
    font_section,
)

SWATCHES = ["#3B82F6", "#8B5CF6", "#10B981", "#F43F5E", "#F59E0B", "#06B6D4", "#EC4899"]


class AppearanceTab:
    def __init__(self, parent: ctk.CTkFrame, dialog: Any) -> None:
        self.dialog = dialog
        self.frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._build_ui()

    def _tr(self, key: str, **kwargs: object) -> str:
        return str(self.dialog._tr(key, **kwargs))

    def _build_ui(self) -> None:
        tokens = self.dialog._theme_mgr.tokens
        draft: Settings = self.dialog._draft

        # Section: Theme Presets
        ctk.CTkLabel(
            self.frame,
            text=self._tr("theme_preset"),
            font=font_section(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(0, 4))

        self.preset_menu = MacOptionMenu(
            self.frame,
            values=THEME_PRESETS,
            command=self._on_preset_selected,
            font=font_caption(),
            fg_color=tokens.surface_raised,
            button_color=tokens.surface_raised,
            button_hover_color=tokens.surface_hover,
            border_color=tokens.border,
            border_width=1,
            text_color=tokens.text,
            dropdown_fg_color=tokens.surface,
            dropdown_hover_color=tokens.surface_hover,
            dropdown_text_color=tokens.text,
            corner_radius=8,
        )
        self.preset_menu.set(draft.theme_preset)
        self.preset_menu.pack(fill="x", pady=(0, 12))
        self.appearance_menu = self.preset_menu

        # Section: Custom Accent Color
        ctk.CTkLabel(
            self.frame,
            text=self._tr("custom_accent"),
            font=font_section(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(0, 4))

        accent_row = ctk.CTkFrame(self.frame, fg_color="transparent")
        accent_row.pack(fill="x", pady=(0, 6))

        self.accent_entry = ctk.CTkEntry(
            accent_row,
            placeholder_text="#3B82F6",
            font=font_mono(),
            fg_color=tokens.surface_raised,
            border_color=tokens.border,
            border_width=1,
            text_color=tokens.text,
        )
        self.accent_entry.insert(0, draft.custom_accent)
        self.accent_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        attach_focus_ring(self.accent_entry)

        # Swatches
        for sw in SWATCHES:
            btn = ctk.CTkButton(
                accent_row,
                text="",
                width=24,
                height=24,
                corner_radius=12,
                fg_color=sw,
                hover_color=sw,
                command=lambda s=sw: self._select_swatch(s),
            )
            btn.pack(side="left", padx=2)

        # Section: Backdrop Mode & Glass
        self.glass_switch = MacSwitch(
            self.frame,
            text=self._tr("glass_effect"),
            font=font_caption(),
            text_color=tokens.text,
        )
        if draft.glass:
            self.glass_switch.select()
        self.glass_switch.pack(anchor="w", pady=(8, 4))

        # Backdrop mode dropdown
        bd_row = ctk.CTkFrame(self.frame, fg_color="transparent")
        bd_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            bd_row,
            text=self._tr("glass_mode"),
            font=font_caption(),
            text_color=tokens.text2,
        ).pack(side="left", padx=(0, 12))
        self.glass_mode_menu = MacOptionMenu(
            bd_row,
            values=BACKDROP_MODES,
            font=font_caption(),
            fg_color=tokens.surface_raised,
            button_color=tokens.surface_raised,
            button_hover_color=tokens.surface_hover,
            border_color=tokens.border,
            border_width=1,
            text_color=tokens.text,
            dropdown_fg_color=tokens.surface,
            dropdown_hover_color=tokens.surface_hover,
            dropdown_text_color=tokens.text,
            corner_radius=8,
        )
        self.glass_mode_menu.set(draft.glass_mode)
        self.glass_mode_menu.pack(side="right")
        self.backdrop_menu = self.glass_mode_menu

        # Sliders: Tint Strength
        ctk.CTkLabel(
            self.frame,
            text=self._tr("tint_strength"),
            font=font_caption(),
            text_color=tokens.text2,
        ).pack(anchor="w", pady=(4, 2))
        self.tint_slider = ctk.CTkSlider(
            self.frame,
            from_=0,
            to=100,
            number_of_steps=100,
            progress_color=tokens.accent,
        )
        self.tint_slider.set(draft.tint_strength)
        self.tint_slider.pack(fill="x", pady=(0, 8))

        # Sliders: Window Alpha
        ctk.CTkLabel(
            self.frame,
            text=self._tr("window_alpha"),
            font=font_caption(),
            text_color=tokens.text2,
        ).pack(anchor="w", pady=(4, 2))
        self.alpha_slider = ctk.CTkSlider(
            self.frame,
            from_=85,
            to=100,
            number_of_steps=15,
            progress_color=tokens.accent,
        )
        self.alpha_slider.set(int(draft.window_alpha * 100))
        self.alpha_slider.pack(fill="x", pady=(0, 8))

        # Corner Roundness
        rad_row = ctk.CTkFrame(self.frame, fg_color="transparent")
        rad_row.pack(fill="x", pady=(4, 8))
        ctk.CTkLabel(
            rad_row,
            text=self._tr("radius_style"),
            font=font_caption(),
            text_color=tokens.text2,
        ).pack(side="left", padx=(0, 12))
        self.radius_menu = ctk.CTkSegmentedButton(
            rad_row,
            values=RADIUS_STYLES,
            selected_color=tokens.accent,
            font=font_caption(),
        )
        self.radius_menu.set(draft.radius_style)
        self.radius_menu.pack(side="right")

        # Reduce motion switch
        self.motion_switch = MacSwitch(
            self.frame,
            text=self._tr("reduce_motion"),
            font=font_caption(),
            text_color=tokens.text2,
        )
        if draft.reduce_motion:
            self.motion_switch.select()
        self.motion_switch.pack(anchor="w", pady=(4, 8))

    def _select_swatch(self, color: str) -> None:
        self.accent_entry.delete(0, "end")
        self.accent_entry.insert(0, color)
        self.dialog._draft.custom_accent = color
        self.dialog._theme_mgr.apply(self.dialog._draft)

    def _on_preset_selected(self, val: str) -> None:
        self.dialog._draft.theme_preset = val
        self.dialog._draft.custom_accent = ""
        self.accent_entry.delete(0, "end")
        self.dialog._theme_mgr.apply(self.dialog._draft)

    def harvest(self, draft: Settings) -> None:
        draft.theme_preset = self.preset_menu.get()
        draft.custom_accent = self.accent_entry.get().strip()
        draft.glass = bool(self.glass_switch.get())
        draft.glass_mode = self.glass_mode_menu.get()
        draft.tint_strength = int(self.tint_slider.get())
        draft.window_alpha = round(self.alpha_slider.get() / 100.0, 2)
        draft.radius_style = self.radius_menu.get()
        draft.reduce_motion = bool(self.motion_switch.get())
