"""Target selection, strategy, output folder, per-item override, PATCH / Cancel, progress."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog
from typing import Any

import customtkinter as ctk

from ..app.queue_model import QueueItem
from ..config import Settings
from ..core.models import FPS_PRESETS
from ..core.platform_profiles import PLATFORM_PROFILES, get_profile
from ..core.strategies import UI_PRESETS, migrate_strategy_name
from .icons import get_icon
from .option_menu import MacOptionMenu
from .segmented_control import MacSegmentedControl
from .strings import t
from .theme import (
    MAC_CHECKBOX_BORDER_COLOR,
    MAC_CHECKBOX_CHECKMARK_COLOR,
    MAC_CHECKBOX_FG_COLOR,
    RADIUS_PILL,
    STATUS_DANGER_BG,
    STATUS_DANGER_BORDER,
    STATUS_DANGER_TEXT,
    STATUS_WARNING_BG,
    STATUS_WARNING_BORDER,
    STATUS_WARNING_TEXT,
    MacCheckBox,
    ThemeTokens,
    attach_focus_ring,
    configure_cached,
    font_body,
    font_caption,
    font_mono,
    font_section,
    get_corner_radii,
    get_theme_manager,
)

CUSTOM = "Custom"


class ControlPanel(ctk.CTkFrame):
    def __init__(
        self,
        master: Any,
        settings: Settings,
        on_patch: Callable[[int, str], None],
        on_cancel: Callable[[], None],
        on_strategy_change: Callable[[], None] | None = None,
        on_override_change: Callable[[Path, int | None, str | None], None] | None = None,
        on_profile_change: Callable[[], None] | None = None,
        footer_master: Any = None,
    ) -> None:
        self.settings = settings
        self._theme_mgr = get_theme_manager(settings)
        tokens = self._theme_mgr.tokens
        card_rad, ctrl_rad = get_corner_radii(settings.radius_style)
        fsize = settings.font_size
        lang = settings.language

        super().__init__(
            master,
            corner_radius=card_rad,
            fg_color="transparent",
            border_width=0,
        )
        self._on_patch = on_patch
        self._on_cancel = on_cancel
        self._on_strategy_change = on_strategy_change
        self._on_override_change = on_override_change
        self._on_profile_change = on_profile_change
        self._label_to_strategy = {s.label: s.name for s in UI_PRESETS.values()}
        self._strategy_to_label = {s.name: s.label for s in UI_PRESETS.values()}
        self._can_patch = False
        self._busy = False
        self._last_pct = 0
        self._focused_item: QueueItem | None = None

        self.grid_columnconfigure(0, weight=1)

        # ── 1. Target FPS Segmented Control ──
        self.target_label = ctk.CTkLabel(
            self,
            text=t("target_fps", lang),
            font=font_section(fsize),
            text_color=tokens.text2,
            anchor="w",
        )
        self.target_label.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))

        self.fps_seg = MacSegmentedControl(
            self,
            values=[*FPS_PRESETS, CUSTOM],
            command=self._preset_changed,
            corner_radius=8,
            font=font_body(bold=True, size_opt=fsize),
            height=34,
        )
        self.fps_seg.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))
        self.preset = self.fps_seg

        # ── 2. 2-Column Grid: Timescale + Preset ──
        self.grid_two_col = ctk.CTkFrame(self, fg_color="transparent")
        self.grid_two_col.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 6))
        self.grid_two_col.grid_columnconfigure(0, weight=1, uniform="insp_col")
        self.grid_two_col.grid_columnconfigure(1, weight=1, uniform="insp_col")

        self.ts_label = ctk.CTkLabel(
            self.grid_two_col,
            text=t("timescale_lbl", lang),
            font=font_caption(fsize),
            text_color=tokens.text2,
            anchor="w",
        )
        self.ts_label.grid(row=0, column=0, sticky="ew", padx=(0, 5), pady=(0, 3))

        self.strat_label = ctk.CTkLabel(
            self.grid_two_col,
            text=t("strategy_lbl", lang),
            font=font_caption(fsize),
            text_color=tokens.text2,
            anchor="w",
        )
        self.strat_label.grid(row=0, column=1, sticky="ew", padx=(5, 0), pady=(0, 3))

        self.timescale = ctk.CTkEntry(
            self.grid_two_col,
            height=32,
            corner_radius=ctrl_rad,
            fg_color=tokens.surface,
            border_color=tokens.border,
            border_width=1,
            text_color=tokens.text,
            font=font_mono(),
        )
        self.timescale.grid(row=1, column=0, sticky="ew", padx=(0, 5))
        attach_focus_ring(self.timescale)

        labels = list(self._label_to_strategy)
        self.strategy = MacOptionMenu(
            self.grid_two_col,
            height=32,
            corner_radius=8,
            border_width=1,
            border_color=tokens.border,
            values=labels,
            command=self._strategy_selected,
            fg_color=tokens.surface_raised,
            button_color=tokens.surface_raised,
            button_hover_color=tokens.surface_hover,
            text_color=tokens.text,
            dropdown_fg_color=tokens.surface,
            dropdown_hover_color=tokens.surface_hover,
            dropdown_text_color=tokens.text,
            font=font_caption(fsize),
            dynamic_resizing=False,
        )
        resolved_key, _ = migrate_strategy_name(settings.strategy)
        current = UI_PRESETS.get(resolved_key)
        self.strategy.set(current.label if current else labels[0])
        self.strategy.grid(row=1, column=1, sticky="ew", padx=(5, 0))
        self.strategy_menu = self.strategy

        # -- Platform profile / readiness selector --
        self.profile_label = ctk.CTkLabel(
            self.grid_two_col,
            text=t("platform_profile_lbl", lang),
            font=font_caption(fsize),
            text_color=tokens.text2,
            anchor="w",
        )
        self.profile_label.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 3))

        self._profile_label_to_id = {
            t(profile.label_key, lang): profile.profile_id
            for profile in PLATFORM_PROFILES.values()
        }
        self.profile = MacOptionMenu(
            self.grid_two_col,
            height=32,
            corner_radius=8,
            border_width=1,
            border_color=tokens.border,
            values=list(self._profile_label_to_id),
            command=self._profile_selected,
            fg_color=tokens.surface_raised,
            button_color=tokens.surface_raised,
            button_hover_color=tokens.surface_hover,
            text_color=tokens.text,
            dropdown_fg_color=tokens.surface,
            dropdown_hover_color=tokens.surface_hover,
            dropdown_text_color=tokens.text,
            font=font_caption(fsize),
            dynamic_resizing=False,
        )
        self.profile.set(t(get_profile(settings.platform_profile).label_key, lang))
        self.profile.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.profile_menu = self.profile

        self.profile_disclaimer = ctk.CTkLabel(
            self.grid_two_col,
            text=t("readiness_disclaimer", lang),
            font=font_caption(fsize),
            text_color=tokens.muted,
            anchor="w",
            justify="left",
            wraplength=255,
        )
        self.profile_disclaimer.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(3, 0))

        # ── 2b. Amber Warning Callout (shown only for "X1T For PC") ──
        self.pc_warn_frame = ctk.CTkFrame(
            self,
            corner_radius=ctrl_rad,
            fg_color=STATUS_WARNING_BG,
            border_width=1,
            border_color=STATUS_WARNING_BORDER,
        )
        self.pc_warn_frame.grid_columnconfigure(0, weight=1)
        self.pc_warn_label = ctk.CTkLabel(
            self.pc_warn_frame,
            text=t("bxd_pc_warn", lang),
            font=font_caption(fsize),
            fg_color="transparent",
            text_color=STATUS_WARNING_TEXT,
            wraplength=260,
            justify="left",
            anchor="w",
        )
        self.pc_warn_label.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        self._update_pc_warn_visibility(resolved_key)

        # ── 2c. Per-Item Override Section (compact 1-line when none set, expandable) ──
        self._override_expanded = False
        self.override_card = ctk.CTkFrame(
            self,
            corner_radius=ctrl_rad,
            fg_color=tokens.surface,
            border_width=1,
            border_color=tokens.border,
        )
        self.override_card.grid(row=4, column=0, sticky="ew", padx=6, pady=(2, 4))
        self.override_card.grid_columnconfigure(0, weight=1)

        override_top = ctk.CTkFrame(self.override_card, fg_color="transparent")
        override_top.grid(row=0, column=0, sticky="ew", padx=6, pady=3)
        override_top.grid_columnconfigure(1, weight=1)

        chev_right_ico = get_icon("chevron_right", (12, 12))
        self.override_toggle_btn = ctk.CTkButton(
            override_top,
            text="" if chev_right_ico else "▸",
            image=chev_right_ico,
            width=18,
            height=18,
            corner_radius=4,
            fg_color="transparent",
            hover_color=tokens.surface_hover,
            text_color=tokens.text2,
            font=font_caption(fsize),
            command=self._toggle_override_expanded,
        )
        self.override_toggle_btn.grid(row=0, column=0, padx=(0, 4))

        self.override_lbl = ctk.CTkLabel(
            override_top,
            text=t("override_section", lang),
            font=font_caption(fsize),
            text_color=tokens.text2,
            anchor="w",
            cursor="hand2",
        )
        self.override_lbl.grid(row=0, column=1, sticky="ew")
        self.override_lbl.bind("<Button-1>", lambda _e: self._toggle_override_expanded())

        self.override_summary_badge = ctk.CTkLabel(
            override_top,
            text=t("empty_val", lang),
            font=font_caption(fsize),
            text_color=tokens.muted,
            anchor="e",
            cursor="hand2",
        )
        self.override_summary_badge.grid(row=0, column=2, sticky="e", padx=(4, 2))
        self.override_summary_badge.bind("<Button-1>", lambda _e: self._toggle_override_expanded())

        self.override_body = ctk.CTkFrame(self.override_card, fg_color="transparent")
        self.override_body.grid_columnconfigure(0, weight=1)

        self.override_status_lbl = ctk.CTkLabel(
            self.override_body,
            text=t("override_status_none", lang),
            font=font_caption(fsize),
            text_color=tokens.muted,
            anchor="w",
            wraplength=255,
            justify="left",
        )
        self.override_status_lbl.grid(row=0, column=0, sticky="ew", padx=8, pady=(0, 2))

        override_btns = ctk.CTkFrame(self.override_body, fg_color="transparent")
        override_btns.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 4))

        self.btn_set_override = ctk.CTkButton(
            override_btns,
            text=t("override_apply_btn", lang),
            height=24,
            width=88,
            corner_radius=6,
            fg_color=tokens.accent_light,
            hover_color=tokens.surface_hover,
            text_color=tokens.accent,
            font=font_caption(fsize),
            command=self._apply_item_override,
            state="disabled",
        )
        self.btn_set_override.pack(side="left", padx=(0, 6))
        attach_focus_ring(self.btn_set_override)

        self.btn_clear_override = ctk.CTkButton(
            override_btns,
            text=t("override_clear_btn", lang),
            height=24,
            width=56,
            corner_radius=6,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text2,
            font=font_caption(fsize),
            command=self._clear_item_override,
            state="disabled",
        )
        self.btn_clear_override.pack(side="left")
        attach_focus_ring(self.btn_clear_override)

        # ── 3. Output Directory + Vertically Stacked Checkboxes ──
        self.output_lbl = ctk.CTkLabel(
            self,
            text=t("output_lbl", lang),
            font=font_section(fsize),
            text_color=tokens.text2,
            anchor="w",
        )
        self.output_lbl.grid(row=5, column=0, sticky="ew", padx=6, pady=(2, 2))

        out_row = ctk.CTkFrame(self, fg_color="transparent")
        out_row.grid(row=6, column=0, sticky="ew", padx=6, pady=(0, 4))
        out_row.grid_columnconfigure(0, weight=1)

        self.out_entry = ctk.CTkEntry(
            out_row,
            height=32,
            corner_radius=ctrl_rad,
            fg_color=tokens.surface,
            border_color=tokens.border,
            border_width=1,
            text_color=tokens.text,
            placeholder_text=t("same_as_source", lang),
            font=font_caption(fsize),
        )
        self.out_entry.grid(row=0, column=0, sticky="ew")
        self.out_entry.bind("<FocusOut>", self._on_out_entry_edited)
        self.out_entry.bind("<Return>", self._on_out_entry_edited)
        attach_focus_ring(self.out_entry)

        # Compatibility alias for out_label
        self.out_label = self.out_entry

        folder_ico = get_icon("folder", (15, 15))
        self.btn_pick_out = ctk.CTkButton(
            out_row,
            text="" if folder_ico else "📁",
            image=folder_ico,
            width=32,
            height=32,
            corner_radius=ctrl_rad,
            command=self._pick_out,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            border_width=1,
            border_color=tokens.border,
        )
        self.btn_pick_out.grid(row=0, column=1, padx=(5, 0))
        attach_focus_ring(self.btn_pick_out)

        self.btn_reset_out = ctk.CTkButton(
            out_row,
            text="↺",
            width=30,
            height=32,
            corner_radius=ctrl_rad,
            fg_color="transparent",
            hover_color=tokens.surface_raised,
            text_color=tokens.muted,
            border_width=1,
            border_color=tokens.border,
            command=self._reset_out,
        )
        self.btn_reset_out.grid(row=0, column=2, padx=(4, 0))
        attach_focus_ring(self.btn_reset_out)
        self._refresh_out()

        # Stack checkboxes vertically so Thai labels never clip at 340px
        opt_col = ctk.CTkFrame(self, fg_color="transparent")
        opt_col.grid(row=7, column=0, sticky="ew", padx=6, pady=(0, 4))
        opt_col.grid_columnconfigure(0, weight=1)

        self.overwrite_check = MacCheckBox(
            opt_col,
            text=t("overwrite_lbl", lang),
            font=font_caption(fsize),
            text_color=tokens.text2,
            command=self._options_changed,
        )
        self.overwrite_check.grid(row=0, column=0, sticky="w", pady=(0, 2))
        if settings.overwrite:
            self.overwrite_check.select()
        self.overwrite_cb = self.overwrite_check

        self.auto_rename_check = MacCheckBox(
            opt_col,
            text=t("auto_rename_lbl", lang),
            font=font_caption(fsize),
            text_color=tokens.text2,
            command=self._options_changed,
        )
        self.auto_rename_check.grid(row=1, column=0, sticky="w", pady=(0, 2))
        if settings.auto_rename:
            self.auto_rename_check.select()

        self.dry_run_cb = MacCheckBox(
            opt_col,
            text=t("v4_dry_run", lang),
            font=font_caption(fsize),
            text_color=tokens.text2,
            command=self._options_changed,
        )
        self.dry_run_cb.grid(row=2, column=0, sticky="w", pady=(0, 2))
        if settings.v4_dry_run:
            self.dry_run_cb.select()

        self.safe_write_cb = MacCheckBox(
            opt_col,
            text=t("backup_original", lang),
            font=font_caption(fsize),
            text_color=tokens.text2,
            command=self._options_changed,
        )
        self.safe_write_cb.grid(row=3, column=0, sticky="w", pady=(0, 2))
        if settings.backup_original:
            self.safe_write_cb.select()

        self.verify_cb = MacCheckBox(
            opt_col,
            text=t("verify_after", lang),
            font=font_caption(fsize),
            text_color=tokens.text2,
            command=self._options_changed,
        )
        self.verify_cb.grid(row=4, column=0, sticky="w")
        if settings.verify_after:
            self.verify_cb.select()

        # ── 4 & 5. Pinned Footer: Progress Bars + Start Patch / Cancel ──
        btn_parent = footer_master if footer_master is not None else self
        btns = ctk.CTkFrame(btn_parent, fg_color="transparent")
        if footer_master is not None:
            btns.pack(fill="x", padx=10, pady=(8, 10))
        else:
            btns.grid(row=8, column=0, sticky="ew", padx=6, pady=(4, 8))
        btns.grid_columnconfigure(0, weight=1)
        self._btns_frame = btns

        prog_card = ctk.CTkFrame(
            btns,
            corner_radius=ctrl_rad,
            fg_color=tokens.surface,
            border_width=1,
            border_color=tokens.border,
        )
        prog_card.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        prog_card.grid_columnconfigure(0, weight=1)
        self._prog_card = prog_card

        file_hdr = ctk.CTkFrame(prog_card, fg_color="transparent")
        file_hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 2))
        file_hdr.grid_columnconfigure(0, weight=1)

        self.file_label = ctk.CTkLabel(
            file_hdr,
            text=t("file_progress_lbl", lang),
            font=font_caption(fsize),
            text_color=tokens.text2,
            anchor="w",
        )
        self.file_label.grid(row=0, column=0, sticky="w")

        self.file_pct_label = ctk.CTkLabel(
            file_hdr,
            text="0%",
            font=font_mono(),
            text_color=tokens.muted,
            anchor="e",
        )
        self.file_pct_label.grid(row=0, column=1, sticky="e")

        self.progress = ctk.CTkProgressBar(
            prog_card,
            height=6,
            corner_radius=RADIUS_PILL,
            progress_color=tokens.accent,
            fg_color=tokens.surface_raised,
        )
        self.progress.set(0)
        self.progress.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))

        batch_hdr = ctk.CTkFrame(prog_card, fg_color="transparent")
        batch_hdr.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 2))
        batch_hdr.grid_columnconfigure(0, weight=1)

        self.batch_label = ctk.CTkLabel(
            batch_hdr,
            text=t("batch_progress_lbl", lang),
            font=font_caption(fsize),
            text_color=tokens.text2,
            anchor="w",
        )
        self.batch_label.grid(row=0, column=0, sticky="w")

        self.batch_pct_label = ctk.CTkLabel(
            batch_hdr,
            text="0%",
            font=font_mono(),
            text_color=tokens.muted,
            anchor="e",
        )
        self.batch_pct_label.grid(row=0, column=1, sticky="e")

        self.progress_batch = ctk.CTkProgressBar(
            prog_card,
            height=6,
            corner_radius=RADIUS_PILL,
            progress_color=tokens.accent,
            fg_color=tokens.surface_raised,
        )
        self.progress_batch.set(0)
        self.progress_batch.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 8))

        zap_ico = get_icon("zap", (16, 16))
        self.patch_btn = ctk.CTkButton(
            btns,
            text=t("start_patch", lang),
            image=zap_ico,
            compound="left",
            height=40,
            corner_radius=ctrl_rad,
            font=font_body(bold=True, size_opt=fsize),
            fg_color=tokens.accent,
            hover_color=tokens.accent_hover,
            border_width=0,
            text_color="#FFFFFF",
            command=self._patch_clicked,
            state="disabled",
        )
        self.patch_btn.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        attach_focus_ring(self.patch_btn)

        self.cancel_btn = ctk.CTkButton(
            btns,
            text=t("cancel_btn", lang),
            height=32,
            corner_radius=ctrl_rad,
            fg_color=tokens.surface_raised,
            hover_color=STATUS_DANGER_BG,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.muted,
            font=font_caption(fsize),
            command=self._on_cancel,
            state="disabled",
        )
        self.cancel_btn.grid(row=2, column=0, sticky="ew")
        attach_focus_ring(self.cancel_btn)

        preset = (
            settings.last_preset if settings.last_preset in [*FPS_PRESETS, CUSTOM] else "60 FPS"
        )
        self.preset.set(preset)
        self._preset_changed(preset)

        # Register theme updates
        self._theme_mgr.subscribe(self.apply_theme)

    # ---------- theme & localization ----------
    def apply_theme(self, tokens: ThemeTokens) -> None:
        _, ctrl_rad = get_corner_radii(self.settings.radius_style)
        fsize = self.settings.font_size
        lang = self.settings.language

        self.target_label.configure(
            text=t("target_fps", lang),
            text_color=tokens.text2,
            font=font_section(fsize),
        )
        self.ts_label.configure(
            text=t("timescale_lbl", lang),
            text_color=tokens.text2,
            font=font_caption(fsize),
        )
        self.strat_label.configure(
            text=t("strategy_lbl", lang),
            text_color=tokens.text2,
            font=font_caption(fsize),
        )
        self.profile_label.configure(
            text=t("platform_profile_lbl", lang),
            text_color=tokens.text2,
            font=font_caption(fsize),
        )
        self.profile_disclaimer.configure(
            text=t("readiness_disclaimer", lang),
            text_color=tokens.muted,
            font=font_caption(fsize),
        )
        self.output_lbl.configure(
            text=t("output_lbl", lang),
            text_color=tokens.text2,
            font=font_section(fsize),
        )

        self.preset.configure(
            selected_color=tokens.accent,
            selected_hover_color=tokens.accent_hover,
            unselected_color=tokens.surface_raised,
            unselected_hover_color=tokens.surface_hover,
            text_color=tokens.text,
            corner_radius=ctrl_rad,
            font=font_body(bold=True, size_opt=fsize),
        )
        is_custom = self.preset.get() == CUSTOM
        self.timescale.configure(
            fg_color=tokens.surface if is_custom else tokens.surface_raised,
            border_color=tokens.border,
            text_color=tokens.text if is_custom else tokens.muted,
            corner_radius=ctrl_rad,
            font=font_mono(),
        )
        self.strategy.configure(
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
            font=font_caption(fsize),
        )
        self.profile.configure(
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
            font=font_caption(fsize),
        )
        self._refresh_profile_menu()
        self.pc_warn_frame.configure(
            fg_color=STATUS_WARNING_BG,
            border_color=STATUS_WARNING_BORDER,
            corner_radius=ctrl_rad,
        )
        self.pc_warn_label.configure(
            text=t("bxd_pc_warn", lang),
            text_color=STATUS_WARNING_TEXT,
            font=font_caption(fsize),
        )

        self.override_card.configure(
            fg_color=tokens.surface,
            border_color=tokens.border,
            corner_radius=ctrl_rad,
        )
        self.override_toggle_btn.configure(
            hover_color=tokens.surface_hover,
            text_color=tokens.text2,
            font=font_caption(fsize),
        )
        self.override_lbl.configure(
            text=t("override_section", lang),
            text_color=tokens.text2,
            font=font_caption(fsize),
        )
        self.override_summary_badge.configure(font=font_caption(fsize))
        self.btn_set_override.configure(
            text=t("override_apply_btn", lang),
            fg_color=tokens.accent_light,
            hover_color=tokens.surface_hover,
            text_color=tokens.accent,
            font=font_caption(fsize),
        )
        self.btn_clear_override.configure(
            text=t("override_clear_btn", lang),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text2,
            font=font_caption(fsize),
        )
        self._refresh_override_ui()

        self.out_entry.configure(
            fg_color=tokens.surface,
            border_color=tokens.border,
            text_color=tokens.text,
            placeholder_text=t("same_as_source", lang),
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self._refresh_out()

        self.btn_pick_out.configure(
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            border_color=tokens.border,
            corner_radius=ctrl_rad,
        )
        self.btn_reset_out.configure(
            hover_color=tokens.surface_raised,
            text_color=tokens.muted,
            border_color=tokens.border,
            corner_radius=ctrl_rad,
        )
        chk_common = {
            "font": font_caption(fsize),
            "text_color": tokens.text2,
            "fg_color": MAC_CHECKBOX_FG_COLOR,
            "border_color": MAC_CHECKBOX_BORDER_COLOR,
            "checkmark_color": MAC_CHECKBOX_CHECKMARK_COLOR,
        }
        self.overwrite_check.configure(
            text=t("overwrite_lbl", lang),
            **chk_common,
        )
        self.auto_rename_check.configure(
            text=t("auto_rename_lbl", lang),
            **chk_common,
        )
        self.dry_run_cb.configure(
            text=t("v4_dry_run", lang),
            **chk_common,
        )
        self.safe_write_cb.configure(
            text=t("backup_original", lang),
            **chk_common,
        )
        self.verify_cb.configure(
            text=t("verify_after", lang),
            **chk_common,
        )

        self._prog_card.configure(
            fg_color=tokens.surface,
            border_color=tokens.border,
            corner_radius=ctrl_rad,
        )
        self.file_label.configure(
            text=t("file_progress_lbl", lang),
            text_color=tokens.text2,
            font=font_caption(fsize),
        )
        self.file_pct_label.configure(text_color=tokens.muted, font=font_mono())
        self.batch_label.configure(
            text=t("batch_progress_lbl", lang),
            text_color=tokens.text2,
            font=font_caption(fsize),
        )
        self.batch_pct_label.configure(text_color=tokens.muted, font=font_mono())
        self.progress.configure(progress_color=tokens.accent, fg_color=tokens.surface_raised)
        self.progress_batch.configure(progress_color=tokens.accent, fg_color=tokens.surface_raised)

        zap_ico = get_icon("zap", (16, 16))
        self.patch_btn.configure(
            image=zap_ico,
            corner_radius=ctrl_rad,
            font=font_body(bold=True, size_opt=fsize),
        )
        self.cancel_btn.configure(
            text=t("cancel_btn", lang),
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.set_state(can_patch=self._can_patch, busy=self._busy)

    # ---------- per-item override ----------
    def _toggle_override_expanded(self) -> None:
        self._override_expanded = not self._override_expanded
        self._refresh_override_ui()

    def set_focused_item(self, item: QueueItem | None) -> None:
        cur = getattr(self, "_focused_item", None)
        if cur is item or (
            cur is not None
            and item is not None
            and cur.item_id == item.item_id
            and cur.timescale == item.timescale
            and cur.strategy == item.strategy
        ):
            return
        self._focused_item = item
        self._refresh_override_ui()

    def _refresh_override_ui(self) -> None:
        tokens = self._theme_mgr.tokens
        lang = self.settings.language
        item = self._focused_item
        parts: list[str] = []
        if item is not None:
            if item.timescale:
                parts.append(f"ts={item.timescale}")
            if item.strategy:
                strat_label = self._strategy_to_label.get(item.strategy, item.strategy)
                parts.append(strat_label)

        has_override = bool(parts)
        show_body = self._override_expanded or has_override
        ico = get_icon("chevron_down" if show_body else "chevron_right", (12, 12))
        self.override_toggle_btn.configure(
            image=ico,
            text="" if ico else ("▾" if show_body else "▸"),
        )
        if show_body:
            self.override_body.grid(row=1, column=0, sticky="ew")
        else:
            self.override_body.grid_remove()

        if item is None:
            self.btn_set_override.configure(state="disabled")
            self.btn_clear_override.configure(state="disabled")
            self.override_summary_badge.configure(
                text=t("empty_val", lang),
                text_color=tokens.muted,
            )
            self.override_status_lbl.configure(
                text=t("override_status_none", lang),
                text_color=tokens.muted,
            )
            return

        self.btn_set_override.configure(state="normal")
        if has_override:
            self.btn_clear_override.configure(state="normal")
            short_summary = ", ".join(parts)
            self.override_summary_badge.configure(
                text=short_summary,
                text_color=tokens.accent,
            )
            details = f"{item.path.name} ({short_summary})"
            self.override_status_lbl.configure(
                text=t("override_status_active", lang, details=details),
                text_color=tokens.accent,
            )
        else:
            self.btn_clear_override.configure(state="disabled")
            self.override_summary_badge.configure(
                text=t("empty_val", lang),
                text_color=tokens.muted,
            )
            self.override_status_lbl.configure(
                text=f"{item.path.name} — {t('override_status_none', lang)}",
                text_color=tokens.muted,
            )

    def _apply_item_override(self) -> None:
        if self._focused_item is None:
            return
        ts = self._read_timescale()
        if ts is None:
            self.timescale.configure(border_color=STATUS_DANGER_BORDER)
            return
        self.timescale.configure(border_color=self._theme_mgr.tokens.border)
        strategy = self.get_strategy()
        if self._on_override_change is not None:
            self._on_override_change(self._focused_item.path, ts, strategy)
        self._refresh_override_ui()

    def _clear_item_override(self) -> None:
        if self._focused_item is None:
            return
        if self._on_override_change is not None:
            self._on_override_change(self._focused_item.path, None, None)
        self._refresh_override_ui()

    # ---------- state & progress ----------
    def get_strategy(self) -> str:
        return self._label_to_strategy.get(self.strategy.get(), self.settings.strategy)

    def set_state(self, *, can_patch: bool, busy: bool) -> None:
        if (
            getattr(self, "_can_patch", None) == can_patch
            and getattr(self, "_busy", None) == busy
        ):
            return
        self._can_patch = can_patch
        self._busy = busy
        tokens = self._theme_mgr.tokens
        lang = self.settings.language

        zap_ico = get_icon("zap", (16, 16))

        if busy:
            self.patch_btn.configure(
                state="disabled",
                text=t("patching_btn", lang, pct=self._last_pct),
                image=zap_ico,
                fg_color=tokens.surface_raised,
                text_color=tokens.muted,
            )
            self.cancel_btn.configure(
                state="normal",
                text=t("cancel_btn", lang),
                fg_color=STATUS_DANGER_BG,
                border_color=STATUS_DANGER_BORDER,
                text_color=STATUS_DANGER_TEXT,
            )
        elif can_patch:
            self._last_pct = 0
            self.patch_btn.configure(
                state="normal",
                text=t("start_patch", lang),
                image=zap_ico,
                fg_color=tokens.accent,
                hover_color=tokens.accent_hover,
                text_color="#FFFFFF",
            )
            self.cancel_btn.configure(
                state="disabled",
                text=t("cancel_btn", lang),
                fg_color=tokens.surface_raised,
                border_color=tokens.border,
                text_color=tokens.muted,
            )
        else:
            self._last_pct = 0
            self.patch_btn.configure(
                state="disabled",
                text=t("start_patch", lang),
                image=zap_ico,
                fg_color=tokens.surface_raised,
                text_color=tokens.muted,
            )
            self.cancel_btn.configure(
                state="disabled",
                text=t("cancel_btn", lang),
                fg_color=tokens.surface_raised,
                border_color=tokens.border,
                text_color=tokens.muted,
            )

    def set_progress(self, fraction: float) -> None:
        clamped = max(0.0, min(1.0, fraction))
        self.progress.set(clamped)
        pct = int(clamped * 100)
        self._last_pct = pct
        self.file_label.configure(text=t("file_progress_lbl", self.settings.language))
        self.file_pct_label.configure(text=f"{pct}%")
        if self._busy:
            self.patch_btn.configure(text=t("patching_btn", self.settings.language, pct=pct))

    def set_batch_progress(
        self,
        file_fraction: float,
        overall_fraction: float,
        file_text: str = "",
        batch_text: str = "",
    ) -> None:
        f_clamped = max(0.0, min(1.0, file_fraction))
        o_clamped = max(0.0, min(1.0, overall_fraction))
        self.progress.set(f_clamped)
        self.progress_batch.set(o_clamped)
        pct_file = int(f_clamped * 100)
        pct_overall = int(o_clamped * 100)
        self._last_pct = pct_overall

        lang = self.settings.language
        self.file_label.configure(text=file_text or t("file_progress_lbl", lang))
        self.file_pct_label.configure(text=f"{pct_file}%")
        self.batch_label.configure(text=batch_text or t("batch_progress_lbl", lang))
        self.batch_pct_label.configure(text=f"{pct_overall}%")

        if self._busy:
            self.patch_btn.configure(text=t("patching_btn", lang, pct=pct_overall))

    # ---------- internals ----------
    def _update_pc_warn_visibility(self, strategy_key: str) -> None:
        if strategy_key in (
            "bxd-pc",
            "bxd-experimental",
            "bxd-bypass",
            "x1t-pc",
            "x1t-experimental",
            "x1t-bypass",
        ):
            self.pc_warn_label.configure(text=t("bxd_pc_warn", self.settings.language))
            self.pc_warn_frame.grid(row=3, column=0, sticky="ew", padx=6, pady=(0, 8))
        else:
            self.pc_warn_frame.grid_remove()

    def _strategy_selected(self, value: str) -> None:
        strategy = self._label_to_strategy.get(value, self.settings.strategy)
        self.settings.strategy = strategy
        self._update_pc_warn_visibility(strategy)
        if self._on_strategy_change:
            self._on_strategy_change()

    def _refresh_profile_menu(self) -> None:
        lang = self.settings.language
        self._profile_label_to_id = {
            t(profile.label_key, lang): profile.profile_id
            for profile in PLATFORM_PROFILES.values()
        }
        self.profile.configure(values=list(self._profile_label_to_id))
        self.profile.set(
            t(get_profile(self.settings.platform_profile).label_key, lang)
        )

    def set_profile(self, profile_id: str) -> None:
        """Sync the selector after settings were applied elsewhere."""
        self.settings.platform_profile = get_profile(profile_id).profile_id
        self._refresh_profile_menu()

    def _profile_selected(self, value: str) -> None:
        profile_id = self._profile_label_to_id.get(value, self.settings.platform_profile)
        self.settings.platform_profile = profile_id
        self.settings.save_async()
        if self._on_profile_change:
            self._on_profile_change()

    def _options_changed(self) -> None:
        self.settings.overwrite = bool(self.overwrite_check.get())
        self.settings.auto_rename = bool(self.auto_rename_check.get())
        self.settings.v4_dry_run = bool(self.dry_run_cb.get())
        self.settings.backup_original = bool(self.safe_write_cb.get())
        self.settings.verify_after = bool(self.verify_cb.get())

    def _preset_changed(self, value: str) -> None:
        if getattr(self, "_last_preset_val", None) == value:
            return
        self._last_preset_val = value
        tokens = self._theme_mgr.tokens
        self.timescale.configure(state="normal")
        self.timescale.delete(0, "end")
        if value == CUSTOM:
            self.timescale.insert(0, str(self.settings.custom_timescale))
            configure_cached(
                self.timescale,
                state="normal",
                fg_color=tokens.surface,
                text_color=tokens.text,
            )
        else:
            self.timescale.insert(0, str(FPS_PRESETS[value]))
            configure_cached(
                self.timescale,
                state="disabled",
                fg_color=tokens.surface_raised,
                text_color=tokens.muted,
            )
        self.settings.last_preset = value

    def _read_timescale(self) -> int | None:
        try:
            value = int(self.timescale.get().strip())
        except ValueError:
            return None
        return value if 1 <= value <= 2_147_483_647 else None

    def _patch_clicked(self) -> None:
        ts = self._read_timescale()
        if ts is None:
            self.timescale.configure(border_color=STATUS_DANGER_BORDER)
            return
        self.timescale.configure(border_color=self._theme_mgr.tokens.border)
        strategy = self._label_to_strategy[self.strategy.get()]
        self.settings.strategy = strategy
        self._options_changed()
        if self.preset.get() == CUSTOM:
            self.settings.custom_timescale = ts
        self._on_patch(ts, strategy)

    def _on_out_entry_edited(self, _event: Any = None) -> None:
        raw = self.out_entry.get().strip()
        same_lbl_en = t("same_as_source", "en")
        same_lbl_th = t("same_as_source", "th")
        if raw in ("", same_lbl_en, same_lbl_th):
            self.settings.output_dir = ""
        else:
            self.settings.output_dir = raw
        self._refresh_out()

    def _pick_out(self) -> None:
        chosen = filedialog.askdirectory(title="Output folder")
        if chosen:
            self.settings.output_dir = chosen
            self._refresh_out()

    def _reset_out(self) -> None:
        self.settings.output_dir = ""
        self._refresh_out()

    def _refresh_out(self) -> None:
        self.out_entry.delete(0, "end")
        if self.settings.output_dir:
            self.out_entry.insert(0, self.settings.output_dir)
        else:
            self.out_entry.configure(
                placeholder_text=t("same_as_source", self.settings.language)
            )
