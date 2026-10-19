from __future__ import annotations

from pathlib import Path

import pytest

from fps_patcher.ui.log_console import (
    LogConsole,
    classify_log_level,
    trim_lines_buffer,
)


def test_log_console_set_context_files(tmp_path: Path) -> None:
    # Test that set_context_files exists on LogConsole and works correctly
    target = tmp_path / "target.mp4"
    source = tmp_path / "source.mp4"

    # We can test the method directly on a dummy instance or mock
    class DummyConsole:
        def __init__(self) -> None:
            self.last_target_file: Path | None = None
            self.last_source_file: Path | None = None

    # Verify the method is bound to LogConsole
    assert hasattr(LogConsole, "set_context_files")

    dummy = DummyConsole()
    LogConsole.set_context_files(dummy, target=target, source=source)  # type: ignore[arg-type]
    assert dummy.last_target_file == target
    assert dummy.last_source_file == source


@pytest.mark.parametrize(
    ("level_in", "expected"),
    [
        ("INFO", "INFO"),
        ("OK", "OK"),
        ("WARN", "WARN"),
        ("ERROR", "ERROR"),
        ("CMD", "CMD"),
        ("COMMAND", "CMD"),
        ("DIM", "DIM"),
        ("DEBUG", "DEBUG"),
    ],
)
def test_classify_log_level_explicit_mapping(level_in: str, expected: str) -> None:
    assert classify_log_level("standard message without prefix", level_in) == expected


def test_classify_log_level_inferred_cmd_and_dim() -> None:
    # Infer CMD from command prefixes when level is INFO
    assert classify_log_level("$ ffmpeg -i ...", "INFO") == "CMD"
    assert classify_log_level("ffmpeg -version", "INFO") == "CMD"
    assert classify_log_level("$ ffmpeg -i ...") == "CMD"
    assert classify_log_level("ffmpeg -version") == "CMD"

    # Infer DIM from dim/verbose prefixes when level is INFO
    assert classify_log_level("frame= 120 fps=60", "INFO") == "DIM"
    assert classify_log_level("[DIM] details", "INFO") == "DIM"
    assert classify_log_level("frame= 120 fps=60") == "DIM"
    assert classify_log_level("[DIM] details") == "DIM"


def test_trim_lines_buffer_caps_over_limit() -> None:
    lines = [f"line {i}" for i in range(5000)]
    kept, dropped_count = trim_lines_buffer(lines, 200)

    assert len(kept) == 200
    assert dropped_count == 4800
    assert kept == lines[4800:]
    assert kept[0] == "line 4800"
    assert kept[-1] == "line 4999"


def test_trim_lines_buffer_leaves_within_limit_untouched() -> None:
    # Short list (< max_lines)
    short = [f"line {i}" for i in range(50)]
    kept_short, dropped_short = trim_lines_buffer(short, 200)
    assert kept_short == short
    assert dropped_short == 0

    # Exact max_lines (== max_lines)
    exact = [f"line {i}" for i in range(200)]
    kept_exact, dropped_exact = trim_lines_buffer(exact, 200)
    assert kept_exact == exact
    assert dropped_exact == 0

    # Empty list
    empty: list[str] = []
    kept_empty, dropped_empty = trim_lines_buffer(empty, 200)
    assert kept_empty == []
    assert dropped_empty == 0

