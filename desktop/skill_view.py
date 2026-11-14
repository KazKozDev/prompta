"""The result area in Skill mode: the SKILL.md, its check, the rules it was written from, and saving it."""

from __future__ import annotations

from html import escape
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QLayout,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from result_column import Wordmark
from result_view import Disclosure, muted_label
from settings_ui import text_link
from widgets import DashedScrollBar, PromptEdit, use_step_scroll

SURFACE_LABELS = {"portable": "Claude apps, API and Claude Code", "claudeCode": "Claude Code only"}


def save_skill(folder: Path, name: str, text: str) -> Path:
    """Writes <folder>/<name>/SKILL.md: the folder name must match `name`. Returns the file path."""
    target = folder / name / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


class SkillView(QScrollArea):
    """Same frame as ResultColumn. `skillEdited(text)` fires when the user edits the SKILL.md."""

    skillEdited = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.payload: dict = {}
        self.editor: PromptEdit | None = None
        self.setObjectName("outputScroll")
        self.setVerticalScrollBar(DashedScrollBar(Qt.Orientation.Vertical, self))
        self.setHorizontalScrollBar(DashedScrollBar(Qt.Orientation.Horizontal, self))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.viewport().setAutoFillBackground(False)
        use_step_scroll(self)
        self.setWidgetResizable(True)
        holder = QWidget()
        holder.setObjectName("outputContent")
        holder.setAutoFillBackground(False)
        self.output_layout = QVBoxLayout(holder)
        self.output_layout.setContentsMargins(0, 0, 0, 0)
        self.output_layout.setSpacing(10)
        self.output_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.setWidget(holder)

    def clear(self) -> None:
        self.editor = None
        while self.output_layout.count():
            item = self.output_layout.takeAt(0)
            if widget := item.widget():
                widget.hide()
                widget.deleteLater()

    def show_placeholder(self) -> None:
        self.clear()
        self.payload = {}
        self.output_layout.addStretch(5)
        self.output_layout.addWidget(Wordmark("PROMPTA"))
        slogan = QLabel("THOUGHTS IN. SKILLS OUT.")
        slogan.setObjectName("slogan")
        slogan.setAlignment(Qt.AlignmentFlag.AlignCenter)
        slogan.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.output_layout.addWidget(slogan)
        self.output_layout.addStretch(6)

    def show_error(self, message: str) -> None:
        self.clear()
        error = QLabel(f"Error: {message}")
        error.setObjectName("error")
        error.setWordWrap(True)
        self.output_layout.addStretch(1)
        self.output_layout.addWidget(error)
        self.output_layout.addStretch(1)

    def render_skill(self, payload: dict) -> None:
        self.clear()
        self.payload = payload
        check = payload.get("check") or {}
        title = QLabel(payload.get("name") or "SKILL.md")
        title.setObjectName("goal")
        title.setWordWrap(True)
        self.output_layout.addWidget(title)
        surface = SURFACE_LABELS.get(payload.get("surface", ""), "")
        state = "Valid" if check.get("valid") else "Not valid"
        repaired = " · fixed after the first check" if payload.get("repaired") else ""
        self.output_layout.addWidget(muted_label(f"{state} · works in {surface}{repaired}"))
        for error in check.get("errors") or []:
            self.output_layout.addWidget(self._note(error, "error"))
        for warning in check.get("warnings") or []:
            self.output_layout.addWidget(self._note(warning, "warn"))

        self.editor = PromptEdit(payload.get("skill", ""), self)
        self.editor.setAccessibleName("SKILL.md")
        self.editor.copy_button.setToolTip("Copy SKILL.md")
        self.editor.copy_button.setAccessibleName("Copy SKILL.md")
        self.editor.fit_to_content()
        self.editor.textChanged.connect(self._on_edited)
        self.output_layout.addWidget(self.editor)

        save = text_link("Save as folder…")
        save.setToolTip("Creates <folder>/<name>/SKILL.md: the skill folder must be named like the skill")
        save.clicked.connect(self.save)
        self.output_layout.addWidget(save, 0, Qt.AlignmentFlag.AlignLeft)

        rules = payload.get("rules") or []
        if rules:
            details = Disclosure(f"Written from {len(rules)} official rule{'s' if len(rules) != 1 else ''}")
            for rule in rules:
                label = QLabel(
                    f"{escape(rule['rule_text'])} "
                    f'<a href="{escape(rule["source_url"])}" style="color:#9a7b1f">{escape(rule["source_title"])}</a>'
                )
                label.setObjectName("muted")
                label.setTextFormat(Qt.TextFormat.RichText)
                label.setWordWrap(True)
                label.setOpenExternalLinks(True)
                details.body_layout.addWidget(label)
            verified = payload.get("verifiedAt")
            if verified:
                details.body_layout.addWidget(muted_label(f"Rules verified against the sources on {verified}."))
            self.output_layout.addWidget(details)
        usage = payload.get("usage") or {}
        if usage.get("calls"):
            tokens = f" · tokens {usage.get('inputTokens', 0)} → {usage.get('outputTokens', 0)}"
            self.output_layout.addWidget(
                muted_label(f"{usage['calls']} call{'s' if usage['calls'] != 1 else ''}{tokens}")
            )
        self.output_layout.addStretch(1)

    @staticmethod
    def _note(text: str, name: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(True)
        return label

    def _on_edited(self) -> None:
        if self.editor is not None:  # history keeps the edit (HistoryView.prompt_edited)
            self.skillEdited.emit(self.editor.toPlainText())

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
