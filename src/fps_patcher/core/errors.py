"""Domain errors raised by the core layer."""

from __future__ import annotations


class FPSPatcherError(Exception):
    """Base class for all application errors."""


class FFmpegNotFoundError(FPSPatcherError):
    """No working ffmpeg/ffprobe binary could be located."""


class ProbeError(FPSPatcherError):
    """ffprobe failed or returned unusable data."""


class PatchError(FPSPatcherError):
    """ffmpeg remux failed."""

    def __init__(self, message: str, stderr_tail: list[str] | None = None) -> None:
        super().__init__(message)
        self.stderr_tail = stderr_tail or []


class OutputFileExistsError(PatchError):
    """Output file already exists and overwrite is disabled."""


class PatchCancelledError(PatchError):
    """Patch was cancelled by the user."""


class VerifyError(FPSPatcherError):
    """Output file failed post-patch verification."""
