"""Patching preset settings tab component."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from ...config import MAX_BXD_PADDING_BYTES, Settings
from ...core.strategies import UI_PRESETS, migrate_strategy_name
from ..option_menu import MacOptionMenu
from ..theme import (
    MacSwitch,
    attach_focus_ring,
    font_caption,
    font_section,
)


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
        self.strategy_menu = MacOptionMenu(
            self.frame,
            values=preset_labels,
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
        resolved_key, _ = migrate_strategy_name(draft.strategy)
        current_strat = UI_PRESETS.get(resolved_key)
        self.strategy_menu.set(current_strat.label if current_strat else preset_labels[0])
        self.strategy_menu.pack(fill="x", pady=(0, 12))

        # Custom X1T Padding Bytes & Hybrid Tail Ceiling
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
            border_width=1,
            text_color=tokens.text,
            font=font_caption(),
        )
        self.padding_entry.insert(0, str(draft.bxd_padding_bytes))
        self.padding_entry.pack(fill="x", pady=(0, 8))
        attach_focus_ring(self.padding_entry)

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
            border_width=1,
            text_color=tokens.text,
            font=font_caption(),
        )
        self.tail_ms_entry.insert(0, str(draft.bxd_max_tail_ms))
        self.tail_ms_entry.pack(fill="x", pady=(0, 10))
        attach_focus_ring(self.tail_ms_entry)

        self.mask_paths_switch = MacSwitch(
            self.frame,
            text=self._tr("mask_paths_lbl"),
            font=font_caption(),
            text_color=tokens.text,
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

        self.v4_strict_switch = MacSwitch(
            self.frame,
            text=self._tr("v4_strict"),
            font=font_caption(),
            text_color=tokens.text2,
        )
        if draft.v4_strict_lossless:
            self.v4_strict_switch.select()
        self.v4_strict_switch.pack(anchor="w", pady=2)

        self.v4_sync_switch = MacSwitch(
            self.frame,
            text=self._tr("v4_sync_mvhd"),
            font=font_caption(),
            text_color=tokens.text2,
        )
        if draft.v4_sync_mvhd:
            self.v4_sync_switch.select()
        self.v4_sync_switch.pack(anchor="w", pady=2)

        self.v4_report_switch = MacSwitch(
            self.frame,
            text=self._tr("v4_export_report"),
            font=font_caption(),
            text_color=tokens.text2,
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

        self.verify_switch = MacSwitch(
            self.frame,
            text=self._tr("verify_after"),
            font=font_caption(),
            text_color=tokens.text,
        )
        if draft.verify_after:
            self.verify_switch.select()
        self.verify_switch.pack(anchor="w", pady=2)

        self.backup_switch = MacSwitch(
            self.frame,
            text=self._tr("backup_original"),
            font=font_caption(),
            text_color=tokens.text,
        )
        if draft.backup_original:
            self.backup_switch.select()
        self.backup_switch.pack(anchor="w", pady=2)

        self.stop_err_switch = MacSwitch(
            self.frame,
            text=self._tr("stop_on_error"),
            font=font_caption(),
            text_color=tokens.text,
        )
        if draft.stop_on_error:
            self.stop_err_switch.select()
        self.stop_err_switch.pack(anchor="w", pady=2)

        ctk.CTkLabel(
            self.frame,
            text=self._tr("preflight_section"),
            font=font_section(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(12, 4))

        self.norm_audio_switch = MacSwitch(
            self.frame,
            text=self._tr("auto_normalize_audio"),
            font=font_caption(),
            text_color=tokens.text,
        )
        if draft.auto_normalize_audio:
            self.norm_audio_switch.select()
        self.norm_audio_switch.pack(anchor="w", pady=2)

        self.cap_bitrate_switch = MacSwitch(
            self.frame,
            text=self._tr("auto_cap_bitrate"),
            font=font_caption(),
            text_color=tokens.text,
        )
        if draft.auto_cap_bitrate:
            self.cap_bitrate_switch.select()
        self.cap_bitrate_switch.pack(anchor="w", pady=2)

        ctk.CTkLabel(
            self.frame,
            text=self._tr("color_metadata_section"),
            font=font_section(),
            text_color=tokens.text,
        ).pack(anchor="w", pady=(12, 4))

        self.fix_color_switch = MacSwitch(
            self.frame,
            text=self._tr("fix_color_tag"),
            font=font_caption(),
            text_color=tokens.text,
        )
        if draft.fix_color_tag:
            self.fix_color_switch.select()
        self.fix_color_switch.pack(anchor="w", pady=2)

        self.scrub_meta_switch = MacSwitch(
            self.frame,
            text=self._tr("scrub_metadata"),
            font=font_caption(),
            text_color=tokens.text,
        )
        if draft.scrub_metadata:
            self.scrub_meta_switch.select()
        self.scrub_meta_switch.pack(anchor="w", pady=2)

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
        draft.auto_normalize_audio = bool(self.norm_audio_switch.get())
        draft.auto_cap_bitrate = bool(self.cap_bitrate_switch.get())
        draft.fix_color_tag = bool(self.fix_color_switch.get())
        draft.scrub_metadata = bool(self.scrub_meta_switch.get())

