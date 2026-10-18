"""Patching preset settings tab component."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from ...config import MAX_BXD_PADDING_BYTES, Settings
from ...core.strategies import UI_PRESETS, migrate_strategy_name
from ..theme import font_caption, font_section


class PatchingTab:
    def __init__(self, parent: ctk.CTkFrame, dialog: Any) -> None:
        self.dialog = dialog
        self.frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._build_ui()

    def _tr(self, key: str, **kwargs: object) -> str:
        return str(self.dialog._tr(key, **kwargs))

    def _build_ui(self) -> None:
        tokens = self.dialog._theme_mgr.tokens
        draft: Settings = self.dialog._draft

        # Default Preset dropdown
        ctk.CTkLabel(
            self.frame,
            text=self._tr("default_strategy"),
            font=font_section(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(0, 4))

        preset_labels = [s.label for s in UI_PRESETS.values()]
        self.strategy_menu = ctk.CTkOptionMenu(
            self.frame,
            values=preset_labels,
            font=font_caption(),
            fg_color=tokens.surface_raised,
            button_color=tokens.border,
            text_color=tokens.text,
        )
        resolved_key, _ = migrate_strategy_name(draft.strategy)
        current_strat = UI_PRESETS.get(resolved_key)
        self.strategy_menu.set(current_strat.label if current_strat else preset_labels[0])
        self.strategy_menu.pack(fill="x", pady=(0, 12))

        # Custom BXD Padding Bytes & Hybrid Tail Ceiling
        ctk.CTkLabel(
            self.frame,
            text=self._tr("bxd_padding_lbl"),
            font=font_caption(),
            text_color=tokens.text2,
        ).pack(anchor="w", pady=(2, 2))
        self.padding_entry = ctk.CTkEntry(
            self.frame,
            height=28,
            fg_color=tokens.surface_raised,
            border_color=tokens.border,
            text_color=tokens.text,
            font=font_caption(),
        )
        self.padding_entry.insert(0, str(draft.bxd_padding_bytes))
        self.padding_entry.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            self.frame,
            text=self._tr("bxd_tail_ms_lbl"),
            font=font_caption(),
            text_color=tokens.text2,
        ).pack(anchor="w", pady=(2, 2))
        self.tail_ms_entry = ctk.CTkEntry(
            self.frame,
            height=28,
            fg_color=tokens.surface_raised,
            border_color=tokens.border,
            text_color=tokens.text,
            font=font_caption(),
        )
        self.tail_ms_entry.insert(0, str(draft.bxd_max_tail_ms))
        self.tail_ms_entry.pack(fill="x", pady=(0, 10))

        self.mask_paths_switch = ctk.CTkSwitch(
            self.frame,
            text=self._tr("mask_paths_lbl"),
            font=font_caption(),
            text_color=tokens.text,
            progress_color=tokens.accent,
        )
        if draft.mask_diagnostic_paths:
            self.mask_paths_switch.select()
        self.mask_paths_switch.pack(anchor="w", pady=(0, 10))

        # Advanced Container Options Section
        ctk.CTkLabel(
            self.frame,
            text=self._tr("v4_options"),
            font=font_section(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(4, 4))

        self.v4_strict_switch = ctk.CTkSwitch(
            self.frame,
            text=self._tr("v4_strict"),
            font=font_caption(),
            text_color=tokens.text2,
            progress_color=tokens.accent,
        )
        if draft.v4_strict_lossless:
            self.v4_strict_switch.select()
        self.v4_strict_switch.pack(anchor="w", pady=2)

        self.v4_sync_switch = ctk.CTkSwitch(
            self.frame,
            text=self._tr("v4_sync_mvhd"),
            font=font_caption(),
            text_color=tokens.text2,
            progress_color=tokens.accent,
        )
        if draft.v4_sync_mvhd:
            self.v4_sync_switch.select()
        self.v4_sync_switch.pack(anchor="w", pady=2)

        self.v4_report_switch = ctk.CTkSwitch(
            self.frame,
            text=self._tr("v4_export_report"),
            font=font_caption(),
            text_color=tokens.text2,
            progress_color=tokens.accent,
        )
        if draft.v4_export_report:
            self.v4_report_switch.select()
        self.v4_report_switch.pack(anchor="w", pady=2)

        # Integrity & Backup
        ctk.CTkLabel(
            self.frame,
            text="Safety & Verification",
            font=font_section(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(12, 4))

        self.verify_switch = ctk.CTkSwitch(
            self.frame,
            text=self._tr("verify_after"),
            font=font_caption(),
            text_color=tokens.text,
            progress_color=tokens.accent,
        )
        if draft.verify_after:
            self.verify_switch.select()
        self.verify_switch.pack(anchor="w", pady=2)

        self.backup_switch = ctk.CTkSwitch(
            self.frame,
            text=self._tr("backup_original"),
            font=font_caption(),
            text_color=tokens.text,
            progress_color=tokens.accent,
        )
        if draft.backup_original:
            self.backup_switch.select()
        self.backup_switch.pack(anchor="w", pady=2)

        self.stop_err_switch = ctk.CTkSwitch(
            self.frame,
            text=self._tr("stop_on_error"),
            font=font_caption(),
            text_color=tokens.text,
            progress_color=tokens.accent,
        )
        if draft.stop_on_error:
            self.stop_err_switch.select()
        self.stop_err_switch.pack(anchor="w", pady=2)

    def harvest(self, draft: Settings) -> None:
        import contextlib

        label_to_strat = {s.label: s.name for s in UI_PRESETS.values()}
        draft.strategy = label_to_strat.get(self.strategy_menu.get(), draft.strategy)
        with contextlib.suppress(ValueError):
            draft.bxd_padding_bytes = max(
                0, min(MAX_BXD_PADDING_BYTES, int(self.padding_entry.get().strip()))
            )
        with contextlib.suppress(ValueError):
            draft.bxd_max_tail_ms = max(0, min(5000, int(self.tail_ms_entry.get().strip())))
        draft.mask_diagnostic_paths = bool(self.mask_paths_switch.get())
        draft.v4_strict_lossless = bool(self.v4_strict_switch.get())
        draft.v4_sync_mvhd = bool(self.v4_sync_switch.get())
        draft.v4_export_report = bool(self.v4_report_switch.get())
        draft.verify_after = bool(self.verify_switch.get())
        draft.backup_original = bool(self.backup_switch.get())
        draft.stop_on_error = bool(self.stop_err_switch.get())

