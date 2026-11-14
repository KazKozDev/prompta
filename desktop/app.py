#!/usr/bin/env python3
"""Prompta — a native macOS app.

PyQt6 UI; the logic is the existing TS pipeline, reached through the desktop/bridge.ts bridge.
History is stored locally; API keys are never written to disk.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from history import HistoryStore
from library import LibraryWidget
from settings_ui import field_label
from mcp_settings import McpSettingsWidget

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QPalette, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from theme import COMPATIBLE, PROMPT_TARGETS, QSS, ROOT
from single_instance import SingleInstance, bring_forward

from history_view import HistoryView
from target_selector import TargetSelector
from technique_panel import TechniquePanel
from result_column import ResultColumn
from about_page import AboutPage
from generator_settings import GeneratorSettings
from settings_dialog import SettingsDialog
import qt_log
from mac_titlebar import paint_title_bar

from controls import BackgroundWidget, Card, ExecutionProfileDropdown
from result_view import ACTION_HEIGHT, CONTROL_HEIGHT
from widgets import (
    DashedScrollPainter,
    HintFilter,
    PopupAnimation,
    ThoughtsEdit,
    use_step_scroll,
)
from workers import BRIDGE, TechniquesLoader, Worker, fetch_ollama_models, node_binary

LOCAL_PROVIDERS_FILE = ROOT / "desktop" / "providers.local.json"  # personal, gitignored


def load_local_providers(path: Path = LOCAL_PROVIDERS_FILE) -> dict[str, dict]:
    """Personal OpenAI-compatible providers from a gitignored file, e.g. Meta's Muse Spark:
    {"providers": [{"key": "meta", "label": "Meta (Muse Spark)", "base_url": "https://api.meta.ai/v1",
    "models": ["muse-spark-1.3"], "key_env": "META_API_KEY", "api_key": ""}]}.
    The key comes from Keychain first, then key_env, then api_key. A missing or broken file adds nothing."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    found = {}
    builtin = {"ollama", "gemini", "openai", "anthropic", "xai", COMPATIBLE}
    for item in data.get("providers", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        key, base = str(item.get("key", "")).strip(), str(item.get("base_url", "")).strip()
        if key and key not in builtin and base.startswith(("http://", "https://")):
            found[key] = {
                **item,
                "key": key,
                "base_url": base,
                "label": str(item.get("label") or key),
                "models": [m for m in item.get("models", []) if isinstance(m, str) and m],
            }
    return found


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
        outer.setContentsMargins(24, 3, 12, 6)  # top equals spacing below the header: title sits centred
        outer.setSpacing(3)

        header = QHBoxLayout()
        header.setSpacing(20)
        header.addStretch(1)  # the window title already says Prompta
        header.addWidget(self.history.picker)
        self.clear_button = QPushButton()
        self.clear_button.setObjectName("settings")
        self.clear_button.setIcon(QIcon(str(ROOT / "desktop/trash.svg")))
        self.clear_button.setIconSize(QSize(17, 17))
        self.clear_button.setFixedSize(28, 28)
        self.clear_button.setToolTip("Clear thoughts and results")
        self.clear_button.setAccessibleName("Clear thoughts and results")
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.clicked.connect(self.clear_workspace)
        header.addWidget(self.clear_button, 0, Qt.AlignmentFlag.AlignVCenter)
        header.setSpacing(8)
        self.settings_button = QPushButton()
        self.settings_button.setObjectName("settings")
        self.settings_button.setIcon(QIcon(str(ROOT / "desktop" / "settings.svg")))
        self.settings_button.setIconSize(QSize(17, 17))
        self.settings_button.setFixedSize(28, 28)
        self.settings_button.setToolTip("Settings")
        self.settings_button.setAccessibleName("Settings")
        self.settings_button.clicked.connect(self.open_settings)
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

        self.status = QLabel("Thoughts → brief → technique → ready-to-use prompt")
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
        self.thoughts.setPlaceholderText("Describe what you need")
        thoughts_palette = self.thoughts.palette()
        thoughts_palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9a8c6b"))
        self.thoughts.setPalette(thoughts_palette)
        self.thoughts.setMinimumHeight(110)
        box.addWidget(self.thoughts, 1)
        # What the brief assumed sits under the request as its own block: natural height, no scroll of its own.
        self.assumptions_slot = QVBoxLayout()
        self.assumptions_slot.setContentsMargins(0, 6, 0, 0)
        box.addLayout(self.assumptions_slot)
        self.assumptions_card: QWidget | None = None

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
        # Where the prompt goes and where it runs belong together: right under the target switch.
        # Where it runs decides which tool steps the prompt may rely on.
        runs_in = QVBoxLayout()
        runs_in.setContentsMargins(0, 6, 0, 2)  # 16px rows: Written for → Runs in → Technique
        runs_in.setSpacing(8)
        runs_in.addWidget(field_label("Runs in"))
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

        box.addLayout(actions)
        # Which model writes the prompt, visible without opening Settings.
        self.model_line = QPushButton()
        self.model_line.setObjectName("modelLine")
        self.model_line.setCursor(Qt.CursorShape.PointingHandCursor)
        self.model_line.setToolTip("The model that writes the prompt · click to change it in Settings")
        self.model_line.clicked.connect(self.open_settings)
        box.addWidget(self.model_line, 0, Qt.AlignmentFlag.AlignLeft)
        self.generation_progress = QProgressBar()
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
    REPO_URL = "https://github.com/KazKozDev/prompta"

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
        self.result_column.assumptionsCard.connect(self._on_assumptions_card)
        self.result_column.briefEdited.connect(lambda: self._sync_build_label())
        self.result_column.rebuildRequested.connect(lambda: self.run_pipeline())
        self.result_column.promptEdited.connect(self.history.prompt_edited)  # edits go into the saved result
        box.addWidget(self.result_column, 1)

        self.result_column.show_placeholder()
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
        self.about = AboutPage(
            self.APP_VERSION, self.AUTHOR, self.AUTHOR_URL, self.REPO_URL, self.history_store.path.parent
        )
        dialog.add_page(self.about, "About", footer=self.about.footer, backdrop=True)
        return dialog

    def open_settings(self) -> None:
        self.settings_dialog.open()

    def load_techniques(self) -> None:
        self.techniques_loader = TechniquesLoader()
        self.techniques_loader.loaded.connect(self._on_techniques_loaded)
        self.techniques_loader.start()

    def _on_techniques_loaded(self, techniques: list) -> None:
        loader = getattr(self, "techniques_loader", None)
        self.prompt_version = getattr(loader, "prompt_version", "") or getattr(self, "prompt_version", "")
        self.technique_panel.set_techniques(techniques)

    def _on_assumptions_card(self, card: QWidget | None) -> None:
        self._set_assumptions_card(card)
        self._sync_build_label()

    # ── run ───────────────────────────────────────────────────────
    def clear_workspace(self) -> None:
        self._discard_result = True
        running = self.worker is not None and self.worker.isRunning()
        if running:
            self.worker.cancel()
        self.thoughts.stop_dictation()
        self.thoughts.clear()
        self.thoughts.setToolTip("")
        self._active_thoughts = ""
        self.history.deselect()
        self.result_column.show_placeholder()
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

    def _set_assumptions_card(self, card: QWidget | None) -> None:
        if self.assumptions_card is not None:
            self.assumptions_card.hide()
            self.assumptions_card.deleteLater()
        self.assumptions_card = card
        if card is not None:
            self.assumptions_slot.addWidget(card)
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
        card = self.assumptions_card
        count = card.change_count() if card is not None and hasattr(card, "change_count") else 0
        base = getattr(self, "build_label", "Build prompt")
        shortcut = base[len("Build prompt") :]
        self.run_button.setText(f"Rebuild · {count} change{'s' if count != 1 else ''}{shortcut}" if count else base)

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

        technique_keys = self.technique_panel.technique_keys()
        payload = {
            "thoughts": thoughts,
            **generator,  # provider, model, key and URL
            **self.target_selector.flags(),
            "variants": self.variants.value(),
        }
        profile = self.execution_profile.current_key()
        payload["executionProfile"] = profile
        if profile == "agent":
            payload["agentCapabilities"] = list(self.execution_profile.AGENT_CAPABILITIES)
        if self.target_selector.open_model():
            payload["openModel"] = self.target_selector.open_model()
        if technique_keys:
            if len(technique_keys) == 1:
                payload["manualTechnique"] = technique_keys[0]
            else:
                payload["manualTechniques"] = technique_keys
        if revised_brief is not None:
            payload["brief"] = revised_brief

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
        self.status.setText(
            f"Building {target_label} prompt from official sources"
            if selected
            else "Brief → technique selection → synthesis"
        )

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
        self.generation_progress.setValue(max(self.generation_progress.value(), min(99, percent)))
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
        if not data.get("ok"):
            if getattr(self, "_rebuilding_brief", False):
                self.status.setText(f"Rebuild failed: {data.get('error', 'unknown error')}")
                return
            self.result_column.show_error(data.get("error", "unknown error"))
            self.status.setText("Error")
            return

        if data.get("procedure"):
            self.result_column.render_procedure(data["procedure"])
            self._save_result(data["procedure"]["technique"]["name"], "procedure", data["procedure"])
            self.status.setText(f"{data['procedure']['technique']['name']} · procedure, no prompt")
            return

        if data.get("manual"):
            self.result_column.render_manual(data["manual"], source_thoughts=self._active_thoughts)
            self._save_result(data["manual"]["technique"]["name"], "manual", data["manual"])
            self.status.setText(f"{data['manual']['technique']['name']} · built using this method")
            built, failed = len(data["manual"].get("variants") or []), len(data["manual"].get("failed") or [])
            if built > 1:
                self.status.setText(
                    f"{built} techniques built" + (f" · {failed} failed, see below the prompt" if failed else "")
                )
            return

        self.result_column.render_result(data["result"], source_thoughts=self._active_thoughts)
        self._save_result(data["result"]["choice"]["name"], "pipeline", data["result"])
        count = len(self.result_column.visible_warnings)
        name = data["result"]["choice"]["name"]
        self.status.setText(
            f"{name} · {count} warning{'s' if count != 1 else ''} below the prompt" if count else f"{name} · ready"
        )

    # ── result rendering ──────────────────────────────────────────

    # ── history ───────────────────────────────────────────────────
    def _save_result(self, label: str, kind: str, payload: dict) -> None:
        self.history.push(label, kind, self._active_thoughts or self.thoughts.toPlainText().strip(), payload)

    def _render_history_entry(self, entry: dict) -> None:
        """Show a saved result; raises KeyError, TypeError or ValueError for data it cannot show."""
        kind, payload = entry["kind"], entry["payload"]
        self.thoughts.setPlainText(entry["thoughts"])
        if kind == "manual":
            self.result_column.render_manual(payload)
        elif kind == "procedure":
            self.result_column.render_procedure(payload)
        else:
            self.result_column.render_result(payload)

    def _on_history_opened(self, entry: dict) -> None:
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
    return app


def main() -> int:
    qt_log.install()  # silences only the known macOS accessibility-bridge noise; PROMPTA_QT_DEBUG=1 shows everything
    app = make_app(sys.argv)
    screenshot = "--screenshot" in sys.argv
    instance = SingleInstance()
    if not screenshot and not instance.claim():
        return 0  # the running copy comes forward instead
    window = PromptaWindow()
    instance.activated.connect(lambda: bring_forward(window))
    window.show()
    paint_title_bar(window)  # dark graphite title bar; app.qss only styles the content

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
        except Exception:
            pass
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

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
