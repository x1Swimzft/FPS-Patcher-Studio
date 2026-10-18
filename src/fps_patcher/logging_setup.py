"""File logging (rotating) for diagnostics."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import app_data_dir


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("fps_patcher")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    handler = RotatingFileHandler(
        app_data_dir() / "fps_patcher.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger
