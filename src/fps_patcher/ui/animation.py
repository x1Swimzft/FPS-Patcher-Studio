"""Lightweight 60fps cubic ease-out animation utility using Tkinter .after()."""

from __future__ import annotations

import contextlib
import time
import tkinter as tk
from collections.abc import Callable
from typing import Any


def ease_out_cubic(t: float) -> float:
    """Cubic ease-out curve: f(t) = 1.0 - (1.0 - t)**3 for t in [0.0, 1.0]."""
    clamped = max(0.0, min(1.0, float(t)))
    return 1.0 - (1.0 - clamped) ** 3


# Map (widget_id, prop_key) -> after_job_id
_ACTIVE_ANIMATIONS: dict[tuple[int, str], str] = {}


def cancel_animation(widget: Any, prop_key: str = "default") -> None:
    """Cancel any active animation on target widget for the specified property."""
    key = (id(widget), prop_key)
    job_id = _ACTIVE_ANIMATIONS.pop(key, None)
    if job_id is not None:
        with contextlib.suppress(tk.TclError, AttributeError):
            widget.after_cancel(job_id)


def is_animating(widget: Any, prop_key: str = "default") -> bool:
    """Check if an animation is currently active on target widget for the specified property."""
    return (id(widget), prop_key) in _ACTIVE_ANIMATIONS


def animate(
    widget: Any,
    start_val: float,
    end_val: float,
    duration_ms: int = 200,
    on_step: Callable[[float], None] | None = None,
    on_done: Callable[[], None] | None = None,
    reduce_motion: bool = False,
    step_interval_ms: int = 16,
    prop_key: str = "default",
) -> str | None:
    """Animate a numeric value from start_val to end_val with cubic ease-out.

    Parameters
    ----------
    widget : Any
        Tkinter or CustomTkinter widget providing .after() and .after_cancel().
    start_val : float
        Initial value at t = 0.
    end_val : float
        Target value at t = 1.
    duration_ms : int
        Total duration in milliseconds (default: 200).
    on_step : Callable[[float], None] | None
        Callback invoked on every frame with the current interpolated float value.
    on_done : Callable[[], None] | None
        Callback invoked once when the animation completes.
    reduce_motion : bool
        If True (or duration_ms <= 0), snap directly to end_val without delay.
    step_interval_ms : int
        Frame interval in milliseconds (default: 16ms ~ 60fps).
    prop_key : str
        Property key to isolate distinct animations on the same widget.

    Returns
    -------
    str | None
        Tkinter after job ID if scheduled, or None if snapped immediately.
    """
    cancel_animation(widget, prop_key=prop_key)

    # Fast path: reduce_motion or non-positive duration
    if reduce_motion or duration_ms <= 0:
        if on_step is not None:
            on_step(float(end_val))
        if on_done is not None:
            on_done()
        return None

    # Already at destination
    if start_val == end_val:
        if on_step is not None:
            on_step(float(end_val))
        if on_done is not None:
            on_done()
        return None

    start_time = time.monotonic()
    key = (id(widget), prop_key)
    delta = float(end_val) - float(start_val)

    def _step() -> None:
        if hasattr(widget, "winfo_exists"):
            try:
                if not widget.winfo_exists():
                    _ACTIVE_ANIMATIONS.pop(key, None)
                    return
            except (tk.TclError, AttributeError):
                _ACTIVE_ANIMATIONS.pop(key, None)
                return

        elapsed_ms = (time.monotonic() - start_time) * 1000.0
        t = min(1.0, max(0.0, elapsed_ms / float(duration_ms)))
        progress = ease_out_cubic(t)
        current_val = float(start_val) + delta * progress

        if on_step is not None:
            try:
                on_step(current_val)
            except (tk.TclError, AttributeError):
                _ACTIVE_ANIMATIONS.pop(key, None)
                return

        if t >= 1.0:
            _ACTIVE_ANIMATIONS.pop(key, None)
            if on_step is not None:
                with contextlib.suppress(tk.TclError, AttributeError):
                    on_step(float(end_val))
            if on_done is not None:
                with contextlib.suppress(tk.TclError, AttributeError):
                    on_done()
            return

        try:
            next_job = widget.after(step_interval_ms, _step)
            _ACTIVE_ANIMATIONS[key] = next_job
        except (tk.TclError, AttributeError):
            _ACTIVE_ANIMATIONS.pop(key, None)

    # Initial frame
    if on_step is not None:
        try:
            on_step(float(start_val))
        except (tk.TclError, AttributeError):
            return None

    try:
        first_job = str(widget.after(step_interval_ms, _step))
        _ACTIVE_ANIMATIONS[key] = first_job
        return first_job
    except (tk.TclError, AttributeError):
        return None
