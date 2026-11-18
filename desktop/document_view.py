"""The result area for modes that write one file instead of a prompt (Skill, Project, Subagent): the file in an
editable block, its check, the official rules it was written from, a save link and the usage line. What the
request left open goes to the window as the same "What I assumed" card a prompt has."""

from __future__ import annotations

from collections.abc import Callable
from html import escape

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLabel, QLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from result_column import Wordmark, brief_card
from result_view import Disclosure, muted_label
from settings_ui import text_link
from widgets import DashedScrollBar, PromptEdit, use_step_scroll


class DocumentView(QScrollArea):
    """Same frame as ResultColumn. `textEdited(text)` fires when the user edits the file; `assumptionsCard`,
    `briefEdited` and `rebuildRequested` work as ResultColumn's do, for the file's questions and assumptions."""

    textEdited = pyqtSignal(str)
    assumptionsCard = pyqtSignal(object)
    briefEdited = pyqtSignal()
    rebuildRequested = pyqtSignal()
    SLOGAN = "THOUGHTS IN. FILES OUT."

    def __init__(self, request_text: Callable[[], str] = lambda: "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._request_text = request_text
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
        self.assumptionsCard.emit(None)  # the questions belong to the file being replaced

    def show_placeholder(self) -> None:
        self.clear()
        self.payload = {}
        self.output_layout.addStretch(5)
        self.output_layout.addWidget(Wordmark("PROMPTA"))
        slogan = QLabel(self.SLOGAN)
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

    def render_document(
        self,
        payload: dict,
        *,
        title: str,
        status: str,
        text: str,
        file_label: str,
        save_label: str,
        save_tip: str,
        on_save: Callable[[], None],
        source_thoughts: str | None = None,
    ) -> None:
        """Title, status line, check notes, the editable file, the save link, the rules and the usage;
        the questions and assumptions it was written on go to the window as a card."""
        self.clear()
        self.payload = payload
        clarify = payload.get("clarify") if isinstance(payload.get("clarify"), dict) else None
        card = brief_card(
            clarify,
            source_thoughts if source_thoughts is not None else self._request_text(),
            self._request_text,
            self.briefEdited.emit,
            self.rebuildRequested.emit,
            built="file",
        )
        if card is not None:
            self.assumptionsCard.emit(card)
        check = payload.get("check") or {}
        heading = QLabel(title)
        heading.setObjectName("goal")
        heading.setWordWrap(True)
        self.output_layout.addWidget(heading)
        self.output_layout.addWidget(muted_label(status))
        for error in check.get("errors") or []:
            self.output_layout.addWidget(self._note(error, "error"))
        for warning in check.get("warnings") or []:
            self.output_layout.addWidget(self._note(warning, "warn"))

        self.editor = PromptEdit(text, self)
        self.editor.setAccessibleName(file_label)
        self.editor.copy_button.setToolTip(f"Copy {file_label}")
        self.editor.copy_button.setAccessibleName(f"Copy {file_label}")
        self.editor.fit_to_content()
        self.editor.textChanged.connect(self._on_edited)
        self.output_layout.addWidget(self.editor)

        save = text_link(save_label)
        save.setToolTip(save_tip)
        save.clicked.connect(on_save)
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
            self.textEdited.emit(self.editor.toPlainText())
