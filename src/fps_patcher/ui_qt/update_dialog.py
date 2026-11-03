"""In-app update dialog: release notes, download progress, skip and cancel."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings
from ..core.updater import detect_install_mode
from ..ui.strings import t


class UpdateDialog(QDialog):
    """Show release notes and drive one update download."""

    update_requested = Signal()
    skip_requested = Signal()
    cancel_requested = Signal()

    def __init__(
        self, info: Any, settings: Settings, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.info = info
        self.settings = settings
        self._downloading = False
        lang = settings.language

        self.setWindowTitle(t("update_dialog_title", lang))
        self.setMinimumWidth(520)
        self.resize(560, 460)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        header = QFrame()
        header.setObjectName("Card")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(4)

        self.title_label = QLabel(t("update_dialog_title", lang))
        self.version_label = QLabel(f"v{getattr(info, 'version', '')}")
        mode_key = (
            "update_mode_installed"
            if detect_install_mode() == "installed"
            else "update_mode_portable"
        )
        self.mode_label = QLabel(f"{t('update_mode_label', lang)}: {t(mode_key, lang)}")
        header_layout.addWidget(self.title_label)
        header_layout.addWidget(self.version_label)
        header_layout.addWidget(self.mode_label)
        outer.addWidget(header)

        self.notes = QPlainTextEdit()
        self.notes.setObjectName("ConsoleLog")
        self.notes.setReadOnly(True)
        self.notes.setPlainText(str(getattr(info, "notes", "") or ""))
        self.notes.setMinimumHeight(180)
        outer.addWidget(self.notes, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        outer.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setObjectName("StatusLabel")
        outer.addWidget(self.status_label)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.update_button = QPushButton(t("update_now_btn", lang))
        self.update_button.setProperty("variant", "primary")
        self.update_button.clicked.connect(self._request_update)
        self.skip_button = QPushButton(t("update_skip_btn", lang))
        self.skip_button.clicked.connect(lambda: self.skip_requested.emit())
        self.cancel_button = QPushButton(t("update_cancel_btn", lang))
        self.cancel_button.setProperty("variant", "ghost")
        self.cancel_button.clicked.connect(self._cancel)
        row.addWidget(self.update_button)
        row.addWidget(self.skip_button)
        row.addStretch(1)
        row.addWidget(self.cancel_button)
        outer.addLayout(row)

    def _request_update(self) -> None:
        if self._downloading:
            return
        self._downloading = True
        self.update_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_label.setText(
            t("update_downloading", self.settings.language, percent=0)
        )
        self.update_requested.emit()

    def _cancel(self) -> None:
        if self._downloading:
            self.cancel_requested.emit()
        else:
            self.reject()

    def set_progress(self, percent: int) -> None:
        value = max(0, min(100, int(percent)))
        self.progress_bar.setValue(value)
        self.status_label.setText(
            t("update_downloading", self.settings.language, percent=value)
        )

    def download_finished(self) -> None:
        self._downloading = False
        self.progress_bar.setValue(100)
        self.status_label.setText(t("update_ready_install", self.settings.language))

    def download_failed(self, message: str) -> None:
        self._downloading = False
        self.update_button.setEnabled(True)
        self.skip_button.setEnabled(True)
        self.status_label.setText(message)

    def download_cancelled(self) -> None:
        self._downloading = False
        self.update_button.setEnabled(True)
        self.skip_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.status_label.setText(t("update_cancelled", self.settings.language))

    def is_downloading(self) -> bool:
        return self._downloading
