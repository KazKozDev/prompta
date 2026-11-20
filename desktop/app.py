#!/usr/bin/env python3
"""Prompta — a native macOS app.

PyQt6 UI; the logic is the existing TS pipeline, reached through the desktop/bridge.ts bridge.
History is stored locally; API keys are never written to disk.
"""

from __future__ import annotations

import json
import subprocess
import os
import sys
from pathlib import Path

from history import HistoryStore
from library import LibraryWidget
from mode_guide import placeholder
from run_request import document_status, manual_status, pipeline_status, prompt_request
from settings_ui import field_label
from mcp_settings import McpSettingsWidget

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QPalette, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from theme import COMPATIBLE, FROZEN, PROMPT_TARGETS, QSS, ROOT
from single_instance import SingleInstance, bring_forward

from history_view import HistoryView
from target_selector import TargetSelector
from technique_panel import TechniquePanel
from result_column import AssumptionsCard, ResultColumn
from agent_mode import AgentTargetSelector
from attachments import Attachments
from agent_view import AgentView
from instructions_mode import InstructionTargetSelector
from instructions_view import InstructionsView
from skill_mode import (
    AGENT_MODE,
    INSTRUCTIONS_MODE,
    PROMPT_MODE,
    SKILL_MODE,
    ModeSwitch,
    SurfaceSelector,
)
from skill_view import SkillView
from about_page import AboutPage
from dictation import DictationPage
from generator_settings import GeneratorSettings
from settings_dialog import SettingsDialog
import qt_log
from mac_titlebar import announce_accessibility, paint_all_title_bars

from controls import BackgroundWidget, Card, ExecutionProfileDropdown
from result_view import ACTION_HEIGHT, CONTROL_HEIGHT
from widgets import (
    DashedProgressBar,
    DashedScrollPainter,
    HintFilter,
    PopupAnimation,
    ThoughtsEdit,
    use_step_scroll,
)
from workers import BRIDGE, TechniquesLoader, Worker, fetch_ollama_models, node_binary

# Personal, gitignored. The installed app ships no personal files, so it reads them from Application Support.
LOCAL_PROVIDERS_FILE = (
    Path.home() / "Library" / "Application Support" / "Prompta" / "providers.local.json"
    if FROZEN
    else ROOT / "desktop" / "providers.local.json"
)


# OpenAI-compatible providers the app knows by name; they travel to the pipeline as "openai" + their URL.
# Muse Spark models think before answering; the pipeline keeps that minimal for api.meta.ai (pipeline/llm.ts).
COMPATIBLE_PROVIDERS = {
    "meta": {
        "key": "meta",
        "label": "Meta (Muse Spark)",
        "base_url": "https://api.meta.ai/v1",
        "models": ["muse-spark-1.3-contributor", "muse-spark-1.3"],
        "key_env": "META_API_KEY",
    },
}


def load_local_providers(path: Path = LOCAL_PROVIDERS_FILE) -> dict[str, dict]:
    """Named OpenAI-compatible providers: COMPATIBLE_PROVIDERS plus personal ones from a gitignored file:
    {"providers": [{"key": "groq", "label": "Groq", "base_url": "https://api.groq.com/openai/v1",
    "models": ["..."], "key_env": "GROQ_API_KEY", "api_key": ""}]}. An entry with a known key ("meta")
    overrides its fields, e.g. adds an api_key. The key comes from Keychain first, then key_env, then api_key.
    A missing or broken file adds nothing."""
    found = {key: dict(item) for key, item in COMPATIBLE_PROVIDERS.items()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return found
    builtin = {"ollama", "gemini", "openai", "anthropic", "xai", COMPATIBLE}
    for item in data.get("providers", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        known = found.get(key, {})
        base = str(item.get("base_url") or known.get("base_url") or "").strip()
        if key and key not in builtin and base.startswith(("http://", "https://")):
            models = [m for m in item.get("models", []) if isinstance(m, str) and m]
            found[key] = {
                **known,
                **item,
                "key": key,
                "base_url": base,
                "label": str(item.get("label") or known.get("label") or key),
                "models": models or known.get("models", []),
            }
    return found


def header_button(icon: str, name: str, slot) -> QPushButton:
    """A 28 px icon button in the window header; `name` is its tooltip and accessible name."""
    button = QPushButton()
    button.setObjectName("settings")
    button.setIcon(QIcon(str(ROOT / "desktop" / icon)))
    button.setIconSize(QSize(17, 17))
    button.setFixedSize(28, 28)
    button.setToolTip(name)
    button.setAccessibleName(name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(slot)
    return button


class StatusLabel(QLabel):
    """Show brief feedback without losing the current run status."""

    def __init__(self) -> None:
        super().__init__()
        self._status = ""
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(self._restore_status)

    def setText(self, text: str | None) -> None:  # noqa: N802
        self._notice_timer.stop()
        self._status = text or ""
        self._restore_status()

    def show_notice(self, text: str) -> None:
        super().setText(text)
        self._notice_timer.start(2500)
        announce_accessibility(self.window(), text)

    def _restore_status(self) -> None:
        super().setText(self._status)


class PromptaWindow(QMainWindow):
    """Main window: the finished prompt comes first (variants as tabs); brief, zero-shot baseline,
    technique rationale and sources fold into "How this prompt was built". The target the prompt is
    written for lives in TargetSelector (target_selector.py): requests and history restore go through it."""

    run_button: QPushButton

    def __init__(self) -> None:
        super().__init__()
        app = QApplication.instance()
        if not hasattr(app, "popup_animation_filter"):
            app.popup_animation_filter = PopupAnimation(app)
            app.installEventFilter(app.popup_animation_filter)
            app.dashed_scroll_painter = DashedScrollPainter(app)
            app.installEventFilter(app.dashed_scroll_painter)
            app.setEffectEnabled(Qt.UIEffect.UI_AnimateCombo, False)
            app.setEffectEnabled(Qt.UIEffect.UI_FadeMenu, False)
            app.setEffectEnabled(Qt.UIEffect.UI_AnimateMenu, False)
        self.setWindowTitle("Prompta")
        available = self.screen().availableGeometry()
        self.resize(min(1160, available.width() - 48), min(820, available.height() - 80))
        self.worker: Worker | None = None
        self.history_store = HistoryStore()
        self.history = HistoryView(self.history_store, self._render_history_entry, self)
        self.history.opened.connect(self._on_history_opened)
        self._active_thoughts = ""
        self._discard_result = False

        root = BackgroundWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 3, 12, 2)  # top equals spacing below the header: title sits centred
        outer.setSpacing(3)

        header = QHBoxLayout()
        header.setSpacing(20)
        self.mode_switch = ModeSwitch()
        self.mode_switch.changed.connect(self._apply_mode)
        header.addWidget(self.mode_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)  # the window title already says Prompta
        header.addWidget(self.history.picker)
        self.clear_button = header_button("trash.svg", "Clear thoughts and results", self.clear_workspace)
        header.addWidget(self.clear_button, 0, Qt.AlignmentFlag.AlignVCenter)
        header.setSpacing(8)
        self.settings_button = header_button("settings.svg", "Settings", self.open_settings)
        header.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        input_card = self._build_input()
        input_scroll = QScrollArea()
        self.input_scroll = input_scroll
        input_scroll.setObjectName("inputScroll")
        input_scroll.viewport().setObjectName("inputViewport")
        viewport_palette = input_scroll.viewport().palette()
        viewport_palette.setColor(QPalette.ColorRole.Window, QColor("#f5f6f8"))
        input_scroll.viewport().setPalette(viewport_palette)
        input_scroll.viewport().setAutoFillBackground(False)
        input_scroll.setWidgetResizable(True)
        input_scroll.setFrameShape(QFrame.Shape.NoFrame)
        input_scroll.setMinimumWidth(input_card.minimumSizeHint().width() + 16)
        input_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        input_scroll.setWidget(input_card)
        input_card.setAutoFillBackground(False)
        use_step_scroll(input_scroll)
        splitter.addWidget(input_scroll)
        splitter.addWidget(self._build_output())
        self.settings_dialog = self._build_settings()
        splitter.setSizes([440, 700])
        outer.addWidget(splitter, 1)

        self.status = StatusLabel()
        self.status.setObjectName("status")
        outer.addSpacing(3)  # keep the original 6px above the status line
        outer.addWidget(self.status)
        self.history.load()
        for button in self.findChildren(QPushButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)

        self.generator.changed.connect(self._sync_model_line)
        self.generator.notice.connect(self.status.setText)
        self.generator.restore()  # last provider, model and URLs; loads that provider's models
        self._sync_model_line()
        self.load_techniques()

        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut.activated.connect(self.run_pipeline)
        shortcut2 = QShortcut(QKeySequence("Meta+Return"), self)
        shortcut2.activated.connect(self.run_pipeline)
        self.build_label = "Build prompt   ⌘↵"
        self.run_button.setText(self.build_label)
        self.run_button.setToolTip("⌘↵ builds the prompt")
        self.status.setText("")
        self._fit_input_column()  # the column with the history picker in the header is wider than at construction

    # ── left column ───────────────────────────────────────────────
    def _build_input(self) -> QWidget:
        card = Card()
        card.setObjectName("mainColumn")
        box = card.vbox()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        self.thoughts = ThoughtsEdit()
        self.thoughts.textChanged.connect(lambda: self._sync_build_label())  # an edited request means a fresh build
        QApplication.instance().aboutToQuit.connect(self.thoughts.stop_dictation)
        self.thoughts.setAccessibleName("Thoughts")
        use_step_scroll(self.thoughts)
        self.thoughts.setPlaceholderText(placeholder(PROMPT_MODE))
        thoughts_palette = self.thoughts.palette()
        thoughts_palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9a8c6b"))
        self.thoughts.setPalette(thoughts_palette)
        self.thoughts.setMinimumHeight(90)
        box.addWidget(self.thoughts, 1)
        # Project files every mode reads next to the request; dropping files on the request attaches them too.
        self.attachments = Attachments()
        self.attachments.notice.connect(lambda text: self.status.setText(text))
        self.attachments.changed.connect(self._fit_input_column)
        self.thoughts.filesDropped.connect(self.attachments.add_paths)
        self.thoughts.attachRequested.connect(self.attachments.pick)
        # Which file the model read how depends on the request: an edit makes the last run's labels stale.
        self.thoughts.textChanged.connect(self.attachments.forget_uses)
        box.addWidget(self.attachments)
        # What the brief assumed sits under the request as its own block: natural height, no scroll of its own.
        self.assumptions_slot = QVBoxLayout()
        self.assumptions_slot.setContentsMargins(0, 6, 0, 0)
        box.addLayout(self.assumptions_slot)
        self.mode_cards: dict[str, QWidget | None] = {}  # each mode keeps its own card; only the current one shows

        box.addSpacing(4)

        try:
            open_models = json.loads((ROOT / "open_model_prompt_guides/manifest.json").read_text())["models"]
        except (OSError, ValueError, KeyError, TypeError):
            open_models = []  # the picker then offers any LLM and the official targets only
        self.target_selector = TargetSelector(open_models)
        self.target_picker = self.target_selector.picker
        # Official targets and open-weight models follow their own guidance: the technique catalog is for Any only.
        self.target_selector.changed.connect(lambda: self.technique_panel.set_target(self.target_selector.target()))
        box.addWidget(self.target_selector)
        self.surface_selector = SurfaceSelector()  # Skill mode only: replaces the prompt controls
        self.surface_selector.hide()
        box.addWidget(self.surface_selector)
        self.instruction_target = InstructionTargetSelector()  # Project mode only
        self.instruction_target.hide()
        box.addWidget(self.instruction_target)
        self.agent_target = AgentTargetSelector()  # Agent mode only
        self.agent_target.hide()
        box.addWidget(self.agent_target)
        # Where the prompt goes and where it runs belong together: right under the target switch.
        # Where it runs decides which tool steps the prompt may rely on.
        runs_in = QVBoxLayout()
        runs_in.setContentsMargins(0, 6, 0, 2)  # 16px rows: Written for → Runs in → Technique
        runs_in.setSpacing(8)
        self.runs_in_label = field_label("Runs in")
        runs_in.addWidget(self.runs_in_label)
        self.execution_profile = ExecutionProfileDropdown()
        self.execution_profile.setAccessibleName("Where will the prompt run?")
        self.execution_profile.setToolTip(
            "Where the generated prompt will be used. Tool steps in the prompt follow what that environment can do."
        )
        self.execution_profile.ensurePolished()  # its own stylesheet would reset the height when polished later
        self.execution_profile.setFixedHeight(CONTROL_HEIGHT)
        runs_in.addWidget(self.execution_profile)
        box.addLayout(runs_in)

        box.addSpacing(4)
        self.technique_panel = TechniquePanel()
        self.technique = self.technique_panel.technique
        self.variants = self.technique_panel.variants
        box.addWidget(self.technique_panel)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.build_label = "Build prompt"
        self.run_button = QPushButton(self.build_label)
        self.run_button.setObjectName("buildPrompt")
        self.run_button.setFixedHeight(ACTION_HEIGHT)
        # While a run is going the same button stops it.
        self.run_button.clicked.connect(lambda: self.cancel_run() if self._running() else self.run_pipeline())
        actions.addWidget(self.run_button, 1)

        # The button sits 5px closer to the blocks above it, and the model line 5px closer to the button,
        # than the column's usual spacing.
        build_block = QVBoxLayout()
        build_block.setSpacing(max(0, box.spacing() - 5))
        build_block.addLayout(actions)
        box.addSpacing(-5)
        box.addLayout(build_block)
        # Which model writes the prompt, visible without opening Settings.
        self.model_line = QPushButton()
        self.model_line.setObjectName("modelLine")
        self.model_line.setCursor(Qt.CursorShape.PointingHandCursor)
        self.model_line.setToolTip("The model that writes the prompt · click to change it in Settings")
        self.model_line.clicked.connect(self.open_settings)
        build_block.addWidget(self.model_line, 0, Qt.AlignmentFlag.AlignLeft)
        self.generation_progress = DashedProgressBar()
        self.generation_progress.setObjectName("generationProgress")
        self.generation_progress.setAccessibleName("Prompt generation in progress")
        self.generation_progress.setTextVisible(False)
        self.generation_progress.setRange(0, 100)
        self.generation_progress.setValue(0)
        policy = self.generation_progress.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.generation_progress.setSizePolicy(policy)
        self.generation_progress.hide()
        box.addWidget(self.generation_progress)

        return card

    APP_VERSION = "0.1.0"
    AUTHOR = "KazKozDev"
    AUTHOR_URL = "https://github.com/KazKozDev"

    # ── right column ──────────────────────────────────────────────
    def _build_output(self) -> QWidget:
        card = Card()
        card.setObjectName("mainColumn")
        box = card.vbox()
        box.setContentsMargins(16, 0, 0, 0)

        history_row = QHBoxLayout()
        history_row.setSpacing(8)
        history_row.addWidget(self.history.combo, 1)  # hidden: it still drives restore
        box.addLayout(history_row)
        box.addSpacing(8)
        box.addWidget(self.history.notice)

        self.result_column = ResultColumn(lambda: self.thoughts.toPlainText().strip())
        self.result_column.assumptionsCard.connect(lambda card: self._on_assumptions_card(card, PROMPT_MODE))
        self.result_column.briefEdited.connect(lambda: self._sync_build_label())
        self.result_column.rebuildRequested.connect(lambda: self.run_pipeline())
        self.result_column.promptEdited.connect(self.history.prompt_edited)  # edits go into the saved result
        self.result_column.promptCopied.connect(lambda text: self.status.show_notice(text))
        box.addWidget(self.result_column, 1)
        request_text = lambda: self.thoughts.toPlainText().strip()  # noqa: E731
        self.skill_view = SkillView(request_text)
        self.skill_view.textEdited.connect(lambda text: self.history.prompt_edited(0, text))
        self.skill_view.hide()
        box.addWidget(self.skill_view, 1)
        self.instructions_view = InstructionsView(request_text)
        self.instructions_view.textEdited.connect(lambda text: self.history.prompt_edited(0, text))
        self.instructions_view.hide()
        box.addWidget(self.instructions_view, 1)
        self.agent_view = AgentView(request_text)
        self.agent_view.textEdited.connect(lambda text: self.history.prompt_edited(0, text))
        self.agent_view.hide()
        box.addWidget(self.agent_view, 1)
        file_views = (
            (SKILL_MODE, self.skill_view),
            (INSTRUCTIONS_MODE, self.instructions_view),
            (AGENT_MODE, self.agent_view),
        )
        for mode, view in file_views:
            view.assumptionsCard.connect(lambda card, m=mode: self._on_assumptions_card(card, m))
            view.briefEdited.connect(lambda: self._sync_build_label())
            view.rebuildRequested.connect(lambda: self.run_pipeline())

        self.result_column.show_placeholder()
        self.skill_view.show_placeholder()
        self.instructions_view.show_placeholder()
        self.agent_view.show_placeholder()
        return card

    # ── settings ──────────────────────────────────────────────────
    def _build_settings(self) -> SettingsDialog:
        dialog = SettingsDialog(self)
        self.generator = GeneratorSettings(load_local_providers())
        dialog.add_page(self.generator, "Model && API", focus=self.generator.api_key)
        self.library = LibraryWidget(ROOT)
        dialog.add_page(
            self.library, "Library", footer=self.library.summary, on_show=self.library.reload, focus=self.library.search
        )
        self.mcp_settings = McpSettingsWidget(
            ROOT, node_binary, field_label, self.generator.for_mcp, self.generator.key_missing_for_mcp
        )
        mcp_scroll = QScrollArea()  # the apps list is taller than the dialog: scroll, don't squeeze rows
        mcp_scroll.setWidgetResizable(True)
        mcp_scroll.setFrameShape(QFrame.Shape.NoFrame)
        mcp_scroll.setObjectName("clearScroll")
        mcp_scroll.setWidget(self.mcp_settings)
        use_step_scroll(mcp_scroll)
        dialog.add_page(
            mcp_scroll, "MCP server", footer=self.mcp_settings.copy_button, on_show=self.mcp_settings.refresh
        )
        dialog.add_page(self.history.page, "History", footer=self.history.delete_all_button)
        self.history.leaveSettings.connect(dialog.accept)
        self.dictation = DictationPage(lambda: self.thoughts.voice_process is not None)
        dialog.add_page(self.dictation, "Dictation", on_show=self.dictation.refresh)
        self.thoughts.dictationSetupRequested.connect(self.open_dictation_settings)
        QApplication.instance().aboutToQuit.connect(self.dictation.download.cancel)  # no .part folder left behind
        self.about = AboutPage(self.APP_VERSION, self.AUTHOR, self.AUTHOR_URL)
        dialog.add_page(self.about, "About", footer=self.about.footer, backdrop=True)
        return dialog

    def open_settings(self) -> None:
        self.settings_dialog.open()

    def open_dictation_settings(self) -> None:
        self.settings_dialog.tabs.setCurrentWidget(self.dictation)
        self.settings_dialog.open()

    def load_techniques(self) -> None:
        self.techniques_loader = TechniquesLoader()
        self.techniques_loader.loaded.connect(self._on_techniques_loaded)
        self.techniques_loader.start()

    def _on_techniques_loaded(self, techniques: list) -> None:
        loader = getattr(self, "techniques_loader", None)
        self.prompt_version = getattr(loader, "prompt_version", "") or getattr(self, "prompt_version", "")
        self.technique_panel.set_techniques(techniques)

    def _on_assumptions_card(self, card: QWidget | None, mode: str = PROMPT_MODE) -> None:
        self._set_assumptions_card(card, mode)
        self._sync_build_label()

    def _current_mode(self) -> str:
        switch = getattr(self, "mode_switch", None)
        return switch.mode() if switch is not None else PROMPT_MODE

    @property
    def assumptions_card(self) -> QWidget | None:
        """The card of the mode on screen: Build reads only that one."""
        return self.mode_cards.get(self._current_mode())

    @assumptions_card.setter
    def assumptions_card(self, card: QWidget | None) -> None:
        self.mode_cards[self._current_mode()] = card

    # ── run ───────────────────────────────────────────────────────
    def clear_workspace(self) -> None:
        self._discard_result = True
        running = self.worker is not None and self.worker.isRunning()
        if running:
            self.worker.cancel()
        self.thoughts.stop_dictation()
        self.thoughts.clear()
        self.attachments.clear()
        self.thoughts.setToolTip("")
        self._active_thoughts = ""
        self.history.deselect()
        self.result_column.show_placeholder()
        self.skill_view.show_placeholder()
        self.instructions_view.show_placeholder()
        self.agent_view.show_placeholder()
        self.generation_progress.hide()
        self.generation_progress.setValue(0)
        self._set_running(running)
        self.status.setText("")
        self.thoughts.setFocus()

    def _sync_model_line(self) -> None:
        self.model_line.setText(self.generator.model_line())

    def _running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _set_running(self, running: bool) -> None:
        self.run_button.setEnabled(True)
        self.run_button.setToolTip("Stop this run" if running else "⌘↵ builds the prompt")
        if running:
            self.run_button.setText("Stop")
        else:
            self._sync_build_label(force=True)  # the finished signal arrives while the thread still counts as running

    def cancel_run(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.status.setText("Cancelling")

    def _set_assumptions_card(self, card: QWidget | None, mode: str = PROMPT_MODE) -> None:
        old = self.mode_cards.get(mode)
        if old is not None and old is not card:
            old.hide()
            old.deleteLater()
        self.mode_cards[mode] = card
        if card is not None:
            self.assumptions_slot.addWidget(card)
            card.setVisible(mode == self._current_mode())
        self._fit_input_column()

    def _fit_input_column(self) -> None:
        """The left column may not shrink below its content, or the right edge (× buttons, microphone) is cut off."""
        scroll = getattr(self, "input_scroll", None)
        if scroll is not None and scroll.widget() is not None:
            scroll.setMinimumWidth(scroll.widget().minimumSizeHint().width() + 16)

    def _card_revision(self) -> dict | None:
        """The edited brief from the assumptions card, if the user changed it and the request
        is the one it belongs to."""
        card = self.assumptions_card
        revise = getattr(card, "revised_brief", None)
        return revise() if revise is not None else None

    def _sync_build_label(self, force: bool = False) -> None:
        """One button: it says Rebuild when the card has edits, so the user knows the request is not re-read."""
        if not hasattr(self, "run_button"):
            return
        if not force and self._running():
            return  # the button says Stop until the run ends
        card = self.assumptions_card  # the current mode's card: another mode's edits do not change this button
        count = card.change_count() if card is not None and hasattr(card, "change_count") else 0
        base = getattr(self, "build_label", "Build prompt")
        _, gap, shortcut = base.partition("   ")  # "Build skill   ⌘↵": keep the shortcut, whatever the label
        rebuild = f"Rebuild · {count} change{'s' if count != 1 else ''}{gap}{shortcut}"
        if self._prompt_mode() and isinstance(card, AssumptionsCard) and card.has_edited_answers():
            rebuild = f"Rebuild with your answers{gap}{shortcut}"
        self.run_button.setText(rebuild if count else base)

    def _prompt_mode(self) -> bool:
        return self.mode_switch.mode() == PROMPT_MODE

    def _mode_view(self):
        """The result area of the current mode."""
        views = {SKILL_MODE: self.skill_view, INSTRUCTIONS_MODE: self.instructions_view, AGENT_MODE: self.agent_view}
        return views.get(self.mode_switch.mode(), self.result_column)

    def _apply_mode(self, mode: str) -> None:
        """File modes (Skill, Project, Agent) swap the prompt controls and result; each keeps its state."""
        prompt = mode == PROMPT_MODE
        for widget in (self.target_selector, self.runs_in_label, self.execution_profile, self.technique_panel):
            widget.setVisible(prompt)
        for card_mode, card in self.mode_cards.items():
            if card is not None:
                card.setVisible(card_mode == mode)
        self.attachments.set_material(prompt)
        self.surface_selector.setVisible(mode == SKILL_MODE)
        self.instruction_target.setVisible(mode == INSTRUCTIONS_MODE)
        self.agent_target.setVisible(mode == AGENT_MODE)
        self.result_column.setVisible(prompt)
        self.skill_view.setVisible(mode == SKILL_MODE)
        self.instructions_view.setVisible(mode == INSTRUCTIONS_MODE)
        self.agent_view.setVisible(mode == AGENT_MODE)
        label = {SKILL_MODE: "Build skill", INSTRUCTIONS_MODE: "Build file", AGENT_MODE: "Build subagent"}.get(
            mode, "Build prompt"
        )
        self.build_label = label + "   ⌘↵"
        self.thoughts.setPlaceholderText(placeholder(mode))
        self._sync_build_label()
        self._fit_input_column()

    def _files_field(self) -> dict:
        """The attached project files for the bridge; no field at all when none are attached."""
        files = self.attachments.files()
        return {"files": files} if files else {}

    def _run_document(self, thoughts: str, generator: dict, revised: dict | None = None) -> None:
        """Skill, Project or Agent mode: one bridge request that writes a file instead of a prompt.
        `revised` is the edited card: the file is rewritten on it and the request is not asked about again."""
        request: dict[str, object]
        if self.mode_switch.mode() == SKILL_MODE:
            request = {"skill": self.surface_selector.surface()}
            status = "Writing SKILL.md from the official skill rules"
        elif self.mode_switch.mode() == AGENT_MODE:
            request = {"agent": self.agent_target.target()}
            status = "Writing the subagent from the official rules"
        else:
            request = {"instructions": self.instruction_target.target()}
            status = "Writing project instructions from the official rules"
        self._set_running(True)
        self.generation_progress.setValue(0)
        self.generation_progress.show()
        self.status.setText(status)
        if revised is not None:
            request["clarify"] = revised
        self._rebuilding_brief = revised is not None
        self._active_thoughts = thoughts
        self._discard_result = False
        self.worker = Worker({"thoughts": thoughts, **generator, **request, **self._files_field()})
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.start()

    def run_pipeline(self, *, revised_brief: dict | None = None) -> None:
        if self.worker and self.worker.isRunning():
            return
        if revised_brief is None:
            revised_brief = self._card_revision()  # edited assumptions rebuild from the brief, not a new one

        thoughts = self.thoughts.toPlainText().strip()
        if not thoughts:
            self.status.setText("Enter your thoughts")
            return

        generator, missing = self.generator.request()
        if missing:
            self.status.setText(missing)
            return
        if not self._prompt_mode():
            self._run_document(thoughts, generator, revised_brief)
            return

        payload = prompt_request(
            thoughts,
            generator,
            target=self.target_selector.request_field(),
            variants=self.variants.value(),
            files=self._files_field(),
            profile=self.execution_profile.current_key(),
            agent_capabilities=self.execution_profile.AGENT_CAPABILITIES,
            technique_keys=self.technique_panel.technique_keys(),
            revised_brief=revised_brief,
        )

        self._set_running(True)
        self.generation_progress.setValue(0)
        self.generation_progress.show()
        selected = self.target_selector.target()
        target_label = (
            self.target_selector.open_model_label()
            if selected == "openModel"
            else PROMPT_TARGETS[selected][0]
            if selected
            else ""
        )
        if selected:
            self.status.setText(f"Loading guidance for {target_label}…")
        elif revised_brief is not None:
            self.status.setText("Using your revised brief…")
        else:
            self.status.setText("Reading your request…")

        self._rebuilding_brief = revised_brief is not None
        self._active_thoughts = thoughts
        self._discard_result = False
        self.worker = Worker(payload)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.start()

    def on_progress(self, percent: int, stage: str) -> None:
        if self._discard_result:
            return
        if self.generation_progress.isHidden() or (self.worker and self.worker.cancelled is True):
            return
        if percent < self.generation_progress.value():
            return
        self.generation_progress.setValue(min(99, percent))
        self.status.setText(stage)

    def on_finished(self, data: dict) -> None:
        if self._discard_result:
            self._set_running(False)
            return
        if data.get("ok"):
            self.generation_progress.setValue(100)
            self.status.setText("Done")
        else:
            self.generation_progress.hide()
        self._set_running(False)
        if data.get("ok") and "filesUsed" in data and self.thoughts.toPlainText().strip() == self._active_thoughts:
            self.attachments.set_uses(data["filesUsed"])  # only while the request is still the one the run read
        if not data.get("ok"):
            if getattr(self, "_rebuilding_brief", False):
                self.status.setText(f"Rebuild failed: {data.get('error', 'unknown error')}")
                return
            self._mode_view().show_error(data.get("error", "unknown error"))
            self.status.setText("Error")
            return

        if data.get("skill"):
            skill = data["skill"]
            self.skill_view.render_skill(skill, source_thoughts=self._active_thoughts)
            self._save_result(skill.get("name") or "SKILL.md", "skill", skill)
            self.status.setText(document_status(str(skill.get("name")), "SKILL.md", skill.get("check")))
            return

        if data.get("instructions"):
            instructions = data["instructions"]
            self.instructions_view.render_instructions(instructions, source_thoughts=self._active_thoughts)
            file_name = instructions.get("fileName") or "AGENTS.md"
            self._save_result(file_name, "instructions", instructions)
            self.status.setText(document_status(file_name, file_name, instructions.get("check")))
            return

        if data.get("agent"):
            agent = data["agent"]
            self.agent_view.render_agent(agent, source_thoughts=self._active_thoughts)
            file_name = agent.get("fileName") or "agent"
            self._save_result(agent.get("name") or file_name, "agent", agent)
            self.status.setText(document_status(file_name, file_name, agent.get("check")))
            return

        if data.get("procedure"):
            self.result_column.render_procedure(data["procedure"])
            self._save_result(data["procedure"]["technique"]["name"], "procedure", data["procedure"])
            self.status.setText(f"{data['procedure']['technique']['name']} · procedure, no prompt")
            return

        if data.get("manual"):
            self.result_column.render_manual(data["manual"], source_thoughts=self._active_thoughts)
            self._save_result(data["manual"]["technique"]["name"], "manual", data["manual"])
            self.status.setText(manual_status(data["manual"]))
            return

        self.result_column.render_result(data["result"], source_thoughts=self._active_thoughts)
        self._save_result(data["result"]["choice"]["name"], "pipeline", data["result"])
        self.status.setText(pipeline_status(data["result"]["choice"]["name"], len(self.result_column.visible_warnings)))

    # ── history ───────────────────────────────────────────────────
    def _save_result(self, label: str, kind: str, payload: dict) -> None:
        self.history.push(label, kind, self._active_thoughts or self.thoughts.toPlainText().strip(), payload)

    def _render_history_entry(self, entry: dict) -> None:
        """Show a saved result; raises KeyError, TypeError or ValueError for data it cannot show."""
        kind, payload = entry["kind"], entry["payload"]
        self.thoughts.setPlainText(entry["thoughts"])
        modes = {"skill": SKILL_MODE, "instructions": INSTRUCTIONS_MODE, "agent": AGENT_MODE}
        self.mode_switch.set_mode(modes.get(kind, PROMPT_MODE))
        if kind == "skill":
            self.surface_selector.set_surface(payload.get("surface", "portable"))
            self.skill_view.render_skill(payload, source_thoughts=entry["thoughts"])
        elif kind == "instructions":
            self.instruction_target.set_target(payload.get("target", "agentsMd"))
            self.instructions_view.render_instructions(payload, source_thoughts=entry["thoughts"])
        elif kind == "agent":
            self.agent_target.set_target(payload.get("target", "claudeCode"))
            self.agent_view.render_agent(payload, source_thoughts=entry["thoughts"])
        elif kind == "manual":
            self.result_column.render_manual(payload)
        elif kind == "procedure":
            self.result_column.render_procedure(payload)
        else:
            self.result_column.render_result(payload)

    def _on_history_opened(self, entry: dict) -> None:
        if entry.get("kind") in ("skill", "instructions", "agent"):
            return  # a file has no prompt version or target: leave the prompt side as it was
        payload = entry["payload"]
        self.thoughts.setPlainText(entry["thoughts"])
        self.result_column.flag_outdated(payload, getattr(self, "prompt_version", ""))
        selected = next((key for key in PROMPT_TARGETS if payload.get(f"{key}Guidance")), None)
        open_model = ""
        if selected == "openModel":  # history keeps the model's name; a model gone from the manifest means any LLM
            open_model = self.target_selector.open_model_id(str(payload["openModelGuidance"].get("target", "")))
        self.target_selector.set_target(selected, open_model)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.history.flush_edits()  # do not lose the last keystrokes on quit
        super().closeEvent(event)


# Flat, borderless controls: soft translucent fills, a focus ring only when focused,
# iOS-style segmented tracks. Applied last so it overrides the older bordered look.


def demo_result() -> dict:
    """A fixed result for screenshots (--screenshot, screenshots.py): two variants, questions, assumptions."""
    return {
        "brief": {
            "goal": "Extract decisions, tasks, and owners from meeting notes into a table",
            "task_type": "extraction",
            "language": "en",
            "stakes": "high",
            "output_format": "Markdown table: Type | Item | Owner",
            "assumptions": ["Notes are provided as text rather than audio"],
            "questions": [
                {"question": "Which meeting types are in scope?", "default": "all internal meetings"},
                {"question": "Should owners be names or roles?", "default": "names as written in the notes"},
            ],
        },
        "choice": {
            "name": "Contextual prompting",
            "key": "contextual_prompting",
            "confidence": 0.82,
            "reason": "The task is grounded in supplied notes and limited to their contents.",
            "whyNotCheaper": "Zero-shot may miss the table format; few-shot needs examples not supplied in the brief.",
        },
        "synthesis": {
            "prompt": (
                "Use ONLY the material below. Cite [n] for every claim.\n\n[1] meeting notes\n\n"
                "Task: extract items from the notes into a table\nOutput: Markdown table"
            ),
            "config": {
                "temperature": 0.2,
                "top_p": 0.95,
                "max_tokens": "1024",
                "rationale": "Low temperature supports consistent formatting and instruction following.",
            },
            "warnings": [],
        },
        "alternatives": [
            {
                "choice": {
                    "name": "Few-shot (one-shot)",
                    "key": "few_shot",
                    "confidence": 0.64,
                    "reason": "Examples establish the required table format more reliably than instructions alone.",
                    "whyNotCheaper": "Zero-shot may not preserve the required format.",
                },
                "synthesis": {
                    "prompt": (
                        "Task: extract items from the notes into a table.\n\nExample 1:\n"
                        "Input: Prepare the report by Friday\nOutput: | Prepare report | Owner | Friday |\n\n"
                        "Input: INSERT HERE: meeting notes\nOutput:"
                    ),
                    "config": {"temperature": 0.2, "top_p": 0.95, "max_tokens": "1024"},
                    "warnings": [],
                    "rationale": "Low temperature keeps output formats consistent.",
                },
            }
        ],
        "rejected": [{}] * 53,
    }


def make_app(argv: list[str]) -> QApplication:
    """The QApplication with the app's palette, stylesheet and hover hints (main() and screenshots.py)."""
    app = QApplication(argv)
    app.setApplicationName("Prompta")
    app.setWindowIcon(QIcon(str(ROOT / "desktop" / "icon.png")))
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#f4ca38"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#352b10"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#80620a"))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor("#80620a"))
    app.setPalette(palette)
    app.setStyleSheet(QSS)
    hint_filter = HintFilter(app)  # our own hover hints instead of the black-framed system ones
    app.hint_filter = hint_filter  # type: ignore[attr-defined]  # widgets look it up by this name
    app.installEventFilter(hint_filter)
    paint_all_title_bars(app)  # dark graphite title bar on every window; app.qss only styles the content
    return app


def main() -> int:
    if "--voice-worker" in sys.argv:
        # The standalone app runs its Whisper worker as itself; first, before a QApplication or the
        # single-instance check, which would add a Dock icon or hand off to the running copy.
        import voice_input

        return voice_input.run()
    qt_log.install()  # silences only the known macOS accessibility-bridge noise; PROMPTA_QT_DEBUG=1 shows everything
    app = make_app(sys.argv)
    screenshot = "--screenshot" in sys.argv
    instance = SingleInstance()
    if not screenshot and not instance.claim():
        return 0  # the running copy comes forward instead
    window = PromptaWindow()
    instance.activated.connect(lambda: bring_forward(window))
    window.show()

    if screenshot:
        # Layout self-check: render a demo result and save the window as PNG.
        index = sys.argv.index("--screenshot")
        path = sys.argv[index + 1] if len(sys.argv) > index + 1 else "/tmp/app.png"
        window.thoughts.setPlainText(
            "I want AI to review my meeting notes and extract decisions, tasks, and owners into a table"
        )
        window.generator._on_models_loaded(fetch_ollama_models())
        # the screenshot needs the techniques too: fetch them synchronously through the bridge
        try:
            proc = subprocess.run(
                [node_binary(), str(BRIDGE)],
                input=json.dumps({"thoughts": "x", "listTechniques": True, "model": "dummy"}),
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(ROOT),
            )
            window._on_techniques_loaded(json.loads(proc.stdout or "{}").get("techniques", []))
        except (OSError, subprocess.SubprocessError, ValueError):
            pass  # the demo window still shows its result without the technique list
        window.result_column.render_result(demo_result())
        window.status.setText("Contextual prompting · ready")  # what on_finished shows for a result without warnings
        window.resize(1160, 1180)
        for _ in range(10):  # let the prompt card's fixed height settle into the layout
            app.processEvents()
        window.grab().save(path)

        if "--screenshot-popup" in sys.argv:
            popup_index = sys.argv.index("--screenshot-popup")
            popup_path = sys.argv[popup_index + 1] if len(sys.argv) > popup_index + 1 else "/tmp/popup.png"
            base = popup_path.rsplit(".", 1)[0]
            for name, widget in (
                ("provider", window.generator.provider),
                ("model", window.generator.model),
                ("technique", window.technique),
            ):
                widget._open()
                app.processEvents()
                if widget._popup is not None:
                    widget._popup.grab().save(f"{base}-{name}.png")
                    widget._popup.close()
            print(f"popups: {base}-*.png")
        print(f"screenshot: {path}")
        return 0

    code = app.exec()
    # Python's own teardown of the PyQt objects crashes in dealloc_QApplication (SIGBUS in sip_api_visit_wrappers):
    # every quit left a crash report and macOS said the app quit unexpectedly. Nothing is left to save by now:
    # closeEvent flushed the history, aboutToQuit stopped dictation and downloads, and each prefs() call has
    # written its value. So leave without that teardown.
    if instance.server is not None:
        instance.server.close()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    sys.exit(main())
