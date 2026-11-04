"""Patch job history: JSON log plus rollback from the ``.bak`` copies.

``timestamp`` is ISO-8601 local time with its UTC offset (e.g.
``2026-11-04T21:15:30+07:00``); callers can parse it with
``datetime.fromisoformat``.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import PatchError
from .models import PatchRequest, PatchResult

log = logging.getLogger("fps_patcher")

MAX_HISTORY = 200

# Parallel patch workers append to the same file; serialize read-modify-write
# inside this process. Cross-process writes remain best-effort.
_HISTORY_LOCK = threading.Lock()


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    timestamp: str  # ISO-8601 local time with UTC offset
    src: str
    output: str
    backup: str | None
    timescale: int
    strategy: str
    platform_profile: str
    rolled_back: bool = False


def _default_history_path() -> Path:
    # Lazy import: core must not pull in app config at module import time.
    from ..config import app_data_dir

    return app_data_dir() / "job_history.json"


def _coerce(raw: object) -> JobRecord | None:
    if not isinstance(raw, dict):
        return None
    try:
        return JobRecord(
            job_id=str(raw["job_id"]),
            timestamp=str(raw["timestamp"]),
            src=str(raw["src"]),
            output=str(raw["output"]),
            backup=None if raw.get("backup") is None else str(raw["backup"]),
            timescale=int(raw["timescale"]),
            strategy=str(raw["strategy"]),
            platform_profile=str(raw.get("platform_profile", "generic")),
            rolled_back=bool(raw.get("rolled_back", False)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _read(path: Path) -> list[JobRecord]:
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        log.warning("Could not read job history %s: %s", path, exc)
        return []
    if not isinstance(raw, list):
        return []
    return [record for item in raw if (record := _coerce(item)) is not None]


def _write(path: Path, records: list[JobRecord]) -> None:
    """Atomic replace: temp file in the same directory, then ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump([asdict(record) for record in records], fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def record_job(
    result: PatchResult,
    req: PatchRequest,
    *,
    history_path: Path | None = None,
) -> JobRecord | None:
    """Append a successful patch to history; ``None`` if the log cannot be written."""
    path = history_path or _default_history_path()
    record = JobRecord(
        job_id=uuid.uuid4().hex,
        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        src=str(result.src),
        output=str(result.output),
        backup=None if result.backup_path is None else str(result.backup_path),
        timescale=req.timescale,
        strategy=req.strategy,
        platform_profile=req.platform_profile,
    )
    try:
        with _HISTORY_LOCK:
            records = _read(path)
            records.insert(0, record)
            _write(path, records[:MAX_HISTORY])
    except OSError as exc:
        # A successful patch must never be reported as failed because of logging.
        log.warning("Could not record job history in %s: %s", path, exc)
        return None
    return record


def load_history(
    *, history_path: Path | None = None, limit: int = 50
) -> list[JobRecord]:
    """Newest first; missing or malformed history reads as an empty list."""
    records = _read(history_path or _default_history_path())
    return records[: max(0, limit)]


def undo_job(
    job_id: str | None = None, *, history_path: Path | None = None
) -> JobRecord:
    """Restore the job's backup over its output and mark the job rolled back."""
    path = history_path or _default_history_path()
    records = _read(path)
    index: int | None = None
    if job_id is not None:
        index = next((i for i, record in enumerate(records) if record.job_id == job_id), None)
    else:
        index = next((i for i, record in enumerate(records) if not record.rolled_back), None)
    if index is None:
        if job_id is not None:
            raise PatchError(f"Job not found: {job_id}")
        raise PatchError("No patch job to roll back.")
    record = records[index]
    if record.rolled_back:
        raise PatchError(f"Job {record.job_id} was already rolled back.")
    if not record.backup:
        raise PatchError(f"Job {record.job_id} has no backup to restore.")
    backup = Path(record.backup)
    output = Path(record.output)
    if not backup.is_file():
        raise PatchError(f"Backup file is missing: {backup}")

    # Lazy import: job_history is imported by patcher at patch time.
    from .patcher import _DestinationLock

    lock = _DestinationLock(output)
    lock.acquire()
    try:
        os.replace(backup, output)
    except OSError as exc:
        raise PatchError(f"Could not restore '{output}': {exc}") from exc
    finally:
        lock.release()

    updated = replace(record, rolled_back=True)
    records[index] = updated
    try:
        _write(path, records)
    except OSError as exc:
        # The bytes are already restored; only the marker failed to persist.
        log.warning("Could not update job history in %s: %s", path, exc)
    return updated
