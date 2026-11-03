"""Job-history dialog: inspect recent patches and roll one back from its backup."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..app.controller import AppController
from ..config import Settings
from ..core.errors import PatchError
from ..core.job_history import JobRecord, load_history
from ..ui.strings import t
from .theme import ThemeManager

_COLUMNS = (
    "history_time",
    "history_source",
    "history_output",
    "history_backup",
    "history_status",
)
_HISTORY_LIMIT = 100


class HistoryDialog(QDialog):
    """Modal list of recent patch jobs with one-click backup rollback."""

    def __init__(
        self,
        settings: Settings,
        theme_manager: ThemeManager,
        controller: AppController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.controller = controller
        self._records: list[JobRecord] = []

        self.setModal(True)
        self.setWindowTitle(t("history_title", settings.language))
        self.resize(820, 460)
        self.setMinimumSize(640, 340)

        theme = theme_manager.theme
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.outer, theme.outer, theme.outer, theme.outer)
        outer.setSpacing(theme.spacing)

        self.table = QTableWidget(0, len(_COLUMNS), self)
        self.table.setObjectName("HistoryTable")
        self.table.setHorizontalHeaderLabels(
            [t(key, settings.language) for key in _COLUMNS]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setStyleSheet(
            "QTableWidget {"
            f"background: {theme.color('surface')};"
            f"border: 1px solid {theme.color('border')};"
            f"border-radius: {theme.card_radius}px;"
            "}"
            "QHeaderView::section {"
            f"background: {theme.color('surface_raised')};"
            f"color: {theme.color('text2')};"
            f"border: none; border-bottom: 1px solid {theme.color('border')};"
            "padding: 4px;"
            "}"
        )
        self.table.itemSelectionChanged.connect(self._sync_rollback)
        outer.addWidget(self.table, 1)

        self.empty_label = QLabel(t("history_empty", settings.language), self)
        self.empty_label.setProperty("role", "muted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        outer.addWidget(self.empty_label, 1)

        footer = QWidget(self)
        row = QHBoxLayout(footer)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.spacing)

        self.rollback_button = QPushButton(t("history_rollback", settings.language))
        self.rollback_button.setProperty("variant", "primary")
        self.rollback_button.setMinimumHeight(theme.primary_height)
        self.rollback_button.clicked.connect(self._rollback)

        self.refresh_button = QPushButton(t("history_refresh", settings.language))
        self.refresh_button.setMinimumHeight(theme.secondary_height)
        self.refresh_button.clicked.connect(self.refresh)

        self.close_button = QPushButton(t("history_close", settings.language))
        self.close_button.setMinimumHeight(theme.secondary_height)
        self.close_button.clicked.connect(self.accept)

        for button in (self.rollback_button, self.refresh_button, self.close_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(button.text())
            button.setToolTip(button.text())

        row.addWidget(self.rollback_button)
        row.addStretch(1)
        row.addWidget(self.refresh_button)
        row.addWidget(self.close_button)
        outer.addWidget(footer)

        self.refresh()

    def refresh(self) -> None:
        """Reload the newest records and rebuild the table."""
        lang = self.settings.language
        records: list[JobRecord]
        try:
            records = load_history(limit=_HISTORY_LIMIT)
        except Exception:
            records = []
        self._records = records

        self.table.setRowCount(0)
        for record in records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = (
                (record.timestamp, record.timestamp),
                (Path(record.src).name, record.src),
                (Path(record.output).name, record.output),
                ("Yes" if record.backup else "No", record.backup or ""),
                (
                    t(
                        "history_rolled_back" if record.rolled_back else "history_available",
                        lang,
                    ),
                    "",
                ),
            )
            for column, (text, tip) in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                if tip:
                    item.setToolTip(tip)
                self.table.setItem(row, column, item)

        empty = not records
        self.table.setVisible(not empty)
        self.empty_label.setVisible(empty)
        self._sync_rollback()

    def _selected_record(self) -> JobRecord | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._records):
            return self._records[row]
        return None

    def _sync_rollback(self) -> None:
        record = self._selected_record()
        self.rollback_button.setEnabled(
            record is not None and not record.rolled_back and not self.controller.busy
        )

    def _rollback(self) -> None:
        record = self._selected_record()
        if record is None or record.rolled_back or self.controller.busy:
            return
        lang = self.settings.language
        title = t("history_title", lang)
        answer = QMessageBox.question(
            self, title, t("history_rollback_confirm", lang)
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            restored = self.controller.undo_job(record.job_id)
        except PatchError as exc:
            QMessageBox.critical(
                self, title, t("history_rollback_failed", lang, error=str(exc))
            )
        else:
            QMessageBox.information(
                self,
                title,
                t("history_rollback_done", lang, path=restored.output),
            )
            self.refresh()
