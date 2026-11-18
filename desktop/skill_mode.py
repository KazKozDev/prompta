"""Prompt / Skill / Project / Agent switch and the "Works in" picker shown in Skill mode.

Skill mode writes a SKILL.md (pipeline/skill.ts), Project mode an agent instruction file
(pipeline/instructions.ts, picker in instructions_mode.py) and Agent mode a subagent
(pipeline/agent.ts, picker in agent_mode.py) instead of a prompt; the prompt controls
(Written for, Runs in, Technique) do not apply to them and are hidden by the window.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from controls import Dropdown
from result_view import CONTROL_HEIGHT
from settings_ui import field_label

PROMPT_MODE = "prompt"
SKILL_MODE = "skill"
INSTRUCTIONS_MODE = "instructions"
AGENT_MODE = "agent"
MODES = (PROMPT_MODE, INSTRUCTIONS_MODE, SKILL_MODE, AGENT_MODE)


class ModeSwitch(QFrame):
    """Four tabs in the header: Prompt, Project, Skill and Subagent, drawn as plain words (the
    chosen one dark and bold), with no tooltips. `changed(mode)` fires on every switch."""

    changed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("modeTabs")  # plain words, not the variant switch's pills (app.qss)
        self.setAccessibleName("What to build")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        self.buttons = QButtonGroup(self)
        self.buttons.setExclusive(True)
        self._by_mode: dict[str, QPushButton] = {}
        segments = [
            (PROMPT_MODE, "Prompt"),
            (INSTRUCTIONS_MODE, "Project"),
            (SKILL_MODE, "Skill"),
            (AGENT_MODE, "Subagent"),
        ]
        for index, (mode, label) in enumerate(segments):
            button = QPushButton(label)
            button.setObjectName("modeTab")
            button.setCheckable(True)
            button.setFixedHeight(24)
            button.ensurePolished()  # the stylesheet's font size, before it is measured
            # Wide enough for the bold face, so the row does not shift when a tab is chosen.
            bold = button.font()
            bold.setWeight(QFont.Weight.DemiBold)
            button.setFixedWidth(QFontMetrics(bold).horizontalAdvance(label) + 4)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.toggled.connect(lambda on, m=mode: self._on_toggled(m, on))
            self.buttons.addButton(button, index)
            self._by_mode[mode] = button
            row.addWidget(button)
        self._by_mode[PROMPT_MODE].setChecked(True)

    def _on_toggled(self, mode: str, on: bool) -> None:
        if on:
            self.changed.emit(mode)

    def mode(self) -> str:
        return next((mode for mode, button in self._by_mode.items() if button.isChecked()), PROMPT_MODE)

    def set_mode(self, mode: str) -> None:
        self._by_mode[mode if mode in self._by_mode else PROMPT_MODE].setChecked(True)


class SurfaceSelector(QWidget):
    """Where the skill must work: portable (six standard keys) or Claude Code (its extensions allowed)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(field_label("Works in"))
        self.picker = Dropdown("Claude apps, API and Claude Code", popup_width=320)
        self.picker.setAccessibleName("Where the skill will work")
        self.picker.setToolTip("Decides which frontmatter keys the skill may use.")
        self.picker.set_items(
            [
                {
                    "key": "portable",
                    "label": "Claude apps, API and Claude Code",
                    "hint": "Standard keys only: name, description, license, …",
                },
                {
                    "key": "claudeCode",
                    "label": "Claude Code only",
                    "hint": "Also when_to_use, paths, context: fork, …",
                },
            ],
            keep="portable",
        )
        self.picker.ensurePolished()  # its own stylesheet would reset the height when polished later
        self.picker.setFixedHeight(CONTROL_HEIGHT)
        layout.addWidget(self.picker)

    def surface(self) -> str:
        return self.picker.current_key() or "portable"

    def set_surface(self, surface: str) -> None:
        self.picker.set_current(surface if surface in ("portable", "claudeCode") else "portable")
