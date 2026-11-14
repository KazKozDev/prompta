"""The result column: the finished prompts as tabs (zero-shot baseline first), how they were built, the
warnings, and the "What I assumed" card that the window places under the request.

No window: the column reads the request through a callable and reports through signals.
"""

from __future__ import annotations

from html import escape
import re

from collections.abc import Callable

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont, QFontMetrics, QIcon
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from result_view import (
    BLOCK_GAP,
    Disclosure,
    FlowLayout,
    keyed_label,
    muted_label,
    note_chip,
    spec_text,
    split_warnings,
)
from settings_ui import field_label
from theme import PROMPT_TARGETS, ROOT, is_official_source
from widgets import DashedScrollBar, PromptEdit, WrappingField, use_step_scroll


class Wordmark(QLabel):
    """The app name, very large and faint, centred in the empty result area; its size follows the width."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setObjectName("wordmark")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)  # never widens the window
        font = self.font()  # weight and tracking in code: a stylesheet font rule would reset the fitted size
        font.setWeight(QFont.Weight.ExtraBold)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
        self.setFont(font)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        font = self.font()
        font.setPixelSize(100)
        width = QFontMetrics(font).horizontalAdvance(self.text()) or 1
        size = max(40, min(220, int(100 * self.width() * 0.78 / width)))
        if font.pixelSize() != size or self.font().pixelSize() != size:
            font.setPixelSize(size)
            self.setFont(font)


class AssumptionsCard(QFrame):
    """ "What I assumed": the brief's answers and assumptions as editable rows. The Build button reads
    `change_count` (it says Rebuild then) and the run sends `revised_brief` instead of a new brief."""

    change_count: Callable[[], int]
    revised_brief: Callable[[], dict | None]


class ResultColumn(QScrollArea):
    """Everything right of the request. Signals: `assumptionsCard` hands over the card for the request column
    (None when the result it belonged to is gone), `briefEdited` when its edits change, `rebuildRequested` on Enter
    in a card field, `promptEdited(variant, text)` when the user edits a prompt (0 is the zero-shot baseline)."""

    assumptionsCard = pyqtSignal(object)
    briefEdited = pyqtSignal()
    rebuildRequested = pyqtSignal()
    promptEdited = pyqtSignal(int, str)

    def __init__(self, request_text: Callable[[], str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._request_text = request_text
        self.visible_warnings: list[str] = []
        self.prompt_edit: PromptEdit | None = None
        self.question_answers: list[tuple[str, WrappingField]] = []
        self.assumption_rows: list[dict] = []
        self.add_assumption_button: QPushButton | None = None
        self.wordmark: Wordmark | None = None
        self.setObjectName("outputScroll")
        self.setVerticalScrollBar(DashedScrollBar(Qt.Orientation.Vertical, self))
        self.setHorizontalScrollBar(DashedScrollBar(Qt.Orientation.Horizontal, self))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.viewport().setAutoFillBackground(False)
        use_step_scroll(self)
        self.setWidgetResizable(True)
        self.output_holder = QWidget()
        self.output_holder.setObjectName("outputContent")
        self.output_layout = QVBoxLayout(self.output_holder)
        self.output_layout.setContentsMargins(0, 0, 0, 0)
        self.output_layout.setSpacing(10)
        # The scroll area must grow with its content, or the widgets overlap.
        self.output_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.setWidget(self.output_holder)
        self.output_holder.setAutoFillBackground(False)

    def clear(self) -> None:
        def clear(layout: QLayout) -> None:
            while layout.count():
                item = layout.takeAt(0)
                if widget := item.widget():
                    widget.hide()
                    widget.deleteLater()
                elif child := item.layout():
                    clear(child)
                    child.deleteLater()

        clear(self.output_layout)
        self.assumptionsCard.emit(None)  # the questions belong to the result being replaced

    # ── empty result area: the app name, large and faint; results replace it ──
    def show_placeholder(self) -> None:
        self.clear()
        self.output_layout.addStretch(5)  # just above centre
        self.wordmark = Wordmark("PROMPTA")
        self.output_layout.addWidget(self.wordmark)
        slogan = QLabel("THOUGHTS IN. PROMPTS OUT.")  # the field-label lettering: capitals, tracked, medium
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

    def flag_outdated(self, payload: dict, current_version: str) -> None:
        """A saved result built under earlier pipeline rules says so, and how to get a current one."""
        if not current_version or payload.get("promptVersion") == current_version:
            return
        note = QLabel("Built with earlier Prompta rules. Build prompt makes it again with the current ones.")
        note.setObjectName("warn")
        note.setWordWrap(True)
        self.output_layout.insertWidget(0, note)

    def _add_usage(self, payload: dict) -> None:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return
        calls = usage["calls"]
        input_tokens, output_tokens = usage["inputTokens"], usage["outputTokens"]
        tokens = (
            f"{input_tokens:,} input · {output_tokens:,} output tokens"
            if input_tokens or output_tokens
            else "Token counts unavailable"
        )
        label = muted_label(f"{calls} model {'call' if calls == 1 else 'calls'} · {tokens}")
        label.setToolTip(
            "Token counts come from the model provider. Calls count generation attempts, "
            "including format retries. HTTP retries are counted within the same call."
        )
        self.output_layout.addWidget(label)

    def _add_zero_shot(self, payload: dict) -> None:
        text = payload.get("zeroShotPrompt")
        if not text:
            brief = payload.get("brief") or {}
            task = brief.get("goal") or self._request_text()
            if not task:
                return
            text = f"Task:\n{task}"
            if brief.get("input"):
                text += f"\n\nInput:\n{brief['input']}"
            if brief.get("output_format"):
                text += f"\n\nAnswer format:\n{brief['output_format']}"
            if brief.get("audience"):
                text += f"\n\nAudience:\n{brief['audience']}"
            if brief.get("tone"):
                text += f"\n\nTone:\n{brief['tone']}"
            if brief.get("constraints"):
                text += "\n\nConstraints:\n" + "\n".join(brief["constraints"])
            text += "\n\nDo the task directly. Do not invent missing facts; say explicitly which input is missing."
        card = QFrame()
        card.setObjectName("tech")
        details = QVBoxLayout(card)
        details.setContentsMargins(0, 4, 0, 0)
        details.setSpacing(5)
        label = QLabel("Zero-shot")
        label.setObjectName("section")
        details.addWidget(label)
        description = QLabel("Direct task instructions without examples.")
        description.setObjectName("muted")
        description.setWordWrap(True)
        details.addWidget(description)
        self.output_layout.addWidget(card)
        editor = PromptEdit(text, self)
        editor.setAccessibleName("Zero-shot baseline prompt")
        editor.setFixedHeight(260)
        details.addWidget(editor)
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setObjectName("divider")
        self.output_layout.addWidget(divider)
        self.output_layout.addSpacing(14)

    def render_procedure(self, procedure: dict) -> None:
        self.clear()

        technique = procedure["technique"]
        title = QLabel(technique["name"])
        title.setObjectName("goal")
        title.setWordWrap(True)
        self.output_layout.addWidget(title)

        meta = QLabel(f"Source: {procedure['source_ref']}")
        meta.setObjectName("muted")
        meta.setWordWrap(True)
        self.output_layout.addWidget(meta)
        self._add_usage(procedure)
        self._add_zero_shot(procedure)

        explain = QLabel("This is a procedure for data or models. Follow the steps in code or manually.")
        explain.setObjectName("warn")
        explain.setWordWrap(True)
        self.output_layout.addWidget(explain)

        steps = QLabel("\n".join(f"{i}. {step}" for i, step in enumerate(procedure["steps"], 1)))
        steps.setWordWrap(True)
        steps.setObjectName("procedureSteps")
        self.output_layout.addWidget(steps)

        when = QLabel(f"When to use: {procedure['when_to_use']}")
        when.setObjectName("muted")
        when.setWordWrap(True)
        self.output_layout.addWidget(when)

        self.output_layout.addStretch(1)

    # ── result ────────────────────────────────────────────────────
    @staticmethod
    def _heading(text: str, name: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(True)
        return label

    def _zero_shot_text(self, payload: dict) -> str:
        if payload.get("zeroShotPrompt"):
            return payload["zeroShotPrompt"]
        brief = payload.get("brief") or {}
        return f"Task:\n{brief.get('goal') or self._request_text()}"

    def _prompt_view(
        self, prompts: list[tuple[str, str]], target: str | None, zero_shot: str, named_tabs: bool = False
    ) -> QTabWidget:
        """Tabs: Variant 0 is always the zero-shot baseline; the built prompts follow and the first one is selected."""

        def editor(text: str) -> PromptEdit:
            box = PromptEdit(text, self, target)
            box.fit_to_content()
            return box

        tabs = QTabWidget()
        tabs.setObjectName("variantTabs")
        tabs.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)  # paint the card behind the tab row too
        tabs.tabBar().setDrawBase(False)
        # Names are short (≤24 characters); eliding cut them because the bold selected tab measures wider.
        tabs.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        tabs.tabBar().setUsesScrollButtons(True)

        def short(name: str) -> str:
            # "SG-ICL (self-generated ICL)" → "SG-ICL"; the full name stays in the tooltip.
            name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip() or name
            return name if len(name) <= 24 else name[:23].rstrip() + "…"

        names = [short(name) for name, _ in prompts]
        # Technique names tell variants apart; official targets share one name per run, so they keep numbers.
        by_name = named_tabs or (all(names) and len(set(names)) == len(names))
        zero = editor(zero_shot)
        zero.setAccessibleName("Zero-shot baseline prompt")
        tabs.addTab(zero, "Zero-shot" if by_name else "Variant 0")
        tabs.setTabToolTip(0, "Zero-shot: the task stated directly, without a prompting technique")
        self.prompt_edit = editor(prompts[0][1])
        tabs.addTab(self.prompt_edit, names[0] if by_name else "Variant 1")
        for index, (_, prompt) in enumerate(prompts[1:], 2):
            tabs.addTab(editor(prompt), names[index - 1] if by_name else f"Variant {index}")
        for index, (name, _) in enumerate(prompts, 1):
            tabs.setTabToolTip(index, name)

        for index in range(tabs.count()):  # the user's edits go into the saved result
            page = tabs.widget(index)
            page.textChanged.connect(lambda i=index, e=page: self.promptEdited.emit(i, e.toPlainText()))
            base = tabs.tabText(index)
            page.on_edited = lambda edited, i=index, b=base: tabs.setTabText(i, f"{b} •" if edited else b)

        def follow_current(*_: object) -> None:
            # The stack would be as tall as its tallest page: pin it to the tab row + the shown prompt.
            current = tabs.currentWidget()
            if current is not None:
                tabs.setFixedHeight(tabs.tabBar().sizeHint().height() + current.height())

        for index in range(tabs.count()):
            tabs.widget(index).on_height = follow_current
        tabs.currentChanged.connect(follow_current)
        tabs.setCurrentIndex(1)
        follow_current()
        return tabs

    @staticmethod
    def _mark_originals(tabs: QTabWidget, payload: dict) -> None:
        """Tell each prompt block what the model wrote, so edits show as edited (also after reopening)."""
        originals = payload.get("originalPrompts") or {}
        for index in range(tabs.count()):
            editor = tabs.widget(index)
            editor.blockSignals(True)  # marking is not an edit
            editor.set_original(originals.get(str(index), editor.toPlainText()))
            editor.blockSignals(False)
            editor._update_edited()

    ZERO_SHOT_NOTE = (
        "Zero-shot: the task stated directly, without a prompting technique. A baseline to compare the variants with."
    )

    @staticmethod
    def _follow_tabs(tabs: QTabWidget, pages: list[list[QWidget]]) -> None:
        """Show only the selected variant's widgets: no variant's text appears under another tab."""

        def show(index: int) -> None:
            for page_index, widgets in enumerate(pages):
                for widget in widgets:
                    widget.setVisible(page_index == index)

        tabs.currentChanged.connect(show)
        show(tabs.currentIndex())

    @staticmethod
    def _brief_block(brief: dict) -> tuple[QVBoxLayout, FlowLayout]:
        """What was understood: the goal, the format, leftover assumptions and one quiet meta row.
        The meta row is returned so the caller can add its note chips to it."""
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        if brief.get("topic"):  # without a topic the goal is already the heading
            box.addWidget(muted_label(brief["goal"], "briefGoal"))
        box.addWidget(keyed_label("Format", brief["output_format"]))
        for key, title in (
            ("audience", "Audience"),
            ("tone", "Tone"),
        ):  # only what the user stated; guesses are assumptions
            if brief.get(key):
                box.addWidget(keyed_label(title, brief[key]))
        row = FlowLayout()
        meta = muted_label(f"{brief['task_type']} · {brief['stakes']} stakes · {brief['language']}", "briefMeta")
        meta.setWordWrap(False)  # one chip-like run in the flow, not a wrapped column
        row.addWidget(meta)
        box.addSpacing(2)
        box.addLayout(row)
        return box, row

    def _add_brief_refinement(self, brief: dict | None, source_thoughts: str | None) -> None:
        """One card under the request: what the brief assumed, as answers and items the user can change.
        Rebuilding sends the edited brief back, so nothing is re-guessed and no edit is lost."""
        if not brief:
            return
        original_request = source_thoughts if source_thoughts is not None else self._request_text()
        questions = self._brief_questions(brief)
        assumptions = [
            item.strip() for item in brief.get("assumptions") or [] if isinstance(item, str) and item.strip()
        ]
        if not questions and not assumptions:
            return

        box = AssumptionsCard()
        box.setObjectName("questionsCard")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 10, 12, 12)
        layout.setSpacing(0)
        title = QLabel("What I assumed")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        layout.addSpacing(6)

        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        layout.addLayout(body_layout)

        # One list, one kind of row: an editable value, the question it answers (if any) above it, × to drop it.
        rows_layout = QVBoxLayout()
        rows_layout.setSpacing(6)
        body_layout.addLayout(rows_layout)
        rows: list[dict] = []  # {"question": str | None, "original": str | None, "field", "removed": bool, "widget"}
        assumption_rows: list[dict] = []

        def changes() -> int:
            count = 0
            for row in rows:
                text = row["field"].text().strip()
                if row["original"] is None:  # added by the user
                    count += bool(text) and not row["removed"]
                else:
                    count += row["removed"] or text != row["original"]
            return count

        def sync() -> None:
            self.briefEdited.emit()

        def add_row(question: str | None, text: str | None) -> WrappingField:
            line = QWidget()
            line_layout = QVBoxLayout(line)
            line_layout.setContentsMargins(0, 0, 0, 0)
            line_layout.setSpacing(2)
            if question:
                line_layout.addWidget(muted_label(question, "question"))
            value_row = QHBoxLayout()
            value_row.setSpacing(6)
            field = WrappingField(text or "", max_lines=8)  # the whole assumption is visible; the card scrolls
            field.setObjectName("answer")
            field.setPlaceholderText("Your answer (optional)" if question else "Your assumption")
            field.setAccessibleName(question or "Assumption")
            remove = QPushButton()
            remove.setObjectName("removeAssumption")
            remove.setIcon(QIcon(str(ROOT / "desktop" / "close.svg")))
            remove.setIconSize(QSize(10, 10))
            remove.setFixedSize(22, 22)
            remove.setCursor(Qt.CursorShape.PointingHandCursor)
            remove.setToolTip("Drop this assumption" + (" (the question stays open)" if question else ""))
            remove.setAccessibleName("Remove assumption")
            value_row.addWidget(field, 1)
            value_row.addWidget(remove, 0, Qt.AlignmentFlag.AlignTop)
            line_layout.addLayout(value_row)
            row = {"question": question, "original": text, "field": field, "removed": False, "widget": line}

            def drop() -> None:
                row["removed"] = True
                line.hide()
                sync()

            remove.clicked.connect(drop)
            field.textChanged.connect(sync)
            field.returnPressed.connect(apply)
            rows.append(row)
            if question is None:
                assumption_rows.append(row)
            rows_layout.addWidget(line)
            return field

        def add_new() -> None:
            add_row(None, None).setFocus()

        def request_unchanged() -> bool:
            return self._request_text() == original_request

        def change_count() -> int:
            return changes() if request_unchanged() else 0

        def revised_brief() -> dict | None:
            if not change_count():
                return None
            revised_questions = []
            for row in rows:
                if row["question"] is None:
                    continue
                value = "" if row["removed"] else row["field"].text().strip()
                revised_questions.append(
                    {"question": row["question"], "default": value} if value else {"question": row["question"]}
                )
            revised_assumptions = [
                row["field"].text().strip()
                for row in assumption_rows
                if not row["removed"] and row["field"].text().strip()
            ]
            return {**brief, "assumptions": revised_assumptions, "questions": revised_questions}

        def apply() -> None:  # Enter in a card field does what the Build button does
            self.rebuildRequested.emit()

        for question, default in questions:
            add_row(question, default)
        for item in assumptions:
            add_row(None, item)
        add = QPushButton("+ Add assumption")
        add.setObjectName("addAssumption")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(add_new)
        body_layout.addSpacing(2)
        body_layout.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)

        title.setToolTip("The prompt is built on these. Change any of them, then Rebuild: the request is not re-read.")

        box.change_count = change_count
        box.revised_brief = revised_brief
        self.question_answers = [(row["question"], row["field"]) for row in rows if row["question"]]
        self.assumption_rows = assumption_rows
        self.add_assumption_button = add
        self.assumptionsCard.emit(box)

    @staticmethod
    def _brief_questions(brief: dict | None) -> list[tuple[str, str]]:
        """(question, assumed default); older results keep questions as bare strings."""
        out = []
        for item in (brief or {}).get("questions") or []:
            if isinstance(item, str):
                item = {"question": item}
            if not isinstance(item, dict) or not isinstance(item.get("question"), str) or not item["question"].strip():
                continue
            default = item.get("default") if isinstance(item.get("default"), str) else ""
            out.append((item["question"].strip(), default.strip()))
        return out[:3]

    def _rules_line(self, guidance: dict, target: str, rule_ids: list[str]) -> QLabel:
        """One line instead of a rules list plus a sources list: rule names link to their official source."""
        name = guidance.get("target") if target == "openModel" else PROMPT_TARGETS[target][0]
        by_id = {rule.get("id"): rule for rule in guidance.get("rules", [])}
        parts, hints = [], {}
        for rule_id in rule_ids or list(by_id):
            rule = by_id.get(rule_id, {})
            url = rule.get("source_url", "")
            safe = is_official_source(url, target)
            if safe:
                parts.append(f'<a href="{escape(url, quote=True)}">{escape(str(rule_id))}</a>')
                hints[url] = " — ".join(x for x in (rule.get("source_section", ""), rule.get("rule_text", "")) if x)
            else:
                parts.append(escape(str(rule_id)))
        checked = escape(str(guidance.get("verified_at", "unknown")))
        label = QLabel(
            f"Official {escape(str(name))} rules: {' · '.join(parts)}"
            f'<span style="color:#9a8d6c"> · checked {checked}</span>'
        )
        label.setObjectName("muted")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setOpenExternalLinks(True)
        label.setWordWrap(True)
        label.setToolTip(f"Rule set {guidance.get('rule_set_version', 'unknown')}")
        label.linkHovered.connect(
            lambda href: QToolTip.showText(QCursor.pos(), hints.get(href, href), label) if href else None
        )
        return label

    def render_result(self, result: dict, *, source_thoughts: str | None = None) -> None:
        self.clear()
        brief = result["brief"]
        choice = result["choice"]
        synthesis = result["synthesis"]
        alternatives = result.get("alternatives") or []
        source_target = next((key for key in PROMPT_TARGETS if isinstance(result.get(f"{key}Guidance"), dict)), None)
        guidance = result.get(f"{source_target}Guidance") if source_target else None
        layout = self.output_layout

        layout.addWidget(self._heading(brief.get("topic") or brief["goal"], "goal"))

        def meta_for(item_choice: dict) -> str:
            if guidance is not None:
                official = PROMPT_TARGETS[source_target][0] if source_target in PROMPT_TARGETS else ""
                name = guidance.get("target") if source_target == "openModel" else official
                own = item_choice["name"]
                return own if "guidance" in own.lower() else f"{own} · official {name} guidance"
            confidence = item_choice.get("confidence")
            return item_choice["name"] + (
                f" · confidence {round(confidence * 100)}%" if isinstance(confidence, (int, float)) else ""
            )

        metas = ["Zero-shot · baseline without a technique", meta_for(choice)] + [
            meta_for(a["choice"]) for a in alternatives
        ]
        meta_label = muted_label(metas[1], "meta")
        layout.addWidget(meta_label)
        self._add_usage(result)
        layout.addSpacing(10)
        self._add_brief_refinement(brief, source_thoughts)
        prompts = [(choice["name"], synthesis["prompt"])] + [
            (a["choice"]["name"], a["synthesis"]["prompt"]) for a in alternatives
        ]
        tabs = self._prompt_view(prompts, source_target, self._zero_shot_text(result))
        self._mark_originals(tabs, result)
        layout.addWidget(tabs)
        layout.addSpacing(BLOCK_GAP)  # air between the prompt and what follows
        variant_items = [(choice, synthesis)] + [(a["choice"], a["synthesis"]) for a in alternatives]
        pages: list[list[QWidget]] = [[] for _ in range(len(variant_items) + 1)]  # 0 = zero-shot
        self.visible_warnings = []
        variant_notes: list[list[str]] = []
        for page, (_, item) in enumerate(variant_items, 1):
            warnings, notes = split_warnings(item["warnings"])
            self.visible_warnings += [w for w in warnings if w not in self.visible_warnings]
            variant_notes.append(notes)
            if warnings:
                label = muted_label("\n".join(f"• {w}" for w in warnings), "warn")
                layout.addWidget(label)
                pages[page].append(label)

        for page, (_, item) in enumerate(variant_items, 1):  # run settings live in the prompt block itself
            tabs.widget(page).set_spec(*spec_text(item["config"]))

        details = Disclosure("How this prompt was built", expanded=True)
        details.button.hide()  # no header: three blocks separated by air, no toggles
        body = details.body_layout
        body.setSpacing(6)

        # 1 · what was understood
        brief_box, notes_row = self._brief_block(brief)
        body.addLayout(brief_box)
        for page, notes in enumerate(variant_notes, 1):  # pipeline notes stay as chips: they are warnings
            own = [note_chip(note) for note in notes]
            for chip in own:
                notes_row.addWidget(chip)
            pages[page] += own

        # 2 · why this technique, short; the cheaper-method argument folds away
        body.addSpacing(BLOCK_GAP)
        why_head = field_label("What it adds over zero-shot")
        if result.get("rejected"):
            why_head.setToolTip(f"Techniques filtered out: {len(result['rejected'])}")
        body.addWidget(why_head)
        body.addSpacing(4)  # header → text: 10px, as in every section
        zero_note = muted_label(self.ZERO_SHOT_NOTE)
        body.addWidget(zero_note)
        pages[0].append(zero_note)
        guidance_variants = guidance.get("variants", []) if isinstance(guidance, dict) else []
        for page, (item_choice, item) in enumerate(variant_items, 1):
            if isinstance(guidance, dict) and source_target:  # the rules and their sources, in one line
                rule_ids = guidance_variants[page - 1].get("rule_ids", []) if page <= len(guidance_variants) else []
                widgets: list[QWidget] = [self._rules_line(guidance, source_target, rule_ids)]
            else:
                widgets = [muted_label(item_choice["reason"])]
                if item_choice.get("whyNotCheaper"):
                    more = Disclosure("Why not a cheaper method")
                    more.body_layout.addWidget(muted_label(item_choice["whyNotCheaper"]))
                    widgets.append(more)
            for widget in widgets:
                body.addWidget(widget)
            pages[page] += widgets

        layout.addWidget(details)
        layout.addStretch(1)
        self._follow_tabs(tabs, pages)
        tabs.currentChanged.connect(lambda index: meta_label.setText(metas[index]))  # header names the shown technique

    def render_manual(self, manual: dict, *, source_thoughts: str | None = None) -> None:
        self.clear()
        variants = manual.get("variants") or [
            {
                "technique": manual["technique"],
                "prompt": manual["prompt"],
                "config": manual["config"],
                "source_ref": manual["source_ref"],
            }
        ]
        names = [v["technique"]["name"] for v in variants]
        self.output_layout.addWidget(self._heading(manual.get("topic") or names[0], "goal"))
        metas = ["Zero-shot · baseline without a technique"] + [f"{name} · chosen manually" for name in names]
        meta_label = muted_label(metas[1], "meta")
        self.output_layout.addWidget(meta_label)
        self._add_usage(manual)
        self.output_layout.addSpacing(10)
        brief = manual.get("brief") if isinstance(manual.get("brief"), dict) else None
        self._add_brief_refinement(brief, source_thoughts)
        tabs = self._prompt_view(
            [(v["technique"]["name"], v["prompt"]) for v in variants],
            None,
            self._zero_shot_text(manual),
            named_tabs=True,
        )
        self._mark_originals(tabs, manual)
        self.output_layout.addWidget(tabs)
        self.output_layout.addSpacing(BLOCK_GAP)
        failed = manual.get("failed") or []
        self.visible_warnings = [f"{f['name']}: {f['error']}" for f in failed]
        if failed:
            self.output_layout.addWidget(
                muted_label("\n".join(f"• Not built — {w}" for w in self.visible_warnings), "warn")
            )
        for page, variant in enumerate(variants, 1):
            tabs.widget(page).set_spec(*spec_text(variant["config"]))
        details = Disclosure("How this prompt was built", expanded=True)
        details.button.hide()
        body = details.body_layout
        body.setSpacing(6)
        if brief and brief.get("goal") and brief.get("output_format"):
            body.addLayout(self._brief_block(brief)[0])
            body.addSpacing(BLOCK_GAP)
        if any(v.get("why") for v in variants):
            body.addWidget(field_label("What it adds over zero-shot"))
        pages: list[list[QWidget]] = [[muted_label(self.ZERO_SHOT_NOTE)]]
        for variant in variants:
            own: list[QWidget] = [muted_label(variant["why"])] if variant.get("why") else []
            own += [field_label("Method source"), muted_label(variant["source_ref"])]
            pages.append(own)
        for widgets in pages:
            for widget in widgets:
                body.addWidget(widget)
        self.output_layout.addWidget(details)
        self.output_layout.addStretch(1)
        self._follow_tabs(tabs, pages)
        tabs.currentChanged.connect(lambda index: meta_label.setText(metas[index]))
