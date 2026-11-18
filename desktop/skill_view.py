"""The result area in Skill mode: the SKILL.md, its check, the rules it was written from, and saving it."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QLabel, QMessageBox, QWidget

from document_view import DocumentView
from result_view import Disclosure

SURFACE_LABELS = {"portable": "Claude apps, API and Claude Code", "claudeCode": "Claude Code only"}


def tests_block(tests: object) -> QWidget | None:
    """Requests to try the skill with in a new chat: the ones that should load it, then near misses that should not.
    None when the run gave none."""
    if not isinstance(tests, dict):
        return None
    trigger = [t for t in tests.get("trigger") or [] if isinstance(t, str) and t.strip()]
    skip = [t for t in tests.get("skip") or [] if isinstance(t, str) and t.strip()]
    if not trigger and not skip:
        return None
    block = Disclosure(f"Try it: {len(trigger)} requests should load it, {len(skip)} should not")
    for mark, items in (("✓", trigger), ("✗", skip)):
        for text in items:
            label = QLabel(f"{mark}  {text}")
            label.setObjectName("muted")
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            block.body_layout.addWidget(label)
    return block


def save_skill(folder: Path, name: str, text: str) -> Path:
    """Writes <folder>/<name>/SKILL.md: the folder name must match `name`. Returns the file path."""
    target = folder / name / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


class SkillView(DocumentView):
    SLOGAN = "THOUGHTS IN. SKILLS OUT."

    def render_skill(self, payload: dict, source_thoughts: str | None = None) -> None:
        check = payload.get("check") or {}
        surface = SURFACE_LABELS.get(payload.get("surface", ""), "")
        state = "Valid" if check.get("valid") else "Not valid"
        reviewed = " · reviewed" if payload.get("reviewed") else ""
        repaired = " · fixed after the first check" if payload.get("repaired") else ""
        tests = tests_block(payload.get("tests"))
        self.render_document(
            payload,
            title=payload.get("name") or "SKILL.md",
            status=f"{state} · works in {surface}{reviewed}{repaired}",
            text=payload.get("skill", ""),
            file_label="SKILL.md",
            save_label="Save as folder…",
            save_tip="Creates <folder>/<name>/SKILL.md: the skill folder must be named like the skill",
            on_save=self.save,
            source_thoughts=source_thoughts,
            extras=[tests] if tests else None,
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
