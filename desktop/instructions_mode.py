"""The "Writes" picker shown in Project mode: which project-instruction file to write.

Project mode writes an agent instruction file (pipeline/instructions.ts) instead of a prompt; the
prompt controls do not apply to it and are hidden by the window.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from controls import Dropdown
from result_view import CONTROL_HEIGHT
from settings_ui import field_label

TARGET_LABELS = {
    "agentsMd": "AGENTS.md",
    "claudeMd": "CLAUDE.md",
    "cursor": "Cursor rule",
    "copilot": "Copilot instructions",
}
TARGET_HINTS = {
    "agentsMd": "Open format: Codex, Cursor, Copilot, Claude Code and others read it",
    "claudeMd": "Claude Code project instructions",
    "cursor": ".cursor/rules/project.mdc with frontmatter",
    "copilot": ".github/copilot-instructions.md",
}


class InstructionTargetSelector(QWidget):
    """Which file Project mode writes; AGENTS.md is the portable default."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(field_label("Writes"))
        self.picker = Dropdown(TARGET_LABELS["agentsMd"], popup_width=360)
        self.picker.setAccessibleName("Which instruction file to write")
        self.picker.setToolTip("Decides the file name, its header and the rules it is written from.")
        self.picker.set_items(
            [{"key": key, "label": label, "hint": TARGET_HINTS[key]} for key, label in TARGET_LABELS.items()],
            keep="agentsMd",
        )
        self.picker.ensurePolished()  # its own stylesheet would reset the height when polished later
        self.picker.setFixedHeight(CONTROL_HEIGHT)
        layout.addWidget(self.picker)

    def target(self) -> str:
        return self.picker.current_key() or "agentsMd"

    def set_target(self, target: str) -> None:
        self.picker.set_current(target if target in TARGET_LABELS else "agentsMd")
