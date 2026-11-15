"""The table under the slogan of an empty result area: what each mode writes and when it is read.

The row of the current mode is darker, so the user sees where it sits among the four.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

# mode key (skill_mode.py) → name, what it writes, when it is read
ROWS = [
    ("prompt", "Prompt", "A prompt for one task", "Once, in a chat"),
    ("skill", "Skill", "SKILL.md: a repeated procedure", "When a task matches, in any project"),
    ("instructions", "Project", "AGENTS.md: the project's rules", "Every session in this project"),
    ("agent", "Subagent", "A specialist with its own tools", "When the main agent hands it a job"),
]
SUMMARY = "Project says how the project works. Skill says how to do a procedure. Subagent is who does it."


def _cell(text: str, name: str, current: bool) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setProperty("current", current)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)  # wraps and grows taller
    return label


def mode_guide(current: str) -> QWidget:
    """Four rows, one per mode, centred under the slogan; `current` is a mode key such as "skill"."""
    holder = QWidget()
    outer = QVBoxLayout(holder)
    outer.setContentsMargins(0, 18, 0, 0)
    outer.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    table = QFrame()
    table.setObjectName("modeGuide")
    table.setMaximumWidth(560)
    grid = QGridLayout(table)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(8)
    for column, head in enumerate(("", "What you get", "When it's used")):
        grid.addWidget(_cell(head, "guideHead", False), 0, column)
    for row, (key, name, what, when) in enumerate(ROWS, start=1):
        on = key == current
        grid.addWidget(_cell(name, "guideMode", on), row, 0)
        grid.addWidget(_cell(what, "guideText", on), row, 1)
        grid.addWidget(_cell(when, "guideText", on), row, 2)
    grid.setColumnStretch(0, 2)
    grid.setColumnStretch(1, 5)
    grid.setColumnStretch(2, 5)
    outer.addWidget(table)
    summary = _cell(SUMMARY, "guideText", False)
    summary.setMaximumWidth(560)
    summary.setContentsMargins(0, 10, 0, 0)
    outer.addWidget(summary)
    return holder
