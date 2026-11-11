# Layouts — FPS Patcher Studio (Qt)

Main window: `QMainWindow` -> Root widget stacking Toolbar (48px) -> body row (QueueView flex + Inspector 300px) -> ConsolePanel (32/180). Settings is a modal dialog 920x640 (min 820x560) with a left rail and one scroll page per tab.

## Main window shell + toolbar (class decl, __init__, _build_shell, _build_toolbar)
Path: `src/fps_patcher/ui_qt/main_window.py` lines 95-302

```python
class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.controller = AppController(settings)
        self.theme_manager = ThemeManager(settings, self)
        self.theme: Theme = self.theme_manager.theme
        self.motion = MotionController(settings.reduce_motion, self.theme, self)

        self._last_output: Path | None = None
        self._watcher: FolderWatcher | None = None
        self._watch_inbox: queue.Queue[Path] = queue.Queue()
        self._watch_batch_active = False
        self._ff_init_thread: threading.Thread | None = None
        self._ff_state = "checking"
        self._ff_detail = ""
        self._update_info: Any = None
        self._update_prompted = False
        self._update_dialog: UpdateDialog | None = None
        self._pending_update_path: Path | None = None
        self._probe_running = False
        self._pending_logs: list[tuple[str, str]] = []
        self._latest_progress: ProgressEvent | None = None
        self._queue_dirty = False
        self._last_busy: bool | None = None
        self._last_can_patch: bool | None = None
        self._console_expanded = False
        self._tray: QSystemTrayIcon | None = None
        self._force_quit = False
        self._tray_notice_shown = False

        self._qt_settings = QSettings("FPSPatcherStudio", "QtUI")
        self._load_queue()

        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, self.theme)

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(self.theme.min_width, self.theme.min_height)
        self.resize(self.theme.window_width, self.theme.window_height)
        if settings.always_on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._restore_geometry()

        self._build_shell()
        self._build_shortcuts()
        self._connect_signals()
        self._build_tray_menu()
        self._sync_tray()

        self.bridge = ControllerBridge(self.controller, self)
        self._connect_bridge()
        self.theme_manager.changed.connect(self._on_theme_changed)

        for name, old, new in self.controller.items.migrated_overrides:
            self.console.append(
                f"[CONFIG] Queue item '{name}' preset migrated: '{old}' -> '{new}'",
                "INFO",
            )

        self._console_expanded = False
        self.console.set_expanded(False)
        self.queue_view.refresh()
        self._sync_focused_item()
        self._refresh_readiness()
        self._update_title_bar()

        self._cleanup_stale_preflight()
        self._init_ffmpeg()
        self._sync_watcher()
        self._sync_explorer_menu()
        self._sync_startup()
        self.controller.check_for_updates_background(__version__)

        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(_WATCH_DRAIN_MS)
        self._watch_timer.timeout.connect(self._drain_watch_inbox)
        self._watch_timer.start()

    # ------------------------------------------------------------------ shell
    def _build_shell(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_toolbar())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(
            self.theme.outer, self.theme.outer, self.theme.outer, self.theme.outer
        )
        body_layout.setSpacing(self.theme.spacing)

        self.queue_view = QueueView(
            self.controller, self.settings, self.theme_manager, body
        )
        self.inspector = Inspector(self.settings, self.theme_manager, body)
        self.inspector.setFixedWidth(self.theme.inspector_width)
        body_layout.addWidget(self.queue_view, 1)
        body_layout.addWidget(self.inspector, 0)
        outer.addWidget(body, 1)

        self.console = ConsolePanel(self.settings, self.theme_manager, root)
        self.console.set_animated(True)
        outer.addWidget(self.console, 0)

    def _build_toolbar(self) -> QWidget:
        theme = self.theme
        lang = self.settings.language
        toolbar = QWidget()
        toolbar.setObjectName("Toolbar")
        toolbar.setFixedHeight(theme.toolbar_height)

        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(theme.inner, 0, theme.inner, 0)
        layout.setSpacing(theme.spacing)

        self.brand_bar = QFrame(toolbar)
        self.brand_bar.setObjectName("BrandBar")
        self.brand_bar.setFixedSize(3, 18)
        self.brand_bar.setStyleSheet(
            f"background: {theme.color('accent')}; border-radius: 1px;"
        )
        layout.addWidget(self.brand_bar, 0, Qt.AlignmentFlag.AlignVCenter)

        self.title_label = QLabel(t("app_title", lang))
        self.title_label.setProperty("role", "title")
        layout.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.version_badge = QLabel(f"v{__version__}")
        self.version_badge.setProperty("role", "badge")
        layout.addWidget(self.version_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)

        self.ffmpeg_button = QPushButton()
        self.ffmpeg_button.setProperty("variant", "secondary")
        self.ffmpeg_button.setProperty("motionSkip", True)
        self.ffmpeg_button.setFixedHeight(theme.button_height)
        self.ffmpeg_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ffmpeg_button.clicked.connect(self._show_ffmpeg_menu)
        layout.addWidget(self.ffmpeg_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.forensic_button = text_button(
            t("forensic_btn", lang),
            theme,
            self._open_forensic,
            variant="ghost",
            height=theme.button_height,
        )
        layout.addWidget(self.forensic_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.history_button = text_button(
            t("history_btn", lang),
            theme,
            self._open_history,
            variant="ghost",
            height=theme.button_height,
        )
        layout.addWidget(self.history_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.output_button = text_button(
            t("open_output_btn", lang),
            theme,
            self._open_output,
            variant="ghost",
            height=theme.button_height,
        )
        layout.addWidget(self.output_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.update_button = text_button(
            "",
            theme,
            self._on_update_clicked,
            variant="primary",
            height=theme.button_height,
        )
        self.update_button.setVisible(False)
        layout.addWidget(self.update_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.theme_button = icon_button(
            "sun" if theme.is_dark else "moon",
            t("toggle_theme_tip", lang),
            theme,
            self._toggle_appearance,
        )
        layout.addWidget(self.theme_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.settings_button = icon_button(
            "settings",
            t("settings_btn", lang),
            theme,
            self._open_settings,
        )
        layout.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.forensic_button.setAccessibleName(t("forensic_btn", lang))
        self.history_button.setAccessibleName(t("history_btn", lang))
        self.output_button.setAccessibleName(t("open_output_btn", lang))
        self._set_ffmpeg_state("checking")
        return toolbar

    def _build_shortcuts(self) -> None:```

## Queue area structure (_build_ui)
Path: `src/fps_patcher/ui_qt/queue_view.py` lines 1306-1416

```python
    def _build_ui(self) -> None:
        theme = self._theme
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.outer)

        self.toolbar = QWidget(self)
        toolbar = self.toolbar
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(theme.outer)
        self.add_files_button = text_button(self.tr("add_files_btn"), theme, self._browse_files)
        self.add_folder_button = text_button(self.tr("add_folder_btn"), theme, self._browse_folder)
        self.add_folder_button.setIcon(get_icon("folder", theme.is_dark))
        self.add_folder_button.setIconSize(QSize(14, 14))
        self.retry_button = text_button(self.tr("retry_failed"), theme, self._retry_failed)
        self.retry_button.setVisible(False)
        self.select_all_button = text_button(
            self.tr("select_all"), theme, self._toggle_select_all, variant="ghost"
        )
        self.clear_selection_button = text_button(
            self.tr("clear_selection"),
            theme,
            self._clear_selection,
            variant="ghost",
        )
        self.clear_all_button = text_button(
            self.tr("clear_all"), theme, self._clear_all, variant="ghost"
        )
        for widget in (
            self.add_files_button,
            self.add_folder_button,
            self.retry_button,
            self.select_all_button,
            self.clear_selection_button,
            self.clear_all_button,
        ):
            bar.addWidget(widget)
        bar.addStretch(1)
        root.addWidget(toolbar)

        self.drop_card = DropCard(theme, getattr(self.settings, "language", "en"), self)
        self.drop_card.browse_requested.connect(self._browse_files)
        self.drop_card.folder_requested.connect(self._browse_folder)
        root.addWidget(self.drop_card, 1)

        self.summary_label = QLabel(self)
        self.summary_label.setProperty("role", "caption")
        self.summary_label.setContentsMargins(theme.inner, 0, 0, 0)
        self.summary_label.setFixedHeight(22)
        self.summary_label.setVisible(False)
        root.addWidget(self.summary_label)

        self.model = QueueModel(self)
        self.delegate = QueueDelegate(self)
        self.list_view = QListView(self)
        self.list_view.setObjectName("QueueViewList")
        self.list_view.setModel(self.model)
        self.list_view.setItemDelegate(self.delegate)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setMouseTracking(True)
        self.list_view.viewport().setMouseTracking(True)
        self.list_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.list_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_view.setFrameShape(QFrame.Shape.NoFrame)
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_view.setAccessibleDescription(
            ", ".join(
                self.tr(f"queue_{key}_action")
                for key in ("override", "forensic", "remove")
            )
        )
        self.list_view.setVisible(False)
        self.list_view.viewport().installEventFilter(self)
        self.list_view.customContextMenuRequested.connect(self._show_context_menu)
        root.addWidget(self.list_view, 1)

        self._divider = hairline(theme)
        root.addWidget(self._divider)

        self.footer = QWidget(self)
        footer = self.footer
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(theme.inner)
        self.preview_switch = Switch(theme, footer)
        self.preview_switch.set_reduce_motion(bool(self.settings.reduce_motion))
        self.preview_switch.setChecked(self._preview_on)
        self.preview_switch.toggled.connect(self._on_preview_toggled)
        foot.addWidget(self.preview_switch)
        self.preview_label = QLabel(self.tr("preview_player"), footer)
        self.preview_label.setProperty("role", "caption")
        foot.addWidget(self.preview_label)
        foot.addStretch(1)
        self.selected_count_label = QLabel(footer)
        self.selected_count_label.setProperty("role", "caption")
        foot.addWidget(self.selected_count_label)
        self.apply_button = text_button(
            self.tr("apply_selected"),
            theme,
            self.patch_requested.emit,
            variant="secondary",
            height=28,
        )
        foot.addWidget(self.apply_button)
        root.addWidget(footer)

    # ---------- state sync ----------```

## Inspector structure (_build)
Path: `src/fps_patcher/ui_qt/inspector.py` lines 146-454

```python
    def _build(self) -> None:
        theme = self._theme
        lang = self._lang()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.viewport().setStyleSheet("background: transparent;")
        root.addWidget(self._scroll, 1)

        body = QWidget()
        body.setObjectName("InspectorBody")
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(
            theme.outer, theme.outer, theme.outer, theme.outer
        )
        self._body_layout.setSpacing(theme.spacing)
        self._scroll.setWidget(body)

        # -- Target FPS ----------------------------------------------------
        self.target_group = CardGroup(t("target_fps", lang), theme)
        target_content = QWidget()
        target_layout = QVBoxLayout(target_content)
        target_layout.setContentsMargins(theme.inner, theme.inner, theme.inner, theme.inner)
        target_layout.setSpacing(theme.outer)
        self._target_layout = target_layout

        self.segments = SegmentedControl(self._segment_items(), theme)
        self.segments.setAccessibleName(t("target_fps", lang))
        self.segments.valueChanged.connect(self._segment_changed)
        target_layout.addWidget(self.segments)

        self.custom_row = QWidget()
        custom_layout = QVBoxLayout(self.custom_row)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(theme.outer)
        self.custom_label = QLabel(t("custom_fps_lbl", lang))
        self.custom_label.setProperty("role", "caption")
        custom_layout.addWidget(self.custom_label)
        self.custom_edit = QLineEdit()
        self.custom_edit.setFixedHeight(theme.entry_height)
        self.custom_edit.setAccessibleName(t("custom_fps_lbl", lang))
        self.custom_edit.setPlaceholderText(t("custom_fps_placeholder", lang))
        self.custom_edit.editingFinished.connect(self._commit_custom)
        custom_layout.addWidget(self.custom_edit)
        target_layout.addWidget(self.custom_row)
        self.custom_row.setVisible(False)
        self.custom_row.setMinimumHeight(0)
        self.custom_row.setMaximumHeight(0)

        self.target_group.body.addWidget(target_content)
        self._body_layout.addWidget(self.target_group)

        # -- Output --------------------------------------------------------
        self.output_group = CardGroup(t("output_lbl", lang), theme)

        self.timescale_field = QLabel()
        self.timescale_field.setProperty("role", "value")
        self.timescale_field.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.timescale_field.setAccessibleName(t("timescale_lbl", lang))
        self.timescale_row = self.output_group.add_row(
            t("timescale_lbl", lang), self.timescale_field
        )

        self.bitrate_field = QLabel("—")
        self.bitrate_field.setProperty("role", "value")
        self.bitrate_field.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.bitrate_field.setAccessibleName(t("bitrate_lbl", lang))
        self.bitrate_row = self.output_group.add_row(
            t("bitrate_lbl", lang), self.bitrate_field
        )

        self.strategy_combo = QComboBox()
        self.strategy_combo.setFixedHeight(theme.combo_height)
        self.strategy_combo.setFixedWidth(200)
        self.strategy_combo.setAccessibleName(t("strategy_lbl", lang))
        resolved_key, _ = migrate_strategy_name(str(self.settings.strategy))
        resolved_preset = UI_PRESETS.get(resolved_key)
        self._sync_preset_items(self.strategy_combo, resolved_preset)
        self._update_strategy_tip(resolved_key)
        self.strategy_combo.activated.connect(self._strategy_activated)
        self.strategy_row = self.output_group.add_row(
            t("strategy_lbl", lang), self.strategy_combo
        )

        self.profile_block = QWidget()
        profile_layout = QVBoxLayout(self.profile_block)
        profile_layout.setContentsMargins(theme.inner, theme.outer, theme.inner, theme.outer)
        profile_layout.setSpacing(theme.outer)
        self._profile_layout = profile_layout
        self.profile_label = QLabel(t("platform_profile_lbl", lang))
        self.profile_label.setProperty("role", "caption")
        profile_layout.addWidget(self.profile_label)
        self.profile_combo = QComboBox()
        self.profile_combo.setFixedHeight(theme.combo_height)
        self.profile_combo.setAccessibleName(t("platform_profile_lbl", lang))
        self.profile_combo.activated.connect(self._profile_activated)
        profile_layout.addWidget(self.profile_combo)
        self.output_group.body.addWidget(self.profile_block)
        self._populate_profiles()

        self.warn_row = QWidget()
        warn_layout = QVBoxLayout(self.warn_row)
        warn_layout.setContentsMargins(theme.inner, 0, theme.inner, theme.inner)
        self.warn_frame = QFrame()
        self.warn_frame.setObjectName("WarnCallout")
        frame_layout = QVBoxLayout(self.warn_frame)
        frame_layout.setContentsMargins(theme.inner, theme.outer, theme.inner, theme.outer)
        self._warn_layout = warn_layout
        self._warn_frame_layout = frame_layout
        self.warn_label = QLabel(t("bxd_pc_warn", lang))
        self.warn_label.setWordWrap(True)
        frame_layout.addWidget(self.warn_label)
        warn_layout.addWidget(self.warn_frame)
        self.warn_row.setVisible(False)
        self.output_group.body.addWidget(self.warn_row)
        self._body_layout.addWidget(self.output_group)

        # -- Readiness -----------------------------------------------------
        self.readiness_card = Card(theme)
        readiness_layout = QHBoxLayout()
        readiness_layout.setContentsMargins(theme.inner, theme.inner, theme.inner, theme.inner)
        readiness_layout.setSpacing(theme.outer)
        self._readiness_layout = readiness_layout
        self.readiness_label = QLabel(t("readiness_summary", lang))
        self.readiness_label.setProperty("role", "caption")
        self.readiness_label.setWordWrap(True)
        readiness_layout.addWidget(self.readiness_label, 1)
        self.info_btn = QPushButton()
        self.info_btn.setProperty("variant", "icon")
        self.info_btn.setIcon(get_icon("info", theme.is_dark))
        self.info_btn.setIconSize(QSize(14, 14))
        self.info_btn.setFixedSize(theme.icon_button_size, theme.icon_button_size)
        self.info_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.info_btn.setToolTip(t("readiness_tip", lang))
        self.info_btn.setAccessibleName(t("readiness_tip", lang))
        self.info_btn.clicked.connect(self._open_readiness)
        readiness_layout.addWidget(self.info_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.readiness_card.body.addLayout(readiness_layout)
        self._body_layout.addWidget(self.readiness_card)

        # -- One merged progress rail -------------------------------------
        self.progress_group = CardGroup(
            t("progress_idle", lang, index=0, total=0), theme
        )
        progress_content = QWidget()
        progress_layout = QVBoxLayout(progress_content)
        progress_layout.setContentsMargins(theme.inner, theme.inner, theme.inner, theme.inner)
        progress_layout.setSpacing(theme.outer)
        self._progress_layout = progress_layout
        self.percent_label = QLabel("0%")
        self.percent_label.setProperty("role", "muted")
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        progress_layout.addWidget(self.percent_label)
        self.progress_bar = MotionProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(theme.progress_height)
        self.progress_bar.setAccessibleName(t("progress_idle", lang, index=0, total=0))
        progress_layout.addWidget(self.progress_bar)
        self.progress_group.body.addWidget(progress_content)
        self._body_layout.addWidget(self.progress_group)

        # -- Per-item override ---------------------------------------------
        self.override_group = CardGroup(t("inspector_override_title", lang), theme)
        override_content = QWidget()
        override_layout = QVBoxLayout(override_content)
        override_layout.setContentsMargins(theme.inner, theme.inner, theme.inner, theme.inner)
        override_layout.setSpacing(theme.outer)
        self._override_layout = override_layout

        self.override_empty = QLabel(t("inspector_override_no_selection", lang))
        self.override_empty.setProperty("role", "muted")
        self.override_empty.setWordWrap(True)
        override_layout.addWidget(self.override_empty)

        self.override_form = QWidget()
        self._override_form_layout = QVBoxLayout(self.override_form)
        self._override_form_layout.setContentsMargins(0, 0, 0, 0)
        self._override_form_layout.setSpacing(theme.outer)

        switch_row = QWidget()
        switch_layout = QHBoxLayout(switch_row)
        switch_layout.setContentsMargins(0, 0, 0, 0)
        switch_layout.setSpacing(theme.outer)
        self.override_enable_label = QLabel(t("inspector_override_enable", lang))
        self.override_enable_label.setProperty("role", "caption")
        switch_layout.addWidget(self.override_enable_label, 1)
        self.override_switch = Switch(theme)
        self.override_switch.set_reduce_motion(bool(self.settings.reduce_motion))
        self.override_switch.setAccessibleName(t("inspector_override_enable", lang))
        self.override_switch.toggled.connect(self._override_toggled)
        switch_layout.addWidget(self.override_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        self._override_form_layout.addWidget(switch_row)

        self.override_fps_label = QLabel(t("inspector_override_fps", lang))
        self.override_fps_label.setProperty("role", "caption")
        self._override_form_layout.addWidget(self.override_fps_label)
        self.override_fps_edit = QLineEdit()
        self.override_fps_edit.setFixedHeight(theme.entry_height)
        self.override_fps_edit.setAccessibleName(t("inspector_override_fps", lang))
        self.override_fps_edit.setPlaceholderText(t("inspector_override_fps", lang))
        self._override_form_layout.addWidget(self.override_fps_edit)

        self.override_preset_label = QLabel(t("inspector_override_preset", lang))
        self.override_preset_label.setProperty("role", "caption")
        self._override_form_layout.addWidget(self.override_preset_label)
        self.override_preset_combo = QComboBox()
        self.override_preset_combo.setFixedHeight(theme.combo_height)
        self.override_preset_combo.setAccessibleName(t("inspector_override_preset", lang))
        self._sync_preset_items(self.override_preset_combo, None)
        self._override_form_layout.addWidget(self.override_preset_combo)

        self.override_profile_label = QLabel(t("inspector_override_profile", lang))
        self.override_profile_label.setProperty("role", "caption")
        self._override_form_layout.addWidget(self.override_profile_label)
        self.override_profile_combo = QComboBox()
        self.override_profile_combo.setFixedHeight(theme.combo_height)
        self.override_profile_combo.setAccessibleName(t("inspector_override_profile", lang))
        self._override_form_layout.addWidget(self.override_profile_combo)
        self._populate_override_profiles()

        override_buttons = QWidget()
        override_button_row = QHBoxLayout(override_buttons)
        override_button_row.setContentsMargins(0, 0, 0, 0)
        override_button_row.setSpacing(theme.outer)
        self.override_apply_btn = text_button(
            t("override_apply_btn", lang),
            theme,
            self._apply_override,
            height=theme.button_height,
        )
        self.override_clear_btn = text_button(
            t("override_clear_btn", lang),
            theme,
            self._clear_override,
            height=theme.button_height,
        )
        override_button_row.addWidget(self.override_apply_btn)
        override_button_row.addWidget(self.override_clear_btn)
        override_button_row.addStretch(1)
        self._override_form_layout.addWidget(override_buttons)

        self.override_state = QLabel(t("inspector_override_inactive", lang))
        self.override_state.setProperty("role", "caption")
        self._override_form_layout.addWidget(self.override_state)
        self.override_hint = QLabel(t("inspector_override_hint", lang))
        self.override_hint.setProperty("role", "muted")
        self.override_hint.setWordWrap(True)
        self._override_form_layout.addWidget(self.override_hint)

        self.override_form.setVisible(False)
        override_layout.addWidget(self.override_form)
        self.override_group.body.addWidget(override_content)
        self._body_layout.addWidget(self.override_group)
        self._body_layout.addStretch(1)

        # -- Pinned footer -------------------------------------------------
        footer = QWidget()
        footer.setObjectName("InspectorFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(theme.outer, theme.spacing, theme.outer, theme.outer)
        footer_layout.setSpacing(theme.spacing)
        self._footer_layout = footer_layout
        self.start_btn = text_button(
            t("start_patch", lang),
            theme,
            self._start_clicked,
            variant="primary",
            height=theme.primary_height,
        )
        self.cancel_btn = text_button(
            t("cancel_btn", lang),
            theme,
            self.cancel_requested.emit,
            variant="secondary",
            height=theme.secondary_height,
        )
        self.cancel_btn.setEnabled(False)
        self.vfr_badge = ConsequenceBadge(
            t("inspector_vfr_banner", lang), "warning", theme
        )
        self.vfr_badge.setVisible(False)
        self.lossless_btn = text_button(
            t("inspector_use_lossless", lang),
            theme,
            self._disable_vfr,
            variant="ghost",
            height=28,
        )
        self.lossless_btn.setVisible(False)
        footer_layout.addWidget(self.vfr_badge)
        footer_layout.addWidget(self.lossless_btn)
        footer_layout.addWidget(self.start_btn)
        footer_layout.addWidget(self.cancel_btn)
        root.addWidget(footer)

    # ------------------------------------------------------------------ theme```

## Console panel structure (_build)
Path: `src/fps_patcher/ui_qt/console.py` lines 105-179

```python
    def _build(self) -> None:
        theme = self._theme
        lang = self._lang()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = QWidget(self)
        self._header.setObjectName("ConsoleHeader")
        self._header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._header.setFixedHeight(max(1, theme.console_collapsed_height - 1))
        self._header_layout = QHBoxLayout(self._header)
        self._header_layout.setContentsMargins(theme.inner, 0, theme.outer, 0)
        self._header_layout.setSpacing(theme.outer)
        root.addWidget(self._header)

        title = t("activity_console", lang)
        self._chevron = icon_button(
            "chevron_right",
            title,
            theme,
            self.toggle,
            accessible_name=title,
            parent=self._header,
        )
        self._chevron.setIcon(get_icon("chevron_right", theme.is_dark))
        self._header_layout.addWidget(self._chevron, 0, Qt.AlignmentFlag.AlignVCenter)

        self._title = QLabel(title, self._header)
        self._title.setProperty("role", "title")
        self._header_layout.addWidget(self._title, 0, Qt.AlignmentFlag.AlignVCenter)

        self._count = QLabel(self._format_line_count(0), self._header)
        self._count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._header_layout.addWidget(self._count, 0, Qt.AlignmentFlag.AlignVCenter)

        self._latest = ElidedLabel("", self._header)
        self._latest.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._header_layout.addWidget(self._latest, 1, Qt.AlignmentFlag.AlignVCenter)

        self._more = icon_button(
            "more",
            t("more_actions", lang),
            theme,
            self._show_menu,
            accessible_name=t("more_actions", lang),
            parent=self._header,
        )
        self._more.setIcon(get_icon("more", theme.is_dark))
        self._header_layout.addWidget(self._more, 0, Qt.AlignmentFlag.AlignVCenter)

        self.detail = QWidget(self)
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(
            theme.inner, theme.outer, theme.inner, theme.outer
        )
        detail_layout.setSpacing(0)

        self.editor = QPlainTextEdit(self.detail)
        self.editor.setObjectName("ConsoleLog")
        self.editor.setReadOnly(True)
        self.editor.setUndoRedoEnabled(False)
        self.editor.setFrameShape(QFrame.Shape.NoFrame)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setMaximumBlockCount(self._max_lines())
        self.editor.setAccessibleName(title)
        detail_layout.addWidget(self.editor)
        root.addWidget(self.detail, 1)

        self._apply_expanded(False)

    # ---------- settings helpers ----------```
