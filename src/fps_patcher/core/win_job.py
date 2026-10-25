"""Windows process helpers: kill-on-close jobs and named mutexes.

A plain ``Popen.kill()`` only stops the direct child. Assigning ffmpeg to a
kill-on-close job means Task Manager kills, crashes and normal exits also take
down any descendants, and cancel can terminate the whole tree atomically.

The process is assigned right after ``Popen`` returns (not suspended). The
spawn-to-assign window is tiny and ffmpeg spawns no helpers during it; children
created before assignment would not be retroactively added.
"""

from __future__ import annotations

import ctypes
import os
from typing import Any

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kernel32() -> Any | None:
    if os.name != "nt":
        return None
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Explicit 64-bit-safe signatures; the ctypes defaults truncate handles to int.
    k32.CreateJobObjectW.restype = ctypes.c_void_p
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k32.ReleaseMutex.argtypes = [ctypes.c_void_p]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    return k32


class ProcessJob:
    """Best-effort kill-on-close job. No-op on non-Windows or API failure."""

    def __init__(self) -> None:
        self._k32 = _kernel32()
        self._handle: Any | None = None
        self._assigned = False
        if self._k32 is None:
            return
        handle = self._k32.CreateJobObjectW(None, None)
        if not handle:
            return
        info = _ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = self._k32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            self._k32.CloseHandle(handle)
            return
        self._handle = handle

    @property
    def active(self) -> bool:
        return self._handle is not None

    def assign(self, process: Any) -> bool:
        """Assign a ``subprocess.Popen`` process to the job."""
        handle = getattr(process, "_handle", None)
        if self._handle is None or self._k32 is None or handle is None:
            return False
        ok = bool(self._k32.AssignProcessToJobObject(self._handle, int(handle)))
        self._assigned = self._assigned or ok
        return ok

    def terminate(self, exit_code: int = 1) -> bool:
        """Terminate every process in the job. False means callers must fall back."""
        if self._handle is None or self._k32 is None or not self._assigned:
            return False
        return bool(self._k32.TerminateJobObject(self._handle, exit_code))

    def close(self) -> None:
        """Close the job; kill-on-close reaps any remaining descendants."""
        if self._handle is not None and self._k32 is not None:
            self._k32.CloseHandle(self._handle)
            self._handle = None
        self._assigned = False


class NamedMutex:
    """Cross-process mutex. No-op on non-Windows or API failure.

    The kernel releases an abandoned mutex when its owner dies; ``acquire()``
    treats ``WAIT_ABANDONED`` as ownership so a crashed writer cannot deadlock
    every later job.
    """

    _INFINITE = 0xFFFFFFFF
    _WAIT_OBJECT_0 = 0
    _WAIT_ABANDONED = 0x80

    def __init__(self, name: str) -> None:
        self._k32 = _kernel32()
        self._handle: Any | None = None
        self._owned = False
        if self._k32 is None:
            return
        handle = self._k32.CreateMutexW(None, False, name)
        self._handle = handle or None

    @property
    def available(self) -> bool:
        return self._handle is not None

    def acquire(self, timeout_ms: int = _INFINITE) -> bool:
        if self._handle is None or self._k32 is None:
            return False
        result = self._k32.WaitForSingleObject(self._handle, timeout_ms)
        self._owned = result in (self._WAIT_OBJECT_0, self._WAIT_ABANDONED)
        return self._owned

    def release(self) -> None:
        if self._owned and self._handle is not None and self._k32 is not None:
            self._k32.ReleaseMutex(self._handle)
            self._owned = False

    def close(self) -> None:
        self.release()
        if self._handle is not None and self._k32 is not None:
            self._k32.CloseHandle(self._handle)
            self._handle = None
