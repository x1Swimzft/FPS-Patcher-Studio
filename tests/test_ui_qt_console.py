"""Qt console parity: line-count strings, batching caps and level colours."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("PySide6")

from fps_patcher.config import Settings  # noqa: E402
from fps_patcher.ui.strings import t  # noqa: E402
from fps_patcher.ui_qt.console import ConsolePanel, classify_log_level  # noqa: E402
from fps_patcher.ui_qt.theme import ThemeManager, make_theme  # noqa: E402


def _console(qtbot: Any, **overrides: Any) -> ConsolePanel:
    settings = Settings(**overrides)
    panel = ConsolePanel(settings, ThemeManager(settings))
    qtbot.addWidget(panel)
    return panel


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        ("en", ("0 lines", "1 line", "5 lines")),
        ("th", ("0 รายการ", "1 รายการ", "5 รายการ")),
    ],
)
def test_format_line_count_exact_strings(qtbot: Any, lang: str, expected: tuple[str, ...]) -> None:
    panel = _console(qtbot, language=lang)
    assert tuple(panel._format_line_count(count) for count in (0, 1, 5)) == expected
    assert panel._format_line_count(1) == t("console_line_one", lang, count=1)
    assert panel._format_line_count(5) == t("console_lines", lang, count=5)


def test_append_batch_caps_lines_and_blocks(qtbot: Any) -> None:
    panel = _console(qtbot, max_log_lines=100, log_timestamps=False)
    assert panel.editor.maximumBlockCount() == 100

    panel.append_batch([(f"line {index}", "INFO") for index in range(150)])

    assert len(panel._entries) == 100
    assert len(panel.get_lines()) == 100
    assert panel.get_lines()[-1] == "line 149"
    assert panel.editor.maximumBlockCount() == 100
    assert panel.editor.blockCount() <= 100
    assert panel._count.text() == "100 lines"


def test_level_colours_are_present_and_distinct(qtbot: Any) -> None:
    settings = Settings(show_ffmpeg_output=True)
    panel = ConsolePanel(settings, ThemeManager(settings))
    qtbot.addWidget(panel)
    theme = make_theme(settings)

    panel.append_batch(
        [
            ("plain info", "INFO"),
            ("all good", "OK"),
            ("careful", "WARN"),
            ("broken", "ERROR"),
            ("ffmpeg -i x", "CMD"),
            ("[DEBUG] trace", "DIM"),
        ]
    )

    colours = {tag: fmt.foreground().color().name() for tag, fmt in panel._formats.items()}
    assert len(set(colours.values())) >= 5
    assert colours["INFO"] == theme.tokens.text[1].lower()
    assert colours["OK"] == theme.tokens.success[1].lower()
    assert colours["WARN"] == theme.tokens.warn[1].lower()
    assert colours["ERROR"] == theme.tokens.danger[1].lower()
    assert colours["CMD"] == theme.tokens.accent[1].lower()
    assert classify_log_level("ffmpeg -i clip.mp4") == "CMD"
    assert classify_log_level("frame= 10 fps=0") == "DIM"


def test_clear_logs_resets_text_entries_and_counter(qtbot: Any) -> None:
    panel = _console(qtbot, log_timestamps=False)
    panel.append_batch([("first", "INFO"), ("second", "OK")])
    assert panel.editor.toPlainText().strip()

    panel.clear_logs()

    assert panel._entries == []
    assert panel.get_lines() == []
    assert panel.editor.toPlainText() == ""
    assert panel._count.text() == "0 lines"
    assert panel._latest.text() == ""
