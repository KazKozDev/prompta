#!/usr/bin/env python3
"""Prompta — a native macOS app.

PyQt6 UI; the logic is the existing TS pipeline, reached through the desktop/bridge.ts bridge.
History is stored locally; API keys are never written to disk.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import keychain
from history import HistoryStore, history_topic
from library import LibraryWidget
from settings_ui import SECTION_GAP, add_section, settings_page
from mcp_settings import McpSettingsWidget

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFontMetrics, QPalette, QFont, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from theme import COMPATIBLE, PROMPT_TARGETS, QSS, ROOT
from single_instance import SingleInstance, bring_forward

from history_view import HistoryMixin
from target_selector import TargetSelector
from window_result import ResultMixin
from window_settings import SettingsMixin
import qt_log

from controls import BackgroundWidget, Card, Dropdown, ExecutionProfileDropdown, IconDropdown, VariantSelector
from result_view import ACTION_HEIGHT, CONTROL_HEIGHT, Disclosure, find_layout, muted_label
from widgets import (
    DashedScrollBar,
    DashedScrollPainter,
    HintFilter,
    HistoryComboBox,
    PopupAnimation,
    ThoughtsEdit,
    title_font,
    use_step_scroll,
)
from workers import BRIDGE, FALLBACK_MODELS, Worker, fetch_ollama_models, node_binary

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


class PromptaWindow(HistoryMixin, SettingsMixin, ResultMixin, QMainWindow):
    """Main window: the finished prompt comes first (variants as tabs); brief, zero-shot baseline,
    technique rationale and sources fold into "How this prompt was built". The target the prompt is
    written for lives in TargetSelector (target_selector.py): requests and history restore go through it."""

    run_button: QPushButton

    def __init__(self) -> None:
        self.visible_warnings: list[str] = []
        self.catalog_summary = ""
        self._variants_before_manual: int | None = None
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
        self._shown_entry: int | None = None  # index in _history_items of the result on screen
        self._history_items: list[dict] = []
        self._active_thoughts = ""
        self._discard_result = False

        root = BackgroundWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 3, 12, 6)  # top equals spacing below the header: title sits centred
        outer.setSpacing(3)

        header = QHBoxLayout()
        self.header_layout = header
        header.setSpacing(20)
        header.addStretch(1)  # the window title already says Prompta
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
        splitter.setSizes([440, 700])
        outer.addWidget(splitter, 1)

        self.status = QLabel("Thoughts → brief → technique → ready-to-use prompt")
        self.status.setObjectName("status")
        outer.addSpacing(3)  # keep the original 6px above the status line
        outer.addWidget(self.status)
        self._load_history()
        for button in self.findChildren(QPushButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)

        self.provider.changed.connect(self._on_provider_changed)
        self.provider.changed.connect(lambda *_: self._sync_model_line())
        self.model.changed.connect(lambda *_: self._sync_model_line())
        self.model_name.textChanged.connect(lambda *_: self._sync_model_line())
        self.api_key.editingFinished.connect(self._reload_models_for_key)  # a new key can unlock the provider's list
        self.model_base_url.textChanged.connect(lambda *_: self._sync_model_line())
        self._restore_generator()  # last provider, model and URLs; loads that provider's models
        for signal in (
            self.provider.changed,
            self.model.changed,
            self.model_name.editingFinished,
            self.model_base_url.editingFinished,
        ):
            signal.connect(lambda *_: self._save_generator())
        self._sync_model_line()
        self._publish_generator()  # the MCP server sees the restored choice even before anything changes
        self.load_techniques()

        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut.activated.connect(self.run_pipeline)
        shortcut2 = QShortcut(QKeySequence("Meta+Return"), self)
        shortcut2.activated.connect(self.run_pipeline)
        self._restyle_input()
        self.build_label = "Build prompt   ⌘↵"
        self.run_button.setText(self.build_label)
        self.run_button.setToolTip("⌘↵ builds the prompt")
        self.status.setText("")
        # History is a picker like every other: the same button, chevron and panel with search inside.
        self.history_picker = IconDropdown(
            "search.svg",
            "Search history",
            searchable=True,
            popup_width=480,
            search_placeholder="Search requests and prompts",
        )
        self.history_picker.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_picker.changed.connect(self._on_history_picked)
        self.history_picker.deleteRequested.connect(self._on_history_delete)
        self.header_layout.insertWidget(self.header_layout.indexOf(self.clear_button), self.history_picker)
        self._sync_history_row()
        self._fit_input_column()  # the restyled column (target switch with Open) is wider than at construction
        self._restyle_settings()

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
        self.technique_label = self._mini_label("Technique")
        box.addWidget(self.technique_label)
        self.technique = Dropdown(
            "— choose a technique —",
            columns=2,
            searchable=True,
            popup_width=820,
            search_placeholder="Filter techniques",
        )
        box.addWidget(self.technique)

        self.local_providers = load_local_providers()
        self.provider = Dropdown("Ollama", popup_width=300)
        self.provider.set_items(
            [
                {"key": "ollama", "label": "Ollama (local/cloud)"},
                {"key": "gemini", "label": "Gemini"},
                {"key": "openai", "label": "OpenAI"},
                {"key": COMPATIBLE, "label": "OpenAI-compatible"},
                {"key": "anthropic", "label": "Anthropic (Claude)"},
                {"key": "xai", "label": "xAI (Grok)"},
            ]
            + [{"key": key, "label": item["label"]} for key, item in self.local_providers.items()]
        )
        self.provider.set_current("ollama")
        self._url_owner = "ollama"

        model_row = QHBoxLayout()
        model_row.setSpacing(6)
        self.model = Dropdown("Choose a model", searchable=True, popup_width=460, search_placeholder="Filter models")
        self.model.set_items([{"key": name, "label": name} for name in FALLBACK_MODELS])
        self.model.set_current("minimax-m3.1-flash:cloud")
        model_row.addWidget(self.model, 1)
        # Other providers have no list to pick from: their model name is typed by hand, kept per provider.
        self.model_name = QLineEdit()
        self.model_name.setPlaceholderText("Model name, e.g. gpt-5.1 or mlx-community/Qwen3-8B")
        self.model_name.setAccessibleName("Model name")
        self.model_name.setMinimumHeight(34)
        self.model_name.hide()
        self._model_lists: dict[str, list[str]] = {}  # each provider shows only its own models
        self._list_sources: dict[str, str] = {}  # "catalog" when a list came from models.dev, not the provider
        for key, item in self.local_providers.items():  # a personal provider starts with the models it names
            if item["models"]:
                self._model_lists[key] = item["models"]
                self._list_sources[key] = "local"
        self._model_choices: dict[str, str] = {}
        model_row.addWidget(self.model_name, 1)
        self.refresh_button = QPushButton("↻")
        self.refresh_button.setObjectName("ghost")
        self.refresh_button.setFixedSize(34, 34)
        self.refresh_button.setToolTip("Refresh the provider's model list")
        self.refresh_button.clicked.connect(self.load_models)
        model_row.addWidget(self.refresh_button)
        self.models_hint = QLabel("Loading Ollama models")
        self.models_hint.setObjectName("muted")
        self.models_hint.setWordWrap(True)

        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle("Settings")
        self.settings_dialog.setModal(True)
        self.settings_dialog.setMinimumWidth(420)
        self.settings_dialog.resize(860, 640)
        # About shows the window's photo over the whole dialog, clearly visible: the veil thins out to the right.
        self.settings_backdrop = BackgroundWidget(veil=(236, 120))
        self.settings_backdrop.setParent(self.settings_dialog)
        self.settings_backdrop.hide()
        self.settings_dialog.installEventFilter(self)
        settings_outer = QVBoxLayout(self.settings_dialog)
        settings_outer.setContentsMargins(24, 24, 24, 24)
        settings_outer.setSpacing(14)
        settings_title = QLabel("Settings")
        settings_title.setObjectName("title")  # same face as the main window header
        settings_title.setFont(title_font())
        settings_outer.addWidget(settings_title)
        self.settings_tabs = QTabWidget()
        self.settings_tabs.setAccessibleName("Settings sections")
        model_page, settings_layout = settings_page(
            "The model that writes your prompts. Each provider keeps its own model, key and URL."
        )
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Not needed for Ollama and local servers")
        self.api_key.setAccessibleName("API key")
        self.remember_key = QCheckBox("Remember in Keychain")
        self.remember_key.setToolTip(
            "Save this provider's key in your macOS login Keychain and fill it in next time. "
            "Unchecking removes the saved key; without it the key stays in memory until you quit."
        )
        self.remember_key.toggled.connect(self._on_remember_key_toggled)
        self.remember_key.setObjectName("settingsCheck")
        self.model_base_url = QLineEdit()
        self._base_urls: dict[str, str] = {}  # each provider keeps its own URL while you switch between them
        self.model_base_url.setPlaceholderText("Optional · http://127.0.0.1:8080/v1")
        self.model_base_url.setAccessibleName("Model base URL")
        self.model_base_url.setToolTip(
            "Requests and any API key you enter go to this endpoint. Empty uses the provider's "
            "default; OpenAI-compatible servers (MLX, LM Studio, vLLM, OpenRouter) need theirs."
        )
        # The app's own form: a caps label over each full-width field, shared gaps, one grey line where it helps.
        add_section(settings_layout, "Provider", self.provider)
        add_section(settings_layout, "Model", model_row, hint=self.models_hint)
        add_section(settings_layout, "API key", self.api_key)
        settings_layout.addSpacing(10)
        settings_layout.addWidget(self.remember_key)  # under the key, flush with the fields
        add_section(
            settings_layout,
            "Base URL",
            self.model_base_url,
            hint="Empty uses the provider's default. OpenAI-compatible servers need their own.",
        )
        self._load_saved_key(self.provider.current_key())
        settings_layout.addStretch(1)
        self.settings_tabs.addTab(model_page, "Model && API")
        self.library = LibraryWidget(ROOT)
        self.settings_tabs.addTab(self.library, "Library")
        self.mcp_settings = McpSettingsWidget(
            ROOT, node_binary, self._mini_label, self._generator_for_mcp, self._mcp_key_missing
        )
        mcp_scroll = QScrollArea()  # the apps list is taller than the dialog: scroll, don't squeeze rows
        mcp_scroll.setWidgetResizable(True)
        mcp_scroll.setFrameShape(QFrame.Shape.NoFrame)
        mcp_scroll.setObjectName("clearScroll")
        mcp_scroll.setWidget(self.mcp_settings)
        use_step_scroll(mcp_scroll)
        self.settings_tabs.addTab(mcp_scroll, "MCP server")
        self.settings_tabs.addTab(self._build_history_settings(), "History")
        self.settings_tabs.addTab(self._build_about_settings(), "About")
        self.settings_tabs.currentChanged.connect(self._settings_tab_changed)
        settings_outer.addWidget(self.settings_tabs, 1)
        settings_outer.addSpacing(SECTION_GAP - settings_outer.spacing())  # the Done row stands apart like a section
        settings_actions = QHBoxLayout()
        # The Library's summary line sits on the Done row, shown only while Library is open.
        settings_actions.addWidget(self.library.summary, 0, Qt.AlignmentFlag.AlignVCenter)
        settings_actions.addWidget(self.delete_all_history_button, 0, Qt.AlignmentFlag.AlignVCenter)
        settings_actions.addWidget(self.mcp_settings.copy_button, 0, Qt.AlignmentFlag.AlignVCenter)
        settings_actions.addWidget(self.about_footer, 0, Qt.AlignmentFlag.AlignVCenter)
        self._sync_settings_footer(self.settings_tabs.currentIndex())
        settings_actions.addStretch(1)
        done_button = QPushButton("Done")
        done_button.setObjectName("primary")
        done_button.clicked.connect(self.settings_dialog.accept)
        settings_actions.addWidget(done_button)
        settings_outer.addLayout(settings_actions)

        try:
            open_models = json.loads((ROOT / "open_model_prompt_guides/manifest.json").read_text())["models"]
        except (OSError, ValueError, KeyError, TypeError):
            open_models = []  # the picker then offers any LLM and the official targets only
        self.target_selector = TargetSelector(open_models)
        self.target_picker = self.target_selector.picker
        self.target_selector.changed.connect(self._on_target_changed)
        box.addWidget(self.target_selector)

        box.addSpacing(4)
        variants_row = QHBoxLayout()
        variants_row.setSpacing(8)
        variants_label = self._mini_label("Prompt variants")
        variants_row.addWidget(variants_label)
        variants_row.addStretch(1)
        self.variants = VariantSelector()
        variants_row.addWidget(self.variants)
        box.addLayout(variants_row)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.build_label = "Build prompt"
        self.run_button = QPushButton(self.build_label)
        self.run_button.setObjectName("buildPrompt")
        self.run_button.setFixedHeight(42)
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

    def _selected_target(self) -> str | None:
        return self.target_selector.target()

    def _on_target_changed(self) -> None:
        """Official targets and open-weight models follow their own guidance: the technique catalog is for Any only."""
        selected = self._selected_target()
        self.technique.setEnabled(selected is None)
        self.technique.setToolTip(
            f"{PROMPT_TARGETS[selected][0]} mode uses official rules instead of the technique catalog."
            if selected
            else "Choose a technique to build a prompt using its method"
        )
        if hasattr(self, "advanced"):
            self._update_advanced_title()

    APP_VERSION = "0.1.0"
    AUTHOR = "KazKozDev"
    AUTHOR_URL = "https://github.com/KazKozDev"
    REPO_URL = "https://github.com/KazKozDev/prompta"

    def _mcp_key_missing(self) -> str:
        """The provider whose key the MCP server cannot read from Keychain, or "" when nothing is missing."""
        provider = self.provider.current_key()
        if provider == "ollama" or (provider == COMPATIBLE and not self.api_key.text().strip()):
            return ""
        local = self.local_providers.get(provider)
        if local and local.get("api_key"):  # the server reads providers.local.json too; an env var it may not see
            return ""
        return "" if keychain.load(provider) else self.provider.text()

    def _load_saved_key(self, provider: str) -> None:
        """Each provider has its own key: show the saved one, or an empty field."""
        saved = keychain.load(provider) if provider != "ollama" else ""
        local = self.local_providers.get(provider)
        if local and not saved:  # a personal provider may keep its key in its env var or the gitignored file
            saved = os.environ.get(str(local.get("key_env") or ""), "") or str(local.get("api_key") or "")
            self.api_key.setText(saved)
            previous = self.remember_key.blockSignals(True)
            self.remember_key.setChecked(False)
            self.remember_key.blockSignals(previous)
            return
        self.api_key.setText(saved)
        previous = self.remember_key.blockSignals(True)
        self.remember_key.setChecked(bool(saved))
        self.remember_key.blockSignals(previous)

    def _on_remember_key_toggled(self, checked: bool) -> None:
        provider = self.provider.current_key()
        if checked:
            key = self.api_key.text().strip()
            if key and not keychain.save(provider, key):
                self.status.setText("Could not save the key to Keychain")
        else:
            keychain.forget(provider)

    # ── right column ──────────────────────────────────────────────
    def _build_output(self) -> QWidget:
        card = Card()
        card.setObjectName("mainColumn")
        box = card.vbox()
        box.setContentsMargins(16, 0, 0, 0)

        history_row = QHBoxLayout()
        history_row.setSpacing(8)
        self.history = HistoryComboBox()
        self.history.deletable = True
        # Saved titles must not become the minimum width of the entire window.
        self.history.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.history.setMinimumContentsLength(12)
        self.history.addItem("— no history yet —", -1)
        self.history.currentIndexChanged.connect(self._on_history_selected)
        self.history.deleteRequested.connect(self._delete_history)
        history_row.addWidget(self.history, 1)
        box.addLayout(history_row)
        box.addSpacing(8)
        self.history_notice = QLabel()
        self.history_notice.setObjectName("error")
        self.history_notice.setWordWrap(True)
        self.history_notice.hide()
        box.addWidget(self.history_notice)

        self.output_scroll = QScrollArea()
        self.output_scroll.setObjectName("outputScroll")
        self.output_scroll.setVerticalScrollBar(DashedScrollBar(Qt.Orientation.Vertical, self.output_scroll))
        self.output_scroll.setHorizontalScrollBar(DashedScrollBar(Qt.Orientation.Horizontal, self.output_scroll))
        self.output_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.output_scroll.viewport().setAutoFillBackground(False)
        use_step_scroll(self.output_scroll)
        self.output_scroll.setWidgetResizable(True)
        self.output_holder = QWidget()
        self.output_holder.setObjectName("outputContent")
        self.output_layout = QVBoxLayout(self.output_holder)
        self.output_layout.setContentsMargins(0, 0, 0, 0)
        self.output_layout.setSpacing(10)
        # The scroll area must grow with its content, or the widgets overlap.
        self.output_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.output_scroll.setWidget(self.output_holder)
        self.output_holder.setAutoFillBackground(False)
        box.addWidget(self.output_scroll, 1)

        self._show_placeholder()
        return card

    def _clear_output(self) -> None:
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
        self._set_assumptions_card(None)  # the questions belong to the result being replaced
        self._sync_build_label()

    # ── run ───────────────────────────────────────────────────────
    def clear_workspace(self) -> None:
        self._shown_entry = None
        self._discard_result = True
        running = self.worker is not None and self.worker.isRunning()
        if running:
            self.worker.cancel()
        self.thoughts.stop_dictation()
        self.thoughts.clear()
        self.thoughts.setToolTip("")
        self._active_thoughts = ""
        previous = self.history.blockSignals(True)
        self.history.setCurrentIndex(0)
        self.history.blockSignals(previous)
        self.history_notice.hide()
        self._show_placeholder()
        self.generation_progress.hide()
        self.generation_progress.setValue(0)
        self._set_running(running)
        self.status.setText("")
        self.thoughts.setFocus()

    def _sync_model_line(self) -> None:
        model = self._current_model()
        where = self.provider.text()
        if self.model_base_url.text().strip():
            where += " · custom URL"
        self.model_line.setText(
            f"Generator model: {model} · {where}" if model else "Generator model: none chosen · open Settings"
        )

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

        provider = self.provider.current_key()
        model = self._current_model()
        api_key = self.api_key.text().strip()
        if self.remember_key.isChecked() and api_key and api_key != keychain.load(provider):
            keychain.save(provider, api_key)  # the key that works is the one to remember

        if not model:
            self.status.setText("Choose a model")
            return
        base_url = self.model_base_url.text().strip() or self._local_url(provider)
        if provider == COMPATIBLE and not base_url:
            self.status.setText("Add the server URL in Settings")
            return
        if provider not in ("ollama", COMPATIBLE) and not api_key and not (provider == "openai" and base_url):
            self.status.setText("Add an API key in Settings")
            return

        technique_keys = self.technique.current_keys()
        payload = {
            "thoughts": thoughts,
            "provider": self._api_provider(provider),  # same API, its own key and URL
            "model": model,
            "apiKey": api_key,
            "baseUrl": base_url,
            **self.target_selector.flags(),
            "variants": self.variants.value(),
        }
        execution_profile = getattr(self, "execution_profile", None)
        if execution_profile is not None:
            profile = execution_profile.current_key()
            payload["executionProfile"] = profile
            if profile == "agent":
                payload["agentCapabilities"] = list(execution_profile.AGENT_CAPABILITIES)
        if self.target_selector.open_model():
            payload["openModel"] = self.target_selector.open_model()
        if technique_keys and self._selected_target() is None:
            if len(technique_keys) == 1:
                payload["manualTechnique"] = technique_keys[0]
            else:
                payload["manualTechniques"] = technique_keys
        if revised_brief is not None:
            payload["brief"] = revised_brief

        self._set_running(True)
        self.generation_progress.setValue(0)
        self.generation_progress.show()
        selected = self._selected_target()
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
            self._clear_output()
            error = QLabel(f"Error: {data.get('error', 'unknown error')}")
            error.setObjectName("error")
            error.setWordWrap(True)
            self.output_layout.addStretch(1)
            self.output_layout.addWidget(error)
            self.output_layout.addStretch(1)
            self.status.setText("Error")
            return

        if data.get("procedure"):
            self.render_procedure(data["procedure"])
            self._push_history(data["procedure"]["technique"]["name"], "procedure", data["procedure"])
            self.status.setText(f"{data['procedure']['technique']['name']} · procedure, no prompt")
            return

        if data.get("manual"):
            self.render_manual(data["manual"], source_thoughts=self._active_thoughts)
            self._push_history(data["manual"]["technique"]["name"], "manual", data["manual"])
            self.status.setText(f"{data['manual']['technique']['name']} · built using this method")
            built, failed = len(data["manual"].get("variants") or []), len(data["manual"].get("failed") or [])
            if built > 1:
                self.status.setText(
                    f"{built} techniques built" + (f" · {failed} failed, see below the prompt" if failed else "")
                )
            return

        self.render_result(data["result"], source_thoughts=self._active_thoughts)
        self._push_history(data["result"]["choice"]["name"], "pipeline", data["result"])
        count = len(self.visible_warnings)
        name = data["result"]["choice"]["name"]
        self.status.setText(
            f"{name} · {count} warning{'s' if count != 1 else ''} below the prompt" if count else f"{name} · ready"
        )

    # ── result rendering ──────────────────────────────────────────

    # ── empty result area: the app name, large and faint; results replace it ──
    def _show_placeholder(self) -> None:
        self._clear_output()
        self.output_layout.addStretch(5)  # just above centre
        self.wordmark = Wordmark("PROMPTA")
        self.output_layout.addWidget(self.wordmark)
        slogan = QLabel("THOUGHTS IN. PROMPTS OUT.")  # the field-label lettering: capitals, tracked, medium
        slogan.setObjectName("slogan")
        slogan.setAlignment(Qt.AlignmentFlag.AlignCenter)
        slogan.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.output_layout.addWidget(slogan)
        self.output_layout.addStretch(6)

    # ── history picker ────────────────────────────────────────────
    def _sync_history_row(self) -> None:
        """Fill the history picker, newest first; searchable by topic, request and prompt text."""
        self.history.hide()  # still drives restore
        picker = getattr(self, "history_picker", None)
        if picker is None:
            return
        items = []
        for index in range(len(self._history_items) - 1, -1, -1):
            entry = self._history_items[index]
            label = history_topic(entry['thoughts'], entry['payload'], entry['label'])
            request = ' '.join(entry['thoughts'].split())
            items.append(
                {
                    "key": str(index),
                    "label": label,
                    # The date, and the request when the topic does not already say it.
                    "hint": entry['created_at'][:10]
                    + ("" if request.casefold() == label.casefold() else f" · {request[:90]}"),
                    "search": json.dumps(entry['payload'], ensure_ascii=False),
                    "deletable": True,
                }
            )
        picker.set_items(items)
        shown = getattr(self, "_shown_entry", None)
        previous = picker.blockSignals(True)
        picker.set_current(str(shown) if isinstance(shown, int) and 0 <= shown < len(self._history_items) else "")
        picker.blockSignals(previous)
        picker.setVisible(bool(self._history_items))
        self._fill_history_settings_list()  # Settings → History shows the same entries

    def _on_history_delete(self, key: str) -> None:
        if not key.isdigit():
            return
        row = self.history.findData(int(key))
        if row > 0:
            self._delete_history(row)
        # Keys are list positions, so the open panel is stale: reopen it with the remaining entries.
        picker = self.history_picker
        if picker._popup is not None:
            picker._popup.close()
        if self._history_items:
            QTimer.singleShot(0, picker._open)

    def _on_history_picked(self, key: str) -> None:
        if key.isdigit():
            self._open_history_index(int(key))
            self._sync_history_row()  # the button names the entry now on screen

    def _open_history_index(self, item_index: int) -> None:
        self._filter_history("", selected=item_index)
        combo_index = self.history.findData(item_index)
        if combo_index > 0:
            self.history.setCurrentIndex(combo_index)
            self._on_history_selected(combo_index)

    # ── left column ───────────────────────────────────────────────
    def _restyle_input(self) -> None:
        card_layout = self.thoughts.parentWidget().layout()
        assert card_layout is not None, "_build_input lays out the input card"

        variants_row = find_layout(card_layout, self.variants)
        variants_label = next(
            variants_row.itemAt(i).widget()
            for i in range(variants_row.count())
            if isinstance(variants_row.itemAt(i).widget(), QLabel)
        )
        self.advanced = Disclosure("Technique", field_label=True, collapsible=False)
        self.advanced.body_layout.setContentsMargins(0, 0, 0, 8)
        # It never folds: a plain field label like "Written for" and "Runs in", not the padded toggle button.
        self.advanced.button.hide()
        self.technique_heading = self._mini_label("Technique")
        self.technique_heading.setContentsMargins(0, 0, 0, 2)  # 8px to its field, as in the rows above
        self.advanced.body_layout.addWidget(self.technique_heading)
        self.advanced.body_layout.setSpacing(6)
        self.technique.set_multi(True)
        self.technique._placeholder = "— automatic —"
        self.technique.set_current_keys([])
        for moved in (self.technique_label, self.technique):
            card_layout.removeWidget(moved)
            self.advanced.body_layout.addWidget(moved)
        for unplaced in (variants_label, self.variants):
            variants_row.removeWidget(unplaced)
        # Full-width segmented switch under the technique picker, with a plain caption saying what the numbers are.
        variants_label.hide()
        variants_label.deleteLater()
        self.advanced.body_layout.addSpacing(6)
        self.variants_caption = muted_label(
            "Variants · prompts built with different techniques to compare", "variantsCaption"
        )
        self.advanced.body_layout.addWidget(self.variants_caption)
        self.advanced.body_layout.addWidget(self.variants)
        self.variants.setObjectName("segmentTrack")
        self.variants.setMinimumSize(0, 0)
        self.variants.setMaximumSize(16777215, 16777215)
        self.variants.layout().setContentsMargins(2, 2, 2, 2)
        self.variants.layout().setSpacing(2)
        buttons = self.variants.buttons.buttons()
        for index, button in enumerate(buttons):
            button.setObjectName("segment")
            button.setProperty("first", index == 0)
            button.setProperty("last", index == len(buttons) - 1)
            button.setMinimumHeight(0)
            button.setMaximumHeight(16777215)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        # The selector was already polished with its old object names; re-apply the stylesheet.
        for styled in [self.variants, *buttons]:
            styled.style().unpolish(styled)
            styled.style().polish(styled)
        actions = find_layout(card_layout, self.run_button)
        index = next(i for i in range(card_layout.count()) if card_layout.itemAt(i).layout() is actions)
        card_layout.insertWidget(index, self.advanced)
        # Where the finished prompt runs: decides which tool steps the prompt may rely on.
        runs_in = QVBoxLayout()
        runs_in.setContentsMargins(0, 0, 0, 8)
        runs_in.setSpacing(8)
        runs_in.addWidget(self._mini_label("Runs in"))
        self.execution_profile = ExecutionProfileDropdown()
        self.execution_profile.setAccessibleName("Where will the prompt run?")
        self.execution_profile.setFixedHeight(CONTROL_HEIGHT)
        self.execution_profile.setToolTip(
            "Where the generated prompt will be used. Tool steps in the prompt follow what that environment can do."
        )
        runs_in.addWidget(self.execution_profile)
        # Where the prompt goes and where it runs belong together: right under the target switch.
        runs_in.setContentsMargins(0, 6, 0, 2)  # 16px rows: Written for → Runs in → Technique
        card_layout.insertLayout(card_layout.indexOf(self.target_selector) + 1, runs_in)
        self.technique.changed.connect(self._update_advanced_title)
        self.variants.buttons.idClicked.connect(self._update_advanced_title)
        self.advanced.button.toggled.connect(self._update_advanced_title)
        self.technique_label.hide()  # its count moves into the Advanced title
        # One control height for fields and segmented tracks so rows line up.
        for field in (self.history, self.technique, self.variants, self.execution_profile, self.target_picker):
            field.ensurePolished()  # its own stylesheet would reset the minimum height when polished later
            field.setFixedHeight(CONTROL_HEIGHT)
        for button in self.variants.buttons.buttons():
            button.setFixedHeight(CONTROL_HEIGHT - 4)
        self.run_button.setFixedHeight(ACTION_HEIGHT)
        self._on_target_changed()

    def _update_advanced_title(self, *_: object) -> None:
        keys = self.technique.current_keys()
        # The Open segment counts as a target even before a model is picked: techniques are for Any only.
        target = self._selected_target()
        manual = bool(keys) and target is None
        # The 1–5 count is only for Any + automatic technique choice. Otherwise one prompt is built:
        # show 1 while locked, then restore the user's count.
        locked = manual or target is not None
        if locked and self._variants_before_manual is None:
            self._variants_before_manual = self.variants.value()
            self.variants.setValue(1)
        elif not locked and self._variants_before_manual is not None:
            self.variants.setValue(self._variants_before_manual)
            self._variants_before_manual = None
        self.variants.setEnabled(not locked)
        self.variants.setVisible(not locked)
        if hasattr(self, "variants_caption"):
            self.variants_caption.setVisible(not locked)
        self.variants.setToolTip("How many of the best-fitting techniques to pick; each gives one prompt")
        # Techniques exist only for Any: official targets and open-weight models follow their own guidance.
        self.advanced.setVisible(target is None)
        self.advanced.set_title("Technique")
        self.advanced.button.setToolTip(self.catalog_summary or "")
        self.technique_heading.setToolTip(self.catalog_summary or "")

    def closeEvent(self, event) -> None:  # noqa: N802
        if getattr(self, "_edit_timer", None) is not None and self._edit_timer.isActive():
            self._edit_timer.stop()
            self._save_prompt_edits()  # do not lose the last keystrokes on quit
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

    if screenshot:
        # Layout self-check: render a demo result and save the window as PNG.
        index = sys.argv.index("--screenshot")
        path = sys.argv[index + 1] if len(sys.argv) > index + 1 else "/tmp/app.png"
        window.thoughts.setPlainText(
            "I want AI to review my meeting notes and extract decisions, tasks, and owners into a table"
        )
        window._on_models_loaded(fetch_ollama_models())
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
        window.render_result(demo_result())
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
                ("provider", window.provider),
                ("model", window.model),
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
