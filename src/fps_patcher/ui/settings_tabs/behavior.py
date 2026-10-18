"""Behavior settings tab component."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from ...config import NOTIFY_MODES, Settings
from ..theme import font_caption, font_section


class BehaviorTab:
    def __init__(self, parent: ctk.CTkFrame, dialog: Any) -> None:
        self.dialog = dialog
        self.frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._build_ui()

    def _tr(self, key: str, **kwargs: object) -> str:
        return str(self.dialog._tr(key, **kwargs))

    def _build_ui(self) -> None:
        tokens = self.dialog._theme_mgr.tokens
        draft: Settings = self.dialog._draft

        # Switches
        self.remember_geo_switch = ctk.CTkSwitch(
            self.frame,
            text=self._tr("remember_geometry"),
            font=font_caption(),
            text_color=tokens.text,
            progress_color=tokens.accent,
        )
        if draft.remember_geometry:
            self.remember_geo_switch.select()
        self.remember_geo_switch.pack(anchor="w", pady=4)

        self.ontop_switch = ctk.CTkSwitch(
            self.frame,
            text=self._tr("always_on_top"),
            font=font_caption(),
            text_color=tokens.text,
            progress_color=tokens.accent,
        )
        if draft.always_on_top:
            self.ontop_switch.select()
        self.ontop_switch.pack(anchor="w", pady=4)

        self.confirm_cancel_switch = ctk.CTkSwitch(
            self.frame,
            text=self._tr("confirm_cancel"),
            font=font_caption(),
            text_color=tokens.text,
            progress_color=tokens.accent,
        )
        if draft.confirm_cancel:
            self.confirm_cancel_switch.select()
        self.confirm_cancel_switch.pack(anchor="w", pady=4)

        self.confirm_overwrite_switch = ctk.CTkSwitch(
            self.frame,
            text=self._tr("confirm_overwrite"),
            font=font_caption(),
            text_color=tokens.text,
            progress_color=tokens.accent,
        )
        if draft.confirm_overwrite:
            self.confirm_overwrite_switch.select()
        self.confirm_overwrite_switch.pack(anchor="w", pady=4)

        # Notification mode
        ctk.CTkLabel(
            self.frame,
            text=self._tr("notify_done"),
            font=font_section(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(12, 4))

        self.notify_menu = ctk.CTkSegmentedButton(
            self.frame,
            values=NOTIFY_MODES,
            selected_color=tokens.accent,
            font=font_caption(),
        )
        self.notify_menu.set(draft.notify_done)
        self.notify_menu.pack(fill="x", pady=(0, 12))

        # Language selection
        ctk.CTkLabel(
            self.frame,
            text=self._tr("language_choice"),
            font=font_section(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(4, 4))

        lang_labels = ["English (en)", "ไทย (th)"]
        self.lang_menu = ctk.CTkOptionMenu(
            self.frame,
            values=lang_labels,
            font=font_caption(),
            fg_color=tokens.surface_raised,
            button_color=tokens.border,
            text_color=tokens.text,
            command=self._on_lang_changed,
        )
        current_idx = 1 if draft.language == "th" else 0
        self.lang_menu.set(lang_labels[current_idx])
        self.lang_menu.pack(fill="x", pady=(0, 8))

    def _on_lang_changed(self, val: str) -> None:
        self.dialog._draft.language = "th" if "th" in val else "en"

    def harvest(self, draft: Settings) -> None:
        draft.remember_geometry = bool(self.remember_geo_switch.get())
        draft.always_on_top = bool(self.ontop_switch.get())
        draft.confirm_cancel = bool(self.confirm_cancel_switch.get())
        draft.confirm_overwrite = bool(self.confirm_overwrite_switch.get())
        draft.notify_done = self.notify_menu.get()
