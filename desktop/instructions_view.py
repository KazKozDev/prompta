"""The result area in Project mode: the instruction file (AGENTS.md, CLAUDE.md, a Cursor rule or
Copilot instructions), its check, the rules it was written from, and saving it into a project."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from document_view import DocumentView
from instructions_mode import TARGET_LABELS


def save_instructions(project: Path, file_name: str, text: str) -> Path:
    """Writes <project>/<file_name> (e.g. .cursor/rules/project.mdc), creating folders. Returns the path."""
    target = project / file_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


class InstructionsView(DocumentView):
    SLOGAN = "THOUGHTS IN. PROJECT RULES OUT."
    MODE = "instructions"

    def render_instructions(self, payload: dict, source_thoughts: str | None = None) -> None:
        check = payload.get("check") or {}
        file_name = payload.get("fileName") or "AGENTS.md"
        state = "Valid" if check.get("valid") else "Not valid"
        lines = check.get("lines")
        size = f" · {lines} line{'s' if lines != 1 else ''}" if lines else ""
        repaired = " · fixed after the first check" if payload.get("repaired") else ""
        self.render_document(
            payload,
            title=file_name,
            status=f"{state} · {TARGET_LABELS.get(payload.get('target', ''), '')}{size}{repaired}",
            text=payload.get("text", ""),
            file_label=Path(file_name).name,
            save_label="Save into project…",
            save_tip=f"Choose the project folder: the file is written to {file_name} there",
            on_save=self.save,
            source_thoughts=source_thoughts,
        )

    def save(self) -> None:
        file_name = self.payload.get("fileName") or ""
        if not file_name or self.editor is None:
            return
        folder = QFileDialog.getExistingDirectory(self, f"Choose the project folder for {file_name}")
        if not folder:
            return
        target = Path(folder) / file_name
        if target.exists():
            answer = QMessageBox.question(self, f"Replace {target.name}?", f"{target} already exists. Replace it?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        save_instructions(Path(folder), file_name, self.editor.toPlainText())
