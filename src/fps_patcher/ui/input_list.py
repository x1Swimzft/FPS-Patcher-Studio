"""Input list widget displaying items in InputQueue with modern cards, badges, and controls."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from tkinter import Menu, filedialog, messagebox
from typing import Any

import customtkinter as ctk

from ..app.controller import AppController
from ..app.queue_model import QueueItem
from ..core.models import SUPPORTED_EXTENSIONS
from .strings import t
from .theme import (
    RADIUS_CARD,
    RADIUS_CONTROL,
    RADIUS_PILL,
    STATUS_DANGER_TEXT,
    STATUS_EXPERIMENTAL_BG,
    STATUS_MUTED_BG,
    STATUS_MUTED_TEXT,
    STATUS_SUCCESS_BG,
    STATUS_SUCCESS_TEXT,
    STATUS_WARNING_BG,
    STATUS_WARNING_TEXT,
    ThemeTokens,
    font_body,
    font_caption,
    font_mono,
    font_section,
    get_theme_manager,
)
from .thumbnails import request_thumbnail


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
        self._theme_mgr = get_theme_manager(self.settings)
        tokens = self._theme_mgr.tokens

        super().__init__(
            master,
            corner_radius=RADIUS_CARD,
            fg_color=tokens.surface,
            border_width=1,
            border_color=tokens.border,
        )
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._row_widgets: dict[str, ctk.CTkFrame] = {}
        self._ctk_images: dict[str, ctk.CTkImage] = {}

        self._build_top_toolbar()
        self._build_scrollable_area()
        self._build_bottom_toolbar()

        self._theme_mgr.subscribe(self.apply_theme)

    def _tr(self, key: str, **kwargs: object) -> str:
        return t(key, self.settings.language, **kwargs)

    # ---------- top toolbar ----------
    def _build_top_toolbar(self) -> None:
        tokens = self._theme_mgr.tokens
        self.top_bar = ctk.CTkFrame(self, fg_color="transparent", height=38)
        self.top_bar.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
        self.top_bar.grid_columnconfigure(2, weight=1)

        # Left label: INPUT FILE / FOLDER
        self.lbl_title = ctk.CTkLabel(
            self.top_bar,
            text=self._tr("input_file_folder"),
            font=font_section(),
            text_color=tokens.text2,
        )
        self.lbl_title.grid(row=0, column=0, sticky="w", padx=(4, 12))

        # Select All button
        self.btn_select_all = ctk.CTkButton(
            self.top_bar,
            text=self._tr("select_all"),
            height=28,
            width=80,
            corner_radius=RADIUS_CONTROL,
            font=font_caption(),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.text,
            command=self._toggle_select_all,
        )
        self.btn_select_all.grid(row=0, column=1, sticky="w", padx=4)

        # Delete Selected button
        self.btn_del_selected = ctk.CTkButton(
            self.top_bar,
            text=self._tr("delete_selected"),
            height=28,
            width=95,
            corner_radius=RADIUS_CONTROL,
            font=font_caption(),
            fg_color="transparent",
            hover_color=tokens.surface_raised,
            border_width=1,
            border_color=tokens.border,
            text_color=STATUS_DANGER_TEXT,
            command=self._delete_selected,
        )
        self.btn_del_selected.grid(row=0, column=2, sticky="w", padx=4)

        # Top Right Actions: Intro & Tutorial
        right_box = ctk.CTkFrame(self.top_bar, fg_color="transparent")
        right_box.grid(row=0, column=3, sticky="e", padx=(0, 4))

        self.btn_add_files = ctk.CTkButton(
            right_box,
            text=self._tr("add_files_btn"),
            height=28,
            width=80,
            corner_radius=RADIUS_CONTROL,
            font=font_caption(),
            fg_color=tokens.accent,
            hover_color=tokens.accent_hover,
            text_color="#FFFFFF",
            command=self._browse_files,
        )
        self.btn_add_files.pack(side="left", padx=4)

        self.btn_add_folder = ctk.CTkButton(
            right_box,
            text=self._tr("add_folder_btn"),
            height=28,
            width=85,
            corner_radius=RADIUS_CONTROL,
            font=font_caption(),
            fg_color=tokens.surface_raised,
            hover_color=tokens.surface_hover,
            border_width=1,
            border_color=tokens.border,
            text_color=tokens.text,
            command=self._browse_folder,
        )
        self.btn_add_folder.pack(side="left", padx=4)

    # ---------- scrollable list ----------
    def _build_scrollable_area(self) -> None:
        tokens = self._theme_mgr.tokens
        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=tokens.bg,
            corner_radius=RADIUS_CONTROL,
            border_width=1,
            border_color=tokens.border,
        )
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        self.scroll.grid_columnconfigure(0, weight=1)

        # Empty state message
        self.empty_label = ctk.CTkLabel(
            self.scroll,
            text=self._tr("drop_title") + "\n" + self._tr("drop_sub"),
            font=font_body(),
            text_color=tokens.muted,
        )
        self.empty_label.pack(pady=40)

    # ---------- bottom toolbar ----------
    def _build_bottom_toolbar(self) -> None:
        tokens = self._theme_mgr.tokens
        self.bottom_bar = ctk.CTkFrame(self, fg_color="transparent", height=38)
        self.bottom_bar.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 10))
        self.bottom_bar.grid_columnconfigure(1, weight=1)

        # Bottom Left: Player Off Toggle
        self.player_switch = ctk.CTkSwitch(
            self.bottom_bar,
            text=self._tr("player_off"),
            font=font_caption(),
            text_color=tokens.text2,
            progress_color=tokens.accent,
            command=self._toggle_player,
        )
        self.player_switch.grid(row=0, column=0, sticky="w", padx=4)

        # Bottom Right: Retry Failed, Clear Inputs, Apply Selected
        right_box = ctk.CTkFrame(self.bottom_bar, fg_color="transparent")
        right_box.grid(row=0, column=2, sticky="e", padx=(0, 4))

        self.btn_retry_failed = ctk.CTkButton(
            right_box,
            text=self._tr("retry_failed"),
            height=30,
            corner_radius=RADIUS_CONTROL,
            font=font_caption(),
            fg_color="transparent",
            hover_color=tokens.surface_raised,
            border_width=1,
            border_color=tokens.border,
            text_color=STATUS_WARNING_TEXT,
            command=self._retry_failed,
        )
        self.btn_retry_failed.pack(side="left", padx=4)

        self.btn_clear_inputs = ctk.CTkButton(
            right_box,
            text=self._tr("clear_inputs"),
            height=30,
            corner_radius=RADIUS_CONTROL,
            font=font_caption(),
            fg_color="transparent",
            hover_color=tokens.surface_raised,
            border_width=1,
            border_color=tokens.border,
            text_color=STATUS_DANGER_TEXT,
            command=self._clear_inputs,
        )
        self.btn_clear_inputs.pack(side="left", padx=4)

        self.btn_apply_selected = ctk.CTkButton(
            right_box,
            text=self._tr("apply_selected"),
            height=30,
            corner_radius=RADIUS_CONTROL,
            font=font_body(bold=True),
            fg_color=tokens.accent,
            hover_color=tokens.accent_hover,
            text_color="#FFFFFF",
            command=self._on_start_patch_selected,
        )
        self.btn_apply_selected.pack(side="left", padx=4)

    # ---------- render queue ----------
    def render(self) -> None:
        """Synchronize UI rows with controller.items (InputQueue)."""
        items = self.controller.items.items

        if not items:
            for w in self._row_widgets.values():
                w.destroy()
            self._row_widgets.clear()
            self.empty_label.pack(pady=40)
            return

        self.empty_label.pack_forget()
        all_sel = bool(items and all(i.selected for i in items))
        self.btn_select_all.configure(
            text=self._tr("deselect_all") if all_sel else self._tr("select_all")
        )
        current_ids = {i.item_id for i in items}

        # Remove deleted rows
        for i_id in list(self._row_widgets.keys()):
            if i_id not in current_ids:
                self._row_widgets[i_id].destroy()
                del self._row_widgets[i_id]

        tokens = self._theme_mgr.tokens

        # Render or update rows
        for _idx, item in enumerate(items):
            if item.item_id in self._row_widgets:
                row_frame = self._row_widgets[item.item_id]
                self._update_row_content(row_frame, item, tokens)
            else:
                row_frame = self._create_row_frame(item, tokens)
                self._row_widgets[item.item_id] = row_frame

            row_frame.pack(fill="x", pady=2, padx=2)

    def _create_row_frame(self, item: QueueItem, tokens: ThemeTokens) -> ctk.CTkFrame:
        row = ctk.CTkFrame(
            self.scroll,
            height=46,
            corner_radius=RADIUS_CONTROL,
            fg_color=tokens.surface_raised,
            border_width=1,
            border_color=tokens.border,
        )
        row.grid_columnconfigure(2, weight=1)

        # 1. Checkbox
        chk = ctk.CTkCheckBox(
            row,
            text="",
            width=20,
            corner_radius=4,
            border_width=1,
            fg_color=tokens.accent,
            command=lambda p=item.path: self._on_toggle(p),
        )
        chk.grid(row=0, column=0, padx=(10, 6), pady=6)
        if item.selected:
            chk.select()
        else:
            chk.deselect()
        row._chk = chk

        # 2. Thumbnail
        thumb_lbl = ctk.CTkLabel(
            row,
            text="🎬",
            width=42,
            height=32,
            corner_radius=4,
            fg_color=tokens.bg,
            font=font_caption(),
        )
        thumb_lbl.grid(row=0, column=1, padx=(0, 8), pady=6)
        row._thumb = thumb_lbl

        # Request thumbnail in background
        ff_exe = self.controller.ffmpeg.ffmpeg if self.controller.ffmpeg else None

        def _on_thumb(
            img: Any | None, tlbl: ctk.CTkLabel = thumb_lbl, i_id: str = item.item_id
        ) -> None:
            self._on_thumb_ready(tlbl, img, i_id)

        request_thumbnail(
            item.path,
            ff_exe,
            (42, 32),
            _on_thumb,
        )

        # 3. Path & Error / Overrides Box
        center_box = ctk.CTkFrame(row, fg_color="transparent")
        center_box.grid(row=0, column=2, sticky="w", padx=(0, 8), pady=4)

        path_text = item.path.name
        lbl_path = ctk.CTkLabel(
            center_box,
            text=path_text,
            font=font_body(bold=True),
            text_color=tokens.text,
            anchor="w",
        )
        lbl_path.pack(anchor="w")
        row._lbl_path = lbl_path

        sub_info = str(item.path.parent)
        if item.error:
            sub_info = f"Error: {item.error}"
        lbl_sub = ctk.CTkLabel(
            center_box,
            text=sub_info,
            font=font_caption(),
            text_color=STATUS_DANGER_TEXT if item.error else tokens.muted,
            anchor="w",
        )
        lbl_sub.pack(anchor="w")
        row._lbl_sub = lbl_sub

        # 4. Badges Container
        badges_box = ctk.CTkFrame(row, fg_color="transparent")
        badges_box.grid(row=0, column=3, sticky="e", padx=(0, 8), pady=6)

        # Resolution badge
        res_str = f"{item.info.width}x{item.info.height}" if item.info else "—"
        res_badge = ctk.CTkLabel(
            badges_box,
            text=res_str,
            font=font_caption(),
            fg_color=tokens.bg,
            text_color=tokens.text2,
            corner_radius=RADIUS_PILL,
            padx=8,
            height=22,
        )
        res_badge.pack(side="left", padx=3)
        row._res_badge = res_badge

        # FPS badge
        fps_str = f"{item.info.fps:.3f} fps" if item.info else "—"
        fps_badge = ctk.CTkLabel(
            badges_box,
            text=fps_str,
            font=font_caption(),
            fg_color=tokens.bg,
            text_color=tokens.text2,
            corner_radius=RADIUS_PILL,
            padx=8,
            height=22,
        )
        fps_badge.pack(side="left", padx=3)
        row._fps_badge = fps_badge

        # Status badge
        status_badge = ctk.CTkLabel(
            badges_box,
            text=self._tr(f"status_{item.status}"),
            font=font_caption(),
            corner_radius=RADIUS_PILL,
            padx=8,
            height=22,
            **self._status_style(item.status),
        )
        status_badge.pack(side="left", padx=3)
        row._status_badge = status_badge

        # 5. Short ID
        id_lbl = ctk.CTkLabel(
            row,
            text=item.item_id,
            font=font_mono(),
            text_color=tokens.muted,
            width=80,
            anchor="e",
        )
        id_lbl.grid(row=0, column=4, padx=(0, 12), pady=6)

        # Right click context menu
        self._bind_context_menu(row, item)
        return row

    def _update_row_content(
        self, row: ctk.CTkFrame, item: QueueItem, tokens: ThemeTokens
    ) -> None:
        chk_w = getattr(row, "_chk", None)
        if chk_w:
            if item.selected:
                chk_w.select()
            else:
                chk_w.deselect()

        sub_w = getattr(row, "_lbl_sub", None)
        if sub_w:
            sub_info = str(item.path.parent)
            if item.error:
                sub_info = f"Error: {item.error}"
            sub_w.configure(
                text=sub_info,
                text_color=STATUS_DANGER_TEXT if item.error else tokens.muted,
            )

        res_w = getattr(row, "_res_badge", None)
        if res_w and item.info:
            res_w.configure(text=f"{item.info.width}x{item.info.height}")

        fps_w = getattr(row, "_fps_badge", None)
        if fps_w and item.info:
            fps_w.configure(text=f"{item.info.fps:.3f} fps")

        status_w = getattr(row, "_status_badge", None)
        if status_w:
            status_w.configure(
                text=self._tr(f"status_{item.status}"),
                **self._status_style(item.status),
            )

    def _status_style(self, status: str) -> dict[str, Any]:
        if status == "ready":
            return {"fg_color": STATUS_SUCCESS_BG, "text_color": STATUS_SUCCESS_TEXT}
        if status == "done":
            return {"fg_color": STATUS_SUCCESS_BG, "text_color": STATUS_SUCCESS_TEXT}
        if status == "failed":
            return {"fg_color": STATUS_EXPERIMENTAL_BG, "text_color": STATUS_DANGER_TEXT}
        if status == "patching":
            return {"fg_color": STATUS_WARNING_BG, "text_color": STATUS_WARNING_TEXT}
        if status == "probing":
            return {"fg_color": STATUS_MUTED_BG, "text_color": STATUS_MUTED_TEXT}
        return {"fg_color": STATUS_MUTED_BG, "text_color": STATUS_MUTED_TEXT}

    def _on_thumb_ready(self, label: ctk.CTkLabel, img: Any, item_id: str) -> None:
        if img is None:
            return

        def update_ui() -> None:
            try:
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(42, 32))
                self._ctk_images[item_id] = ctk_img
                label.configure(image=ctk_img, text="")
            except Exception:
                pass

        self.after(0, update_ui)

    # ---------- user actions ----------
    def _on_toggle(self, path: Path) -> None:
        self.controller.items.toggle(path)
        items = self.controller.items.items
        all_sel = bool(items and all(i.selected for i in items))
        self.btn_select_all.configure(
            text=self._tr("deselect_all") if all_sel else self._tr("select_all")
        )

    def _toggle_select_all(self) -> None:
        items = self.controller.items.items
        all_sel = bool(items and all(i.selected for i in items))
        self.controller.items.select_all(not all_sel)
        self.btn_select_all.configure(
            text=self._tr("deselect_all") if not all_sel else self._tr("select_all")
        )
        self.render()

    def _delete_selected(self) -> None:
        self.controller.remove_selected()
        self.render()

    def _clear_inputs(self) -> None:
        if not self.controller.items:
            return
        if messagebox.askyesno(self._tr("clear_inputs"), self._tr("clear_confirm")):
            self.controller.clear_queue()
            self.render()

    def _retry_failed(self) -> None:
        n = self.controller.items.reset_failed()
        if n > 0:
            self.render()
            self._on_start_patch_selected()

    def _browse_files(self) -> None:
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

    def _browse_folder(self) -> None:
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
            else:
                msg = "No supported video files found in selected folder."
                messagebox.showinfo("No Videos", msg)

    def _toggle_player(self) -> None:
        is_on = bool(self.player_switch.get())
        txt = self._tr("player_on") if is_on else self._tr("player_off")
        self.player_switch.configure(text=txt)

    # ---------- context menu ----------
    def _bind_context_menu(self, widget: ctk.CTkFrame, item: QueueItem) -> None:
        from ..core.strategies import UI_PRESETS

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

        def popup(event: Any) -> None:
            menu.post(event.x_root, event.y_root)

        widget.bind("<Button-3>", popup)
        for child in widget.winfo_children():
            child.bind("<Button-3>", popup)

    def _set_item_override(
        self, path: Path, timescale: int | None = None, strategy: str | None = None
    ) -> None:
        item = self.controller.items.get(path)
        eff_ts = timescale if timescale is not None else (item.timescale if item else None)
        eff_st = strategy if strategy is not None else (item.strategy if item else None)
        self.controller.items.set_override(path, timescale=eff_ts, strategy=eff_st)
        self.render()

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
        else:
            subprocess.run(["xdg-open", str(directory)])

    def _copy_to_clip(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)

    # ---------- theme update ----------
    def apply_theme(self, tokens: ThemeTokens) -> None:
        self.configure(fg_color=tokens.surface, border_color=tokens.border)
        self.lbl_title.configure(text_color=tokens.text2)
        self.scroll.configure(fg_color=tokens.bg, border_color=tokens.border)
        self.empty_label.configure(text_color=tokens.muted)
        self.btn_select_all.configure(
            fg_color=tokens.surface_raised,
            border_color=tokens.border,
            text_color=tokens.text,
        )
        self.btn_add_files.configure(fg_color=tokens.accent, hover_color=tokens.accent_hover)
        self.btn_add_folder.configure(
            fg_color=tokens.surface_raised,
            border_color=tokens.border,
            text_color=tokens.text,
        )
        self.btn_apply_selected.configure(fg_color=tokens.accent, hover_color=tokens.accent_hover)
        self.render()
