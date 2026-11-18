"""The result area in Agent mode: the subagent file, its check, the rules it was written from, and saving
it into a project under the agent's name."""

from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from agent_mode import TARGET_LABELS
from document_view import DocumentView
from instructions_view import save_instructions

FOLDERS = {
    "claudeCode": ".claude/agents/{}.md",
    "cursor": ".cursor/agents/{}.md",
    "codex": ".codex/agents/{}.toml",
    "copilot": ".github/agents/{}.agent.md",
}
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def agent_file_name(target: str, text: str, fallback: str) -> str:
    """The project path for the agent's current name: an edit of `name` in the text renames the file."""
    match = re.search(r'^name\s*=\s*"([^"]*)"', text, re.M) if target == "codex" else None
    if target != "codex":
        front = re.match(r"---\r?\n(.*?)\r?\n---", text.lstrip(), re.S)
        match = re.search(r"^name:\s*[\"']?([^\"'\n]*?)[\"']?\s*$", front.group(1), re.M) if front else None
    name = match.group(1).strip() if match else ""
    pattern = FOLDERS.get(target)
    return pattern.format(name) if pattern and NAME.match(name) else fallback


class AgentView(DocumentView):
    SLOGAN = "THOUGHTS IN. SUBAGENTS OUT."

    def render_agent(self, payload: dict, source_thoughts: str | None = None) -> None:
        check = payload.get("check") or {}
        file_name = payload.get("fileName") or ".claude/agents/agent.md"
        state = "Valid" if check.get("valid") else "Not valid"
        repaired = " · fixed after the first check" if payload.get("repaired") else ""
        self.render_document(
            payload,
            title=payload.get("name") or Path(file_name).name,
            status=f"{state} · {TARGET_LABELS.get(payload.get('target', ''), '')} · {file_name}{repaired}",
            text=payload.get("text", ""),
            file_label=Path(file_name).name,
            save_label="Save into project…",
            save_tip=f"Choose the project folder: the subagent is written to {file_name} there",
            on_save=self.save,
            source_thoughts=source_thoughts,
        )

    def save(self) -> None:
        if self.editor is None:
            return
        text = self.editor.toPlainText()
        file_name = agent_file_name(self.payload.get("target", ""), text, self.payload.get("fileName") or "")
        if not file_name:
            return
        folder = QFileDialog.getExistingDirectory(self, f"Choose the project folder for {file_name}")
        if not folder:
            return
        target = Path(folder) / file_name
        if target.exists():
            answer = QMessageBox.question(self, f"Replace {target.name}?", f"{target} already exists. Replace it?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        save_instructions(Path(folder), file_name, text)
