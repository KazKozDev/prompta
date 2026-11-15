"""The "Subagent for" picker shown in Subagent mode: which tool's subagent format to write.

Agent mode writes a subagent definition (pipeline/agent.ts) instead of a prompt; the prompt controls
do not apply to it and are hidden by the window.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from controls import Dropdown
from result_view import CONTROL_HEIGHT
from settings_ui import field_label

TARGET_LABELS = {
    "claudeCode": "Claude Code",
    "cursor": "Cursor",
    "codex": "Codex",
    "copilot": "GitHub Copilot",
}
TARGET_HINTS = {
    "claudeCode": ".claude/agents/<name>.md · Cursor and VS Code read it too",
    "cursor": ".cursor/agents/<name>.md",
    "codex": ".codex/agents/<name>.toml",
    "copilot": ".github/agents/<name>.agent.md",
}


class AgentTargetSelector(QWidget):
    """Which tool the subagent is for; Claude Code's format is the most widely read."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(field_label("Subagent for"))
        self.picker = Dropdown(TARGET_LABELS["claudeCode"], popup_width=360)
        self.picker.setAccessibleName("Which tool the subagent is for")
        self.picker.setToolTip("Decides the file format, its fields and the rules it is written from.")
        self.picker.set_items(
            [{"key": key, "label": label, "hint": TARGET_HINTS[key]} for key, label in TARGET_LABELS.items()],
            keep="claudeCode",
        )
        self.picker.ensurePolished()  # its own stylesheet would reset the height when polished later
        self.picker.setFixedHeight(CONTROL_HEIGHT)
        layout.addWidget(self.picker)

    def target(self) -> str:
        return self.picker.current_key() or "claudeCode"

    def set_target(self, target: str) -> None:
        self.picker.set_current(target if target in TARGET_LABELS else "claudeCode")
