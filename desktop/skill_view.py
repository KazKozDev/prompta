"""The result area in Skill mode: the SKILL.md, its check, the rules it was written from, and saving it."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from document_view import DocumentView

SURFACE_LABELS = {"portable": "Claude apps, API and Claude Code", "claudeCode": "Claude Code only"}


def save_skill(folder: Path, name: str, text: str) -> Path:
    """Writes <folder>/<name>/SKILL.md: the folder name must match `name`. Returns the file path."""
    target = folder / name / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


class SkillView(DocumentView):
    SLOGAN = "THOUGHTS IN. SKILLS OUT."
    MODE = "skill"

    def render_skill(self, payload: dict) -> None:
        check = payload.get("check") or {}
        surface = SURFACE_LABELS.get(payload.get("surface", ""), "")
        state = "Valid" if check.get("valid") else "Not valid"
        repaired = " · fixed after the first check" if payload.get("repaired") else ""
        self.render_document(
            payload,
            title=payload.get("name") or "SKILL.md",
            status=f"{state} · works in {surface}{repaired}",
            text=payload.get("skill", ""),
            file_label="SKILL.md",
            save_label="Save as folder…",
            save_tip="Creates <folder>/<name>/SKILL.md: the skill folder must be named like the skill",
            on_save=self.save,
        )

    def save(self) -> None:
        name = self.payload.get("name") or ""
        if not name or self.editor is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose where to create the skill folder")
        if not folder:
            return
        target = Path(folder) / name / "SKILL.md"
        if target.exists():
            answer = QMessageBox.question(self, "Replace SKILL.md?", f"{target} already exists. Replace it?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        save_skill(Path(folder), name, self.editor.toPlainText())
