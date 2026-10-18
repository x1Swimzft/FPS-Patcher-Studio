"""Target selection, strategy, output folder, PATCH / Cancel, progress."""

from __future__ import annotations

from collections.abc import Callable
from tkinter import filedialog
from typing import Any

import customtkinter as ctk

from ..config import Settings
from ..core.models import FPS_PRESETS
from ..core.strategies import UI_PRESETS, migrate_strategy_name
from .strings import t
from .theme import (
    RADIUS_CARD,
    RADIUS_CONTROL,
    RADIUS_PILL,
    STATUS_DANGER_BG,
    STATUS_DANGER_BORDER,
    STATUS_DANGER_TEXT,
    STATUS_WARNING_BG,
    STATUS_WARNING_TEXT,
    ThemeTokens,
    font_body,
    font_caption,
    font_section,
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
    ) -> None:
        self.settings = settings
        self._theme_mgr = get_theme_manager(settings)
        tokens = self._theme_mgr.tokens

        super().__init__(
            master,
            corner_radius=RADIUS_CARD,
            fg_color=tokens.surface,
            border_width=1,
            border_color=tokens.border,
        )
        self._on_patch = on_patch
        self._on_cancel = on_cancel
        self._on_strategy_change = on_strategy_change
        self._label_to_strategy = {s.label: s.name for s in UI_PRESETS.values()}
        self._can_patch = False
        self._busy = False
        self.grid_columnconfigure(1, weight=1)

        # 0. Target Presets
        self.target_label = ctk.CTkLabel(
            self,
            text=t("target_fps", settings.language),
            font=font_section(),
            text_color=tokens.text2,
        )
        self.target_label.grid(row=0, column=0, sticky="w", padx=14, pady=(10, 4))

        self.preset = ctk.CTkSegmentedButton(
            self,
            values=[*FPS_PRESETS, CUSTOM],
            command=self._preset_changed,
            selected_color=tokens.accent,
            selected_hover_color=tokens.accent_hover,
            unselected_color=tokens.surface_raised,
            unselected_hover_color=tokens.surface,
            text_color=tokens.text,
            corner_radius=RADIUS_CONTROL,
            font=font_body(bold=True),
            border_width=1,
        )
        self.preset.grid(row=0, column=1, sticky="ew", padx=(0, 14), pady=(10, 4))

        # 1. Timescale entry
        self.ts_label = ctk.CTkLabel(
            self,
            text=t("timescale_lbl", settings.language),
            font=font_caption(),
            text_color=tokens.text2,
        )
        self.ts_label.grid(row=1, column=0, sticky="w", padx=14, pady=3)

        self.timescale = ctk.CTkEntry(
            self,
            height=30,
            corner_radius=RADIUS_CONTROL,
            fg_color=tokens.surface_raised,
            border_color=tokens.border,
            border_width=1,
            text_color=tokens.text,
            font=font_body(),
        )
        self.timescale.grid(row=1, column=1, sticky="ew", padx=(0, 14), pady=3)

        # 2. Preset selection (BXD Presets only)
        self.strat_label = ctk.CTkLabel(
            self,
            text=t("strategy_lbl", settings.language),
            font=font_caption(),
            text_color=tokens.text2,
        )
        self.strat_label.grid(row=2, column=0, sticky="w", padx=14, pady=3)

        labels = list(self._label_to_strategy)
        self.strategy = ctk.CTkOptionMenu(
            self,
            height=30,
            corner_radius=RADIUS_CONTROL,
            values=labels,
            command=self._strategy_selected,
            fg_color=tokens.surface_raised,
            button_color=tokens.border,
            button_hover_color=tokens.accent,
            text_color=tokens.text,
            font=font_caption(),
        )
        resolved_key, _ = migrate_strategy_name(settings.strategy)
        current = UI_PRESETS.get(resolved_key)
        self.strategy.set(current.label if current else labels[0])
        self.strategy.grid(row=2, column=1, sticky="ew", padx=(0, 14), pady=3)

        # 2b. Warning banner when Bxd For PC is active
        self.pc_warn_label = ctk.CTkLabel(
            self,
            text=t("bxd_pc_warn", settings.language),
            font=font_caption(),
            fg_color=STATUS_WARNING_BG,
            text_color=STATUS_WARNING_TEXT,
            corner_radius=RADIUS_CONTROL,
            padx=8,
            pady=4,
            wraplength=420,
            justify="left",
        )
        self._update_pc_warn_visibility(resolved_key)

        # 3. Output directory
        self.output_lbl = ctk.CTkLabel(
            self,
            text=t("output_lbl", settings.language),
            font=font_caption(),
            text_color=tokens.text2,
        )
        self.output_lbl.grid(row=4, column=0, sticky="w", padx=14, pady=3)

        out_row = ctk.CTkFrame(self, fg_color="transparent")
        out_row.grid(row=4, column=1, sticky="ew", padx=(0, 14), pady=3)
        out_row.grid_columnconfigure(0, weight=1)

        self.out_label = ctk.CTkLabel(
            out_row,
            text="",
            font=font_caption(),
            text_color=tokens.text,
            anchor="w",
        )
        self.out_label.grid(row=0, column=0, sticky="ew")

        self.btn_pick_out = ctk.CTkButton(
            out_row,
            text="📁",
            width=30,
            height=28,
            corner_radius=RADIUS_CONTROL,
            command=self._pick_out,
            fg_color=tokens.surface_raised,
            hover_color=tokens.border,
            text_color=tokens.text,
            border_width=1,
            border_color=tokens.border,
        )
        self.btn_pick_out.grid(row=0, column=1, padx=(4, 0))

        self.btn_reset_out = ctk.CTkButton(
            out_row,
            text="↺",
            width=30,
            height=28,
            corner_radius=RADIUS_CONTROL,
            fg_color="transparent",
            hover_color=tokens.surface_raised,
            text_color=tokens.muted,
            border_width=1,
            border_color=tokens.border,
            command=self._reset_out,
        )
        self.btn_reset_out.grid(row=0, column=2, padx=(4, 0))
        self._refresh_out()

        # 4. Checkboxes
        opt_row = ctk.CTkFrame(self, fg_color="transparent")
        opt_row.grid(row=5, column=0, columnspan=2, sticky="w", padx=14, pady=(2, 2))

        self.overwrite_check = ctk.CTkCheckBox(
            opt_row,
            text=t("overwrite_lbl", settings.language),
            font=font_caption(),
            text_color=tokens.text2,
            checkmark_color="#FFFFFF",
            fg_color=tokens.accent,
            hover_color=tokens.accent_hover,
            border_color=tokens.border,
            command=self._options_changed,
        )
        self.overwrite_check.grid(row=0, column=0, padx=(0, 14))
        if settings.overwrite:
            self.overwrite_check.select()

        self.auto_rename_check = ctk.CTkCheckBox(
            opt_row,
            text=t("auto_rename_lbl", settings.language),
            font=font_caption(),
            text_color=tokens.text2,
            checkmark_color="#FFFFFF",
            fg_color=tokens.accent,
            hover_color=tokens.accent_hover,
            border_color=tokens.border,
            command=self._options_changed,
        )
        self.auto_rename_check.grid(row=0, column=1, padx=(0, 10))
        if settings.auto_rename:
            self.auto_rename_check.select()

        # 5. Progress bars (8px height, accent fill)
        self.file_label = ctk.CTkLabel(
            self,
            text=t("file_progress", settings.language, pct=0),
            font=font_caption(),
            text_color=tokens.muted,
            anchor="w",
        )
        self.file_label.grid(row=6, column=0, columnspan=2, sticky="w", padx=14, pady=(4, 1))

        self.progress = ctk.CTkProgressBar(
            self,
            height=8,
            corner_radius=RADIUS_PILL,
            progress_color=tokens.accent,
            fg_color=tokens.border,
        )
        self.progress.set(0)
        self.progress.grid(row=7, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 2))

        self.batch_label = ctk.CTkLabel(
            self,
            text=t("batch_progress", settings.language, pct=0),
            font=font_caption(),
            text_color=tokens.muted,
            anchor="w",
        )
        self.batch_label.grid(row=8, column=0, columnspan=2, sticky="w", padx=14, pady=(2, 1))

        self.progress_batch = ctk.CTkProgressBar(
            self,
            height=8,
            corner_radius=RADIUS_PILL,
            progress_color=tokens.accent,
            fg_color=tokens.border,
        )
        self.progress_batch.set(0)
        self.progress_batch.grid(row=9, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 4))

        # 6. Action buttons row (Height 48, solid accent fill, glow border)
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=10, column=0, columnspan=2, sticky="ew", padx=14, pady=(6, 12))
        btns.grid_columnconfigure(0, weight=1)

        self.patch_btn = ctk.CTkButton(
            btns,
            text=t("start_patch", settings.language),
            height=48,
            corner_radius=RADIUS_CONTROL,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=tokens.accent,
            hover_color=tokens.accent_hover,
            border_width=1,
            border_color=tokens.accent_glow,
            text_color="#FFFFFF",
            command=self._patch_clicked,
            state="disabled",
        )
        self.patch_btn.grid(row=0, column=0, sticky="ew")

        self.cancel_btn = ctk.CTkButton(
            btns,
            text=t("cancel_btn", settings.language),
            width=90,
            height=48,
            corner_radius=RADIUS_CONTROL,
            fg_color="transparent",
            hover_color=STATUS_DANGER_BG,
            border_width=1,
            border_color=STATUS_DANGER_BORDER,
            text_color=STATUS_DANGER_TEXT,
            font=font_body(bold=True),
            command=self._on_cancel,
            state="disabled",
        )
        self.cancel_btn.grid(row=0, column=1, padx=(8, 0))

        preset = (
            settings.last_preset if settings.last_preset in [*FPS_PRESETS, CUSTOM] else "60 FPS"
        )
        self.preset.set(preset)
        self._preset_changed(preset)

        # Register theme updates
        self._theme_mgr.subscribe(self.apply_theme)

    def apply_theme(self, tokens: ThemeTokens) -> None:
        self.configure(fg_color=tokens.surface, border_color=tokens.border)
        self.target_label.configure(text_color=tokens.text2)
        self.ts_label.configure(text_color=tokens.text2)
        self.strat_label.configure(text_color=tokens.text2)
        self.output_lbl.configure(text_color=tokens.text2)
        self.preset.configure(
            selected_color=tokens.accent,
            selected_hover_color=tokens.accent_hover,
            unselected_color=tokens.surface_raised,
            text_color=tokens.text,
        )
        self.timescale.configure(
            fg_color=tokens.surface_raised,
            border_color=tokens.border,
            text_color=tokens.text,
        )
        self.strategy.configure(
            fg_color=tokens.surface_raised,
            button_color=tokens.border,
            button_hover_color=tokens.accent,
            text_color=tokens.text,
        )
        self.out_label.configure(text_color=tokens.text)
        self.btn_pick_out.configure(
            fg_color=tokens.surface_raised,
            hover_color=tokens.border,
            text_color=tokens.text,
            border_color=tokens.border,
        )
        self.btn_reset_out.configure(
            hover_color=tokens.surface_raised,
            text_color=tokens.muted,
            border_color=tokens.border,
        )
        self.overwrite_check.configure(
            text_color=tokens.text2,
            fg_color=tokens.accent,
            hover_color=tokens.accent_hover,
            border_color=tokens.border,
        )
        self.auto_rename_check.configure(
            text_color=tokens.text2,
            fg_color=tokens.accent,
            hover_color=tokens.accent_hover,
            border_color=tokens.border,
        )
        self.progress.configure(progress_color=tokens.accent, fg_color=tokens.border)
        self.progress_batch.configure(progress_color=tokens.accent, fg_color=tokens.border)
        self.set_state(can_patch=self._can_patch, busy=self._busy)

    def get_strategy(self) -> str:
        return self._label_to_strategy.get(self.strategy.get(), self.settings.strategy)

    def set_state(self, *, can_patch: bool, busy: bool) -> None:
        self._can_patch = can_patch
        self._busy = busy
        tokens = self._theme_mgr.tokens

        if busy:
            self.patch_btn.configure(
                state="disabled",
                fg_color=tokens.surface_raised,
                border_color=tokens.border,
                text_color=tokens.muted,
            )
            self.cancel_btn.configure(
                state="normal",
                fg_color=STATUS_DANGER_BG,
                border_color=STATUS_DANGER_BORDER,
                text_color=STATUS_DANGER_TEXT,
            )
        elif can_patch:
            self.patch_btn.configure(
                state="normal",
                text=t("start_patch", self.settings.language),
                fg_color=tokens.accent,
                hover_color=tokens.accent_hover,
                border_color=tokens.accent_glow,
                text_color="#FFFFFF",
            )
            self.cancel_btn.configure(
                state="disabled",
                fg_color="transparent",
                border_color=tokens.border,
                text_color=tokens.muted,
            )
        else:
            self.patch_btn.configure(
                state="disabled",
                text=t("start_patch", self.settings.language),
                fg_color=tokens.surface_raised,
                border_color=tokens.border,
                text_color=tokens.muted,
            )
            self.cancel_btn.configure(
                state="disabled",
                fg_color="transparent",
                border_color=tokens.border,
                text_color=tokens.muted,
            )

    def set_progress(self, fraction: float) -> None:
        self.progress.set(fraction)
        pct = int(fraction * 100)
        self.file_label.configure(text=t("file_progress", self.settings.language, pct=pct))
        if self._busy:
            self.patch_btn.configure(text=t("patching_btn", self.settings.language, pct=pct))

    def set_batch_progress(
        self,
        file_fraction: float,
        overall_fraction: float,
        file_text: str = "",
        batch_text: str = "",
    ) -> None:
        self.progress.set(file_fraction)
        self.progress_batch.set(overall_fraction)
        pct = int(overall_fraction * 100)
        if file_text:
            self.file_label.configure(text=file_text)
        else:
            pct_file = int(file_fraction * 100)
            self.file_label.configure(text=t("file_progress", self.settings.language, pct=pct_file))
        if batch_text:
            self.batch_label.configure(text=batch_text)
        else:
            self.batch_label.configure(text=t("batch_progress", self.settings.language, pct=pct))

        if self._busy:
            self.patch_btn.configure(text=t("patching_btn", self.settings.language, pct=pct))

    # ---------- internals ----------
    def _update_pc_warn_visibility(self, strategy_key: str) -> None:
        if strategy_key in ("bxd-pc", "bxd-experimental", "bxd-bypass"):
            self.pc_warn_label.configure(text=t("bxd_pc_warn", self.settings.language))
            self.pc_warn_label.grid(
                row=3, column=0, columnspan=2, sticky="ew", padx=14, pady=(2, 2)
            )
        else:
            self.pc_warn_label.grid_remove()

    def _strategy_selected(self, value: str) -> None:
        strategy = self._label_to_strategy.get(value, self.settings.strategy)
        self.settings.strategy = strategy
        self._update_pc_warn_visibility(strategy)
        if self._on_strategy_change:
            self._on_strategy_change()

    def _options_changed(self) -> None:
        self.settings.overwrite = bool(self.overwrite_check.get())
        self.settings.auto_rename = bool(self.auto_rename_check.get())

    def _preset_changed(self, value: str) -> None:
        self.timescale.configure(state="normal")
        self.timescale.delete(0, "end")
        if value == CUSTOM:
            self.timescale.insert(0, str(self.settings.custom_timescale))
        else:
            self.timescale.insert(0, str(FPS_PRESETS[value]))
            self.timescale.configure(state="disabled")
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

    def _pick_out(self) -> None:
        chosen = filedialog.askdirectory(title="Output folder")
        if chosen:
            self.settings.output_dir = chosen
            self._refresh_out()

    def _reset_out(self) -> None:
        self.settings.output_dir = ""
        self._refresh_out()

    def _refresh_out(self) -> None:
        text = self.settings.output_dir or "Same folder as source"
        if len(text) > 36:
            text = "…" + text[-34:]
        self.out_label.configure(text=text)
