"""Input list widget displaying items in InputQueue with modern cards, badges, and controls."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from tkinter import Menu, filedialog, messagebox
from typing import Any

import customtkinter as ctk

from ..app.controller import AppController
from ..app.queue_model import QueueItem
from ..core.models import SUPPORTED_EXTENSIONS
from .drop_zone import DropZone
from .icons import get_icon
from .strings import t
from .theme import (
    RADIUS_PILL,
    STATUS_DANGER_BG,
    STATUS_DANGER_TEXT,
    STATUS_MUTED_BG,
    STATUS_MUTED_TEXT,
    STATUS_SUCCESS_BG,
    STATUS_SUCCESS_TEXT,
    STATUS_WARNING_BG,
    STATUS_WARNING_TEXT,
    ThemeTokens,
    font_body,
    font_caption,
    get_corner_radii,
    get_theme_manager,
)
from .thumbnails import request_thumbnail

THUMB_SIZE = (72, 44)


def _format_duration(seconds: float) -> str:
    if not seconds or seconds <= 0:
        return "00:00"
    total_sec = int(round(seconds))
    mins, secs = divmod(total_sec, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs:d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def _format_meta(item: QueueItem) -> str:
    info = item.info
    if info is None:
        return "—"
    parts: list[str] = []
    if info.width and info.height:
        parts.append(f"{info.width}×{info.height}")
    if info.duration_s:
        parts.append(_format_duration(info.duration_s))
    if info.fps:
        fps_str = f"{info.fps:.2f}".rstrip("0").rstrip(".")
        parts.append(f"{fps_str} fps")
    return " · ".join(parts) if parts else "—"


class InputList(ctk.CTkFrame):
    def __init__(
        self,
        master: Any,
        controller: AppController,
        on_start_patch_selected: Callable[[], None],
    ) -> None:
        self.controller = controller
        self.settings = controller.settings
        self._on_start_patch_selected = on_start_patch_selected
        self._on_focus_change: Callable[[Path | None], None] | None = None
        self._theme_mgr = get_theme_manager(self.settings)
        tokens = self._theme_mgr.tokens
        card_rad, _ = get_corner_radii(self.settings.radius_style)

        super().__init__(
            master,
            corner_radius=card_rad,
            fg_color=tokens.bg,
            border_width=0,
        )
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._row_widgets: dict[str, ctk.CTkFrame] = {}
        self._row_sigs: dict[str, tuple[Any, ...]] = {}
        self._last_order: list[str] = []
        self._ctk_images: dict[str, ctk.CTkImage] = {}
        self._thumb_requested: set[str] = set()
        self._can_patch = False
        self._busy = False

        self._build_top_toolbar()
        self._build_scrollable_area()
        self._build_preview_strip()
        self._build_bottom_toolbar()

        self._theme_mgr.subscribe(self.apply_theme)

    def set_on_focus_change(self, callback: Callable[[Path | None], None]) -> None:
        self._on_focus_change = callback

    def _tr(self, key: str, **kwargs: object) -> str:
        return t(key, self.settings.language, **kwargs)

    def _fsize(self) -> str:
        return getattr(self.settings, "font_size", "M")

    def _radii(self) -> tuple[int, int]:
        return get_corner_radii(getattr(self.settings, "radius_style", "Normal"))

    # ---------- top toolbar ----------
    def _build_top_toolbar(self) -> None:
        tokens = self._theme_mgr.tokens
        _, ctrl_rad = self._radii()
        fsize = self._fsize()

        self.top_bar = ctk.CTkFrame(self, fg_color=tokens.bg, height=36)
        self.top_bar.grid(row=0, column=0, sticky="ew", padx=4, pady=(2, 6))
        self.top_bar.grid_columnconfigure(2, weight=1)

        # Left buttons: Add Files, Add Folder (soft tinted per Apple HIG spec)
        left_box = ctk.CTkFrame(self.top_bar, fg_color=tokens.bg)
        left_box.grid(row=0, column=0, sticky="w")

        self.btn_add_files = ctk.CTkButton(
            left_box,
            text=f"＋ {self._tr('add_files_btn')}",
            height=28,
            width=96,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=0,
            text_color=tokens.text,
            command=self._browse_files,
        )
        self.btn_add_files.pack(side="left", padx=(0, 6))

        folder_ico = get_icon("folder", (14, 14))
        self.btn_add_folder = ctk.CTkButton(
            left_box,
            text=self._tr("add_folder_btn") if folder_ico else f"📁 {self._tr('add_folder_btn')}",
            image=folder_ico,
            compound="left",
            height=28,
            width=102,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=0,
            text_color=tokens.text,
            command=self._browse_folder,
        )
        self.btn_add_folder.pack(side="left", padx=(0, 6))

        # Hidden/compatibility title label
        self.lbl_title = ctk.CTkLabel(
            self.top_bar,
            text="",
            width=1,
            font=font_caption(fsize),
            text_color=tokens.text2,
        )

        # Right buttons: Retry Failed (when needed), Select All, Clear Selection
        right_box = ctk.CTkFrame(self.top_bar, fg_color="transparent")
        right_box.grid(row=0, column=3, sticky="e")

        self.btn_retry_failed = ctk.CTkButton(
            right_box,
            text=self._tr("retry_failed"),
            height=28,
            width=92,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=STATUS_WARNING_BG,
            hover_color=tokens.surface_hover,
            border_width=0,
            text_color=STATUS_WARNING_TEXT,
            command=self._retry_failed,
        )

        self.btn_select_all = ctk.CTkButton(
            right_box,
            text=self._tr("select_all"),
            height=28,
            width=88,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=0,
            text_color=tokens.text,
            command=self._toggle_select_all,
        )
        self.btn_select_all.pack(side="left", padx=(0, 6))

        self.btn_clear_selection = ctk.CTkButton(
            right_box,
            text=self._tr("clear_selection"),
            height=28,
            width=104,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=0,
            text_color=tokens.text,
            command=self._clear_selection,
        )
        self.btn_clear_selection.pack(side="left", padx=(0, 6))

        self.btn_clear_all = ctk.CTkButton(
            right_box,
            text=self._tr("clear_all"),
            height=28,
            width=88,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=0,
            text_color=tokens.text,
            command=self._clear_all,
        )
        self.btn_clear_all.pack(side="left")

        # Compatibility buttons preserved for external references
        self.btn_del_selected = self.btn_clear_selection
        self.btn_clear_inputs = self.btn_clear_all

    # ---------- scrollable list ----------
    def _build_scrollable_area(self) -> None:
        tokens = self._theme_mgr.tokens
        _, ctrl_rad = self._radii()

        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=tokens.bg,
            corner_radius=ctrl_rad,
            border_width=0,
        )
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.scroll.grid_columnconfigure(0, weight=1)

        # Empty state with existing DropZone preserved
        self.drop_zone = DropZone(self.scroll, on_files=self._on_dropped_files)
        self.drop_zone.pack(fill="both", expand=True, padx=4, pady=12)
        self.empty_label = self.drop_zone.label

    # ---------- preview player strip ----------
    def _build_preview_strip(self) -> None:
        tokens = self._theme_mgr.tokens
        card_rad, ctrl_rad = self._radii()
        fsize = self._fsize()

        self.preview_strip = ctk.CTkFrame(
            self,
            corner_radius=card_rad,
            fg_color=tokens.surface_raised,
            border_width=1,
            border_color=tokens.border,
        )
        self.preview_strip.grid_columnconfigure(1, weight=1)

        self.preview_thumb_lbl = ctk.CTkLabel(
            self.preview_strip,
            text="🎬",
            width=88,
            height=50,
            corner_radius=8,
            fg_color=tokens.surface,
            text_color=tokens.muted,
            font=font_caption(fsize),
        )
        self.preview_thumb_lbl.grid(row=0, column=0, padx=(10, 10), pady=8)

        info_col = ctk.CTkFrame(self.preview_strip, fg_color="transparent")
        info_col.grid(row=0, column=1, sticky="ew", pady=8)

        self.preview_name_lbl = ctk.CTkLabel(
            info_col,
            text="—",
            font=font_body(bold=True, size_opt=fsize),
            text_color=tokens.text,
            anchor="w",
        )
        self.preview_name_lbl.pack(anchor="w")

        self.preview_meta_lbl = ctk.CTkLabel(
            info_col,
            text="—",
            font=font_caption(fsize),
            text_color=tokens.muted,
            anchor="w",
        )
        self.preview_meta_lbl.pack(anchor="w")

        self.preview_play_btn = ctk.CTkButton(
            self.preview_strip,
            text=self._tr("open_in_player"),
            height=28,
            width=76,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.accent_light,
            hover_color=tokens.accent_glow,
            text_color=tokens.accent,
            border_width=0,
            command=self._play_active_file,
        )
        self.preview_play_btn.grid(row=0, column=2, padx=(8, 12), pady=8)

    # ---------- bottom toolbar ----------
    def _build_bottom_toolbar(self) -> None:
        tokens = self._theme_mgr.tokens
        _, ctrl_rad = self._radii()
        fsize = self._fsize()

        self.bottom_bar = ctk.CTkFrame(
            self,
            fg_color="transparent",
            height=42,
            corner_radius=0,
        )
        self.bottom_bar.grid(row=3, column=0, sticky="ew", padx=4, pady=(6, 0))
        self.bottom_bar.grid_columnconfigure(1, weight=1)

        self.bottom_divider = ctk.CTkFrame(
            self.bottom_bar,
            height=1,
            fg_color=tokens.border,
            corner_radius=0,
        )
        self.bottom_divider.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        # Left: Preview Player switch
        self.player_switch = ctk.CTkSwitch(
            self.bottom_bar,
            text=self._tr("preview_player"),
            font=font_caption(fsize),
            text_color=tokens.text,
            progress_color=tokens.success,
            command=self._toggle_player,
        )
        self.player_switch.grid(row=1, column=0, sticky="w", padx=4)

        # Center/Right: "N of M selected"
        self.lbl_selected_count = ctk.CTkLabel(
            self.bottom_bar,
            text=self._tr("selected_count", selected=0, total=0),
            font=font_caption(fsize),
            text_color=tokens.muted,
        )
        self.lbl_selected_count.grid(row=1, column=1, sticky="e", padx=(8, 12))

        # Right: Apply Selected (soft blue button calling Start Patch handler)
        self.btn_apply_selected = ctk.CTkButton(
            self.bottom_bar,
            text=self._tr("apply_selected"),
            height=28,
            width=116,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
            fg_color=tokens.accent_light,
            hover_color=tokens.accent_glow,
            text_color=tokens.accent,
            border_width=0,
            command=self._on_start_patch_selected,
        )
        self.btn_apply_selected.grid(row=1, column=2, sticky="e", padx=2)

    # ---------- focus & state helpers ----------
    def set_state(self, *, busy: bool) -> None:
        if getattr(self, "_busy", None) == busy:
            return
        self._busy = busy
        state = "disabled" if busy else "normal"
        for btn in (
            getattr(self, "btn_add_files", None),
            getattr(self, "btn_add_folder", None),
            getattr(self, "btn_retry_failed", None),
            getattr(self, "btn_select_all", None),
            getattr(self, "btn_clear_selection", None),
            getattr(self, "btn_clear_all", None),
            getattr(self, "btn_apply_selected", None),
        ):
            if btn is not None:
                with contextlib.suppress(Exception):
                    if btn.cget("state") != state:
                        btn.configure(state=state)

    def _resolve_active_item(self, items: list[QueueItem]) -> QueueItem | None:
        """Resolve active QueueItem from controller/queue_model without duplicate state."""
        if not items:
            return None
        if self.controller.current_patching_path is not None:
            found = self.controller.items.get(self.controller.current_patching_path)
            if found is not None:
                return found
        if self.controller.current is not None:
            for it in items:
                if it.info is self.controller.current:
                    return it
        selected = self.controller.items.selected()
        return selected[0] if selected else items[0]

    def _on_card_clicked(self, path: Path) -> None:
        item = self.controller.items.get(path)
        if item is not None and item.info is not None:
            self.controller.current = item.info
        if self._on_focus_change is not None:
            self._on_focus_change(path)
        self.render()

    # ---------- render queue ----------
    def render(self) -> None:
        """Synchronize UI rows with controller.items (InputQueue) in O(changed) time."""
        items = self.controller.items.items
        total = len(items)
        selected_items = self.controller.items.selected()
        sel_count = len(selected_items)

        self.lbl_selected_count.configure(
            text=self._tr("selected_count", selected=sel_count, total=total)
        )
        all_sel = bool(items and sel_count == total)
        self.btn_select_all.configure(
            text=self._tr("deselect_all") if all_sel else self._tr("select_all")
        )

        has_failed = any(i.status in ("failed", "skipped") for i in items)
        if has_failed:
            if not getattr(self.btn_retry_failed, "winfo_ismapped", lambda: False)():
                self.btn_retry_failed.pack(side="left", padx=(0, 6), before=self.btn_select_all)
        else:
            if getattr(self.btn_retry_failed, "winfo_ismapped", lambda: False)():
                self.btn_retry_failed.pack_forget()

        if not items:
            for w in self._row_widgets.values():
                w.destroy()
            self._row_widgets.clear()
            self._row_sigs.clear()
            self._last_order.clear()
            self.drop_zone.pack(fill="both", expand=True, padx=4, pady=12)
            self._update_preview_strip(None)
            return

        self.drop_zone.pack_forget()

        current_order = [i.item_id for i in items]
        current_ids = set(current_order)

        # Remove deleted rows
        for i_id in list(self._row_widgets.keys()):
            if i_id not in current_ids:
                self._row_widgets[i_id].destroy()
                del self._row_widgets[i_id]
                self._row_sigs.pop(i_id, None)

        # If FFmpeg became available after initial render, retry missing thumbnails
        missing_thumbs = len(self._ctk_images) < len(self._thumb_requested)
        if self.controller.ffmpeg is not None and missing_thumbs:
            for i_id in list(self._thumb_requested):
                if i_id not in self._ctk_images:
                    self._thumb_requested.discard(i_id)

        tokens = self._theme_mgr.tokens
        active_item = self._resolve_active_item(items)
        active_id = active_item.item_id if active_item is not None else None
        order_changed = current_order != self._last_order

        # Render or update rows only when row signature changes
        for item in items:
            is_focused = item.item_id == active_id
            sig = (
                item.selected,
                item.status,
                item.error,
                id(item.info) if item.info is not None else None,
                item.timescale,
                item.strategy,
                is_focused,
                self.settings.language,
                self.settings.radius_style,
                self.settings.font_size,
            )
            is_new = item.item_id not in self._row_widgets
            if is_new:
                row_frame = self._create_row_frame(item, tokens, is_focused=is_focused)
                self._row_widgets[item.item_id] = row_frame
                self._row_sigs[item.item_id] = sig
                row_frame.pack(fill="x", pady=4, padx=4)
            else:
                row_frame = self._row_widgets[item.item_id]
                if self._row_sigs.get(item.item_id) != sig:
                    self._update_row_content(row_frame, item, tokens, is_focused=is_focused)
                    self._row_sigs[item.item_id] = sig
                if order_changed:
                    row_frame.pack_forget()
                    row_frame.pack(fill="x", pady=4, padx=4)

            if item.item_id not in self._thumb_requested and self.controller.ffmpeg is not None:
                self._request_row_thumb(row_frame, item)

        self._last_order = current_order
        self._update_preview_strip(active_item)

    def _create_row_frame(
        self, item: QueueItem, tokens: ThemeTokens, *, is_focused: bool = False
    ) -> ctk.CTkFrame:
        card_rad, _ = self._radii()
        fsize = self._fsize()

        row = ctk.CTkFrame(
            self.scroll,
            height=64,
            corner_radius=card_rad,
            fg_color=tokens.surface_drop_hover if is_focused else tokens.surface,
            border_width=1,
            border_color=tokens.border_focus if is_focused else tokens.border,
        )
        row.grid_columnconfigure(2, weight=1)

        # 1. Checkbox
        chk = ctk.CTkCheckBox(
            row,
            text="",
            width=20,
            height=20,
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=5,
            border_width=1,
            fg_color=tokens.accent,
            hover_color=tokens.accent_hover,
            border_color=tokens.border,
            checkmark_color="#FFFFFF",
            command=lambda p=item.path: self._on_toggle(p),
        )
        chk.grid(row=0, column=0, padx=(12, 8), pady=10)
        if item.selected:
            chk.select()
        else:
            chk.deselect()
        row._chk = chk

        # 2. Thumbnail (72x44 rounded 8px)
        cached_img = self._ctk_images.get(item.item_id)
        thumb_lbl = ctk.CTkLabel(
            row,
            text="" if cached_img else "🎬",
            image=cached_img,
            width=THUMB_SIZE[0],
            height=THUMB_SIZE[1],
            corner_radius=8,
            fg_color=tokens.surface_raised,
            text_color=tokens.muted,
            font=font_caption(fsize),
        )
        thumb_lbl.grid(row=0, column=1, padx=(0, 12), pady=10)
        row._thumb = thumb_lbl

        # 3. Filename & Path / Error / Overrides
        center_box = ctk.CTkFrame(row, fg_color="transparent")
        center_box.grid(row=0, column=2, sticky="ew", padx=(0, 10), pady=8)

        lbl_path = ctk.CTkLabel(
            center_box,
            text=item.path.name,
            font=font_body(bold=True, size_opt=fsize),
            text_color=tokens.text,
            anchor="w",
        )
        lbl_path.pack(anchor="w", fill="x")
        row._lbl_path = lbl_path

        sub_info, is_err = self._format_sub_line(item)
        lbl_sub = ctk.CTkLabel(
            center_box,
            text=sub_info,
            font=font_caption(fsize),
            text_color=STATUS_DANGER_TEXT if is_err else tokens.muted,
            anchor="w",
        )
        lbl_sub.pack(anchor="w", fill="x")
        row._lbl_sub = lbl_sub

        # 4. Metadata ("1920×1080 · 00:42 · 60 fps")
        lbl_meta = ctk.CTkLabel(
            row,
            text=_format_meta(item),
            font=font_caption(fsize),
            text_color=tokens.muted,
            anchor="e",
        )
        lbl_meta.grid(row=0, column=3, sticky="e", padx=(0, 12), pady=10)
        row._lbl_meta = lbl_meta
        row._res_badge = lbl_meta
        row._fps_badge = lbl_meta

        # 5. Status Pill Badge
        status_badge = ctk.CTkLabel(
            row,
            text=self._tr(f"status_{item.status}"),
            font=font_caption(fsize),
            corner_radius=RADIUS_PILL,
            padx=10,
            height=22,
            **self._status_style(item.status),
        )
        status_badge.grid(row=0, column=4, sticky="e", padx=(0, 14), pady=10)
        row._status_badge = status_badge

        # Click to focus & lazy right-click context menu
        self._bind_row_events(row, item.path)
        return row

    def _request_row_thumb(self, row: ctk.CTkFrame, item: QueueItem) -> None:
        self._thumb_requested.add(item.item_id)
        ff_exe = self.controller.ffmpeg.ffmpeg if self.controller.ffmpeg else None
        thumb_lbl = getattr(row, "_thumb", None)
        if thumb_lbl is None:
            return

        def _on_thumb(
            img: Any | None, tlbl: ctk.CTkLabel = thumb_lbl, i_id: str = item.item_id
        ) -> None:
            self._on_thumb_ready(tlbl, img, i_id)

        request_thumbnail(item.path, ff_exe, THUMB_SIZE, _on_thumb)

    def _format_sub_line(self, item: QueueItem) -> tuple[str, bool]:
        if item.error:
            return f"Error: {item.error}", True
        sub = str(item.path)
        overrides: list[str] = []
        if item.timescale is not None:
            overrides.append(f"{item.timescale} ts")
        if item.strategy is not None:
            overrides.append(item.strategy)
        if overrides:
            sub = f"{sub}  [Override: {', '.join(overrides)}]"
        return sub, False

    def _update_row_content(
        self,
        row: ctk.CTkFrame,
        item: QueueItem,
        tokens: ThemeTokens,
        *,
        is_focused: bool = False,
    ) -> None:
        card_rad, _ = self._radii()
        fsize = self._fsize()

        row.configure(
            corner_radius=card_rad,
            fg_color=tokens.surface_drop_hover if is_focused else tokens.surface,
            border_color=tokens.border_focus if is_focused else tokens.border,
        )

        chk_w = getattr(row, "_chk", None)
        if chk_w:
            chk_w.configure(
                fg_color=tokens.accent,
                hover_color=tokens.accent_hover,
                border_color=tokens.border,
            )
            if item.selected:
                chk_w.select()
            else:
                chk_w.deselect()

        thumb_w = getattr(row, "_thumb", None)
        if thumb_w:
            thumb_w.configure(fg_color=tokens.surface_raised, text_color=tokens.muted)

        path_w = getattr(row, "_lbl_path", None)
        if path_w:
            path_w.configure(
                text=item.path.name,
                text_color=tokens.text,
                font=font_body(bold=True, size_opt=fsize),
            )

        sub_w = getattr(row, "_lbl_sub", None)
        if sub_w:
            sub_info, is_err = self._format_sub_line(item)
            sub_w.configure(
                text=sub_info,
                text_color=STATUS_DANGER_TEXT if is_err else tokens.muted,
                font=font_caption(fsize),
            )

        meta_w = getattr(row, "_lbl_meta", None)
        if meta_w:
            meta_w.configure(
                text=_format_meta(item),
                text_color=tokens.muted,
                font=font_caption(fsize),
            )

        status_w = getattr(row, "_status_badge", None)
        if status_w:
            status_w.configure(
                text=self._tr(f"status_{item.status}"),
                font=font_caption(fsize),
                **self._status_style(item.status),
            )

    def _status_style(self, status: str) -> dict[str, Any]:
        tokens = self._theme_mgr.tokens
        if status in ("done", "ready"):
            return {"fg_color": STATUS_SUCCESS_BG, "text_color": STATUS_SUCCESS_TEXT}
        if status == "failed":
            return {"fg_color": STATUS_DANGER_BG, "text_color": STATUS_DANGER_TEXT}
        if status == "patching":
            return {"fg_color": tokens.accent_light, "text_color": tokens.accent}
        if status in ("skipped", "probing"):
            return {"fg_color": STATUS_WARNING_BG, "text_color": STATUS_WARNING_TEXT}
        # pending
        return {"fg_color": STATUS_MUTED_BG, "text_color": STATUS_MUTED_TEXT}

    def _on_thumb_ready(self, label: ctk.CTkLabel, img: Any, item_id: str) -> None:
        if img is None:
            return

        def update_ui() -> None:
            try:
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=THUMB_SIZE)
                self._ctk_images[item_id] = ctk_img
                if label.winfo_exists():
                    label.configure(image=ctk_img, text="")
                if bool(self.player_switch.get()):
                    active = self._resolve_active_item(self.controller.items.items)
                    if active is not None and active.item_id == item_id:
                        self._update_preview_strip(active)
            except Exception:
                pass

        self.after(0, update_ui)

    def _update_preview_strip(self, active_item: QueueItem | None) -> None:
        if not bool(self.player_switch.get()) or active_item is None:
            self.preview_strip.grid_remove()
            self.preview_name_lbl.configure(text="—")
            self.preview_meta_lbl.configure(text="—")
            self.preview_thumb_lbl.configure(image=None, text="🎬")
            return

        self.preview_strip.grid(row=2, column=0, sticky="ew", padx=4, pady=(6, 2))
        self.preview_name_lbl.configure(text=active_item.path.name)
        meta_text = _format_meta(active_item)
        self.preview_meta_lbl.configure(text=self._tr("preview_sub", meta=meta_text))
        img = self._ctk_images.get(active_item.item_id)
        if img is not None:
            self.preview_thumb_lbl.configure(image=img, text="")
        else:
            self.preview_thumb_lbl.configure(image=None, text="🎬")

    def _play_active_file(self) -> None:
        active = self._resolve_active_item(self.controller.items.items)
        if active is None or not active.path.exists():
            return
        if hasattr(os, "startfile"):
            os.startfile(str(active.path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(active.path)])
        else:
            subprocess.Popen(["xdg-open", str(active.path)])

    # ---------- user actions ----------
    def _on_dropped_files(self, paths: list[Path]) -> None:
        if paths:
            self.controller.add_files(paths)
            self.render()
            if self._on_focus_change is not None:
                self._on_focus_change(paths[-1])

    def _on_toggle(self, path: Path) -> None:
        self.controller.items.toggle(path)
        items = self.controller.items.items
        sel_count = len(self.controller.items.selected())
        all_sel = bool(items and sel_count == len(items))
        self.btn_select_all.configure(
            text=self._tr("deselect_all") if all_sel else self._tr("select_all")
        )
        self.lbl_selected_count.configure(
            text=self._tr("selected_count", selected=sel_count, total=len(items))
        )

    def _toggle_select_all(self) -> None:
        if self._busy or self.controller.busy:
            return
        items = self.controller.items.items
        all_sel = bool(items and all(i.selected for i in items))
        self.controller.items.select_all(not all_sel)
        self.btn_select_all.configure(
            text=self._tr("deselect_all") if not all_sel else self._tr("select_all")
        )
        self.render()

    def _clear_selection(self) -> None:
        if self._busy or self.controller.busy:
            return
        self.controller.items.select_all(False)
        self.render()

    def _delete_selected(self) -> None:
        if self._busy or self.controller.busy:
            return
        self.controller.remove_selected()
        self.render()

    def _clear_all(self) -> None:
        if self._busy or self.controller.busy:
            return
        if not self.controller.items:
            return
        if messagebox.askyesno(self._tr("clear_all"), self._tr("clear_confirm")):
            self.controller.clear_queue()
            self._ctk_images.clear()
            self._thumb_requested.clear()
            if self._on_focus_change is not None:
                self._on_focus_change(None)
            self.render()

    def _clear_inputs(self) -> None:
        self._clear_all()

    def _retry_failed(self) -> None:
        if self._busy or self.controller.busy:
            return
        n = self.controller.items.reset_failed()
        if n > 0:
            self.render()
            self._on_start_patch_selected()

    def _browse_files(self) -> None:
        if self._busy or self.controller.busy:
            return
        files = filedialog.askopenfilenames(
            title="Select video files",
            filetypes=[
                ("Video files", "*.mp4;*.mov;*.m4v"),
                ("MP4 files", "*.mp4"),
                ("MOV files", "*.mov"),
                ("All files", "*.*"),
            ],
        )
        if files:
            paths = [Path(p) for p in files]
            self.controller.add_files(paths)
            self.render()
            if self._on_focus_change is not None:
                self._on_focus_change(paths[-1])

    def _browse_folder(self) -> None:
        if self._busy or self.controller.busy:
            return
        folder = filedialog.askdirectory(title="Select folder with video files")
        if folder:
            paths: list[Path] = []
            f_path = Path(folder)
            for root, _, filenames in os.walk(f_path):
                for name in filenames:
                    ext = Path(name).suffix.lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        paths.append(Path(root) / name)
            if paths:
                self.controller.add_files(paths)
                self.render()
                if self._on_focus_change is not None:
                    self._on_focus_change(paths[-1])
            else:
                msg = "No supported video files found in selected folder."
                messagebox.showinfo("No Videos", msg)

    def _toggle_player(self) -> None:
        self.player_switch.configure(text=self._tr("preview_player"))
        active = self._resolve_active_item(self.controller.items.items)
        self._update_preview_strip(active)

    # ---------- events & lazy context menu ----------
    def _bind_row_events(self, row: ctk.CTkFrame, path: Path) -> None:
        chk = getattr(row, "_chk", None)

        def on_left_click(_event: Any, p: Path = path) -> None:
            self._on_card_clicked(p)

        def on_right_click(event: Any, p: Path = path) -> None:
            self._popup_context_menu(event, p)

        def bind_tree(w: Any) -> None:
            if chk is not None and w is chk:
                w.bind("<Button-3>", on_right_click)
                return
            w.bind("<Button-1>", on_left_click)
            w.bind("<Button-3>", on_right_click)
            for child in w.winfo_children():
                bind_tree(child)

        bind_tree(row)

    def _popup_context_menu(self, event: Any, path: Path) -> None:
        from ..core.strategies import UI_PRESETS

        item = self.controller.items.get(path)
        if item is None:
            return

        menu = Menu(self, tearoff=0)
        menu.add_command(
            label=f"60 FPS ({self._tr('set_fps')})",
            command=lambda: self._set_item_override(item.path, timescale=60000),
        )
        menu.add_command(
            label=f"120 FPS ({self._tr('set_fps')})",
            command=lambda: self._set_item_override(item.path, timescale=120000),
        )

        preset_menu = Menu(menu, tearoff=0)
        for p_key, p_strat in UI_PRESETS.items():

            def _make_cmd(key: str) -> Callable[[], None]:
                return lambda: self._set_item_override(item.path, strategy=key)

            preset_menu.add_command(
                label=p_strat.label,
                command=_make_cmd(p_key),
            )
        menu.add_cascade(label=self._tr("set_strategy"), menu=preset_menu)

        menu.add_separator()
        menu.add_command(
            label=f"🔧 {self._tr('repair_for_mobile')}",
            command=lambda: self._repair_item_for_mobile(item.path),
        )
        menu.add_separator()
        menu.add_command(
            label=self._tr("open_containing_folder"),
            command=lambda: self._open_dir(item.path.parent),
        )
        if item.output is not None and item.output.exists():
            out_parent = item.output.parent
            menu.add_command(
                label=self._tr("open_output_file"),
                command=lambda: self._open_dir(out_parent),
            )
        menu.add_command(
            label=self._tr("copy_path"),
            command=lambda: self._copy_to_clip(str(item.path)),
        )
        menu.add_separator()
        menu.add_command(
            label=self._tr("move_up"),
            command=lambda: self._move_item(item.path, -1),
        )
        menu.add_command(
            label=self._tr("move_down"),
            command=lambda: self._move_item(item.path, 1),
        )
        menu.add_separator()
        menu.add_command(
            label=self._tr("delete_selected"),
            command=lambda: self._remove_item(item.path),
        )
        menu.add_command(
            label=self._tr("clear_inputs"),
            command=self._clear_inputs,
        )
        menu.post(event.x_root, event.y_root)

    def _set_item_override(
        self, path: Path, timescale: int | None = None, strategy: str | None = None
    ) -> None:
        item = self.controller.items.get(path)
        eff_ts = timescale if timescale is not None else (item.timescale if item else None)
        eff_st = strategy if strategy is not None else (item.strategy if item else None)
        self.controller.items.set_override(path, timescale=eff_ts, strategy=eff_st)
        self.render()
        if self._on_focus_change is not None:
            self._on_focus_change(path)

    def _repair_item_for_mobile(self, path: Path) -> None:
        self.controller.repair_file_for_mobile(path)

    def _move_item(self, path: Path, delta: int) -> None:
        items = self.controller.items.items
        for idx, i in enumerate(items):
            if i.path.resolve() == path.resolve():
                new_idx = max(0, min(idx + delta, len(items) - 1))
                self.controller.items.move(path, new_idx)
                self.render()
                break

    def _remove_item(self, path: Path) -> None:
        self.controller.items.remove(path)
        self.render()

    def _open_dir(self, directory: Path) -> None:
        if hasattr(os, "startfile"):
            os.startfile(str(directory))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(directory)], check=False)
        else:
            subprocess.run(["xdg-open", str(directory)], check=False)

    def _copy_to_clip(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)

    # ---------- theme update ----------
    def apply_theme(self, tokens: ThemeTokens) -> None:
        card_rad, ctrl_rad = self._radii()
        fsize = self._fsize()

        self.configure(corner_radius=card_rad, fg_color=tokens.bg)
        self.top_bar.configure(fg_color=tokens.bg)
        self.scroll.configure(fg_color=tokens.bg)
        self.btn_add_files.configure(
            text=f"＋ {self._tr('add_files_btn')}",
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        has_folder_ico = bool(self.btn_add_folder.cget("image"))
        folder_txt = (
            self._tr("add_folder_btn")
            if has_folder_ico
            else f"📁 {self._tr('add_folder_btn')}"
        )
        self.btn_add_folder.configure(
            text=folder_txt,
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.btn_retry_failed.configure(
            text=self._tr("retry_failed"),
            fg_color=STATUS_WARNING_BG,
            hover_color=tokens.surface_hover,
            text_color=STATUS_WARNING_TEXT,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.btn_select_all.configure(
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.btn_clear_selection.configure(
            text=self._tr("clear_selection"),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.btn_clear_all.configure(
            text=self._tr("clear_all"),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            text_color=tokens.text,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.bottom_divider.configure(fg_color=tokens.border)
        self.player_switch.configure(
            text=self._tr("preview_player"),
            text_color=tokens.text,
            progress_color=tokens.success,
            font=font_caption(fsize),
        )
        self.lbl_selected_count.configure(
            text_color=tokens.muted,
            font=font_caption(fsize),
        )
        self.btn_apply_selected.configure(
            text=self._tr("apply_selected"),
            fg_color=tokens.accent_light,
            hover_color=tokens.accent_glow,
            text_color=tokens.accent,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self.preview_strip.configure(
            corner_radius=card_rad,
            fg_color=tokens.surface_raised,
            border_color=tokens.border,
        )
        self.preview_thumb_lbl.configure(
            fg_color=tokens.surface,
            text_color=tokens.muted,
            font=font_caption(fsize),
        )
        self.preview_name_lbl.configure(
            text_color=tokens.text,
            font=font_body(bold=True, size_opt=fsize),
        )
        self.preview_meta_lbl.configure(
            text_color=tokens.muted,
            font=font_caption(fsize),
        )
        self.preview_play_btn.configure(
            text=self._tr("open_in_player"),
            fg_color=tokens.accent_light,
            hover_color=tokens.accent_glow,
            text_color=tokens.accent,
            corner_radius=ctrl_rad,
            font=font_caption(fsize),
        )
        self._row_sigs.clear()
        self.render()
