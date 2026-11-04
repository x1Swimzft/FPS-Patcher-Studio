"""Shared Qt widget contracts: sections, setting rows and consequence badges."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

from fps_patcher.config import Settings  # noqa: E402
from fps_patcher.ui_qt.theme import make_theme  # noqa: E402
from fps_patcher.ui_qt.widgets import (  # noqa: E402
    CollapsibleSection,
    ConsequenceBadge,
    InsetRow,
    SettingRow,
    Switch,
    WrapLabel,
)


def test_collapsible_section_hides_body_until_toggled(qtbot: Any) -> None:
    section = CollapsibleSection("Advanced", make_theme(Settings()))
    qtbot.addWidget(section)
    section.show()
    seen: list[bool] = []
    section.toggled.connect(seen.append)

    assert not section.is_expanded
    assert not section.body.isVisible()

    qtbot.mouseClick(section.header, Qt.MouseButton.LeftButton)
    assert section.is_expanded
    assert section.body.isVisible()
    assert seen == [True]

    qtbot.mouseClick(section.header, Qt.MouseButton.LeftButton)
    assert not section.is_expanded
    assert not section.body.isVisible()
    assert seen == [True, False]


def test_collapsible_section_starts_expanded(qtbot: Any) -> None:
    section = CollapsibleSection("Advanced", make_theme(Settings()), expanded=True)
    qtbot.addWidget(section)
    section.show()

    assert section.is_expanded
    assert section.body.isVisible()
    assert section.header.property("expanded") == "true"


def test_setting_row_shows_hint_and_label_click_activates_control(qtbot: Any) -> None:
    theme = make_theme(Settings())
    toggle = Switch(theme)
    row = SettingRow("Auto fix VFR", theme, toggle, hint="Lossless is safer.")
    qtbot.addWidget(row)
    row.show()

    assert row.hint.isVisible()
    assert row.minimumHeight() >= 40

    qtbot.mouseClick(row.label, Qt.MouseButton.LeftButton)
    assert toggle.isChecked()


def test_setting_row_without_hint_hides_it(qtbot: Any) -> None:
    row = SettingRow("Theme", make_theme(Settings()))
    qtbot.addWidget(row)
    assert not row.hint.isVisible()
    assert row.control is None


@pytest.mark.parametrize(
    ("kind", "token"),
    [
        ("lossless", "success"),
        ("warning", "warn"),
        ("danger", "danger"),
        ("neutral", "text2"),
    ],
)
def test_consequence_badge_uses_semantic_colour(
    qtbot: Any, kind: str, token: str
) -> None:
    dark = make_theme(Settings())
    badge = ConsequenceBadge("write probe failed", kind, dark)
    qtbot.addWidget(badge)

    assert badge.accessibleName() == "write probe failed"
    assert dark.color(token) in badge.styleSheet()

    light = make_theme(Settings(appearance="light"))
    badge.set_theme(light)
    assert light.color(token) in badge.styleSheet()


def test_consequence_badge_rejects_unknown_kind(qtbot: Any) -> None:
    with pytest.raises(ValueError):
        ConsequenceBadge("nope", "unknown", make_theme(Settings()))


def test_inset_row_grows_with_the_font_scale(qtbot: Any) -> None:
    medium = InsetRow("Target FPS", make_theme(Settings(font_size="M")))
    large = InsetRow("Target FPS", make_theme(Settings(font_size="L")))
    qtbot.addWidget(medium)
    qtbot.addWidget(large)

    assert medium.height() == 34
    assert large.height() == 36


def test_switch_is_forty_by_twenty_two(qtbot: Any) -> None:
    toggle = Switch(make_theme(Settings()))
    qtbot.addWidget(toggle)

    assert (toggle.width(), toggle.height()) == (40, 22)


def test_switch_thumb_slides_and_snaps_with_reduce_motion(qtbot: Any) -> None:
    toggle = Switch(make_theme(Settings()))
    qtbot.addWidget(toggle)
    toggle.show()

    toggle.setChecked(True)
    qtbot.waitUntil(lambda: toggle.thumbOffset == pytest.approx(1.0), timeout=500)

    toggle.set_reduce_motion(True)
    toggle.setChecked(False)
    assert toggle.thumbOffset == pytest.approx(0.0)


def test_wrap_label_breaks_unspaced_thai(qtbot: Any) -> None:
    text = "จำกัดบิตเรตวิดีโอสำหรับมือถือเมื่อต้นฉบับสูงกว่าเป้าหมาย"
    label = WrapLabel(text)
    qtbot.addWidget(label)
    label.show()

    one_line = label.fontMetrics().height()
    assert label.heightForWidth(160) > one_line
    assert label.minimumSizeHint().width() == 1
