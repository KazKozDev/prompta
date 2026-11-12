#!/usr/bin/env python3
"""Prompta — нативное приложение для macOS.

UI на PyQt6, логика — существующий TS-пайплайн через мост desktop/bridge.ts.
История хранится локально; ключи API на диск не записываются.
"""

from __future__ import annotations

import json
import os
import re
from html import escape
from urllib.parse import urlencode
import shutil
import sqlite3
from datetime import datetime
import subprocess
from collections import deque
from threading import Thread
import sys
import urllib.request
from pathlib import Path

try:
    from . import keychain
    from .history import HistoryStore, history_topic
    from .library import LibraryWidget
    from .mcp_settings import McpSettingsWidget
except ImportError:
    import keychain
    from history import HistoryStore, history_topic
    from library import LibraryWidget
    from mcp_settings import McpSettingsWidget

from PyQt6.QtCore import QModelIndex, QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QUrl, QProcess, QThread, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel, QColor, QCursor, QFontMetrics, QTextCursor, QPainter, QPalette, QPen, QFont, QGuiApplication, QIcon, QPixmap, QKeySequence, QShortcut, QDesktopServices, QTextDocument
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionSlider,
    QSizePolicy,
    QSplitter,
    QTabBar,
    QTabWidget,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

try:
    from .theme import CHAT_URLS, DARK_SCROLL_QSS, PROMPT_TARGETS, QSS, ROOT, is_official_source
    from .widgets import *  # noqa: F401,F403 — базовые виджеты, вынесенные из этого файла
except ImportError:
    from theme import CHAT_URLS, DARK_SCROLL_QSS, PROMPT_TARGETS, QSS, ROOT, is_official_source
    from widgets import *  # noqa: F401,F403

try:
    from .workers import *  # noqa: F401,F403 — потоки и мост к пайплайну
    from .controls import *  # noqa: F401,F403 — элементы управления
    from .result_view import *  # noqa: F401,F403 — вёрстка результата
    from .history_view import HistoryMixin
    from . import qt_log
except ImportError:
    from workers import *  # noqa: F401,F403
    from controls import *  # noqa: F401,F403
    from result_view import *  # noqa: F401,F403
    from history_view import HistoryMixin
    import qt_log

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


class WrappingField(QPlainTextEdit):
    """One-paragraph field that wraps: grows to fit its text up to `max_lines`, Enter submits instead of breaking the line."""
    returnPressed = pyqtSignal()

    def __init__(self, text: str = "", max_lines: int = 2) -> None:
        super().__init__()
        self.max_lines = max_lines
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self.document().setDocumentMargin(2)
        self.setText(text)
        # Plain-text layout reports its height in wrapped lines: refit whenever Qt re-wraps the text.
        self.document().documentLayout().documentSizeChanged.connect(self._schedule_fit)

    def _schedule_fit(self, *_: object) -> None:
        QTimer.singleShot(0, self._fit)  # after the pending re-wrap, not halfway through it

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._schedule_fit()

    def text(self) -> str:  # same reading and writing as QLineEdit, so callers need not care which field it is
        return self.toPlainText()

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        self.setPlainText(text)
        self.moveCursor(QTextCursor.MoveOperation.Start)  # show the beginning, not the tail

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.returnPressed.emit()
            return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source) -> None:  # noqa: N802 - Qt naming
        self.insertPlainText(" ".join(source.text().split()))  # pasted line breaks become spaces

    def _fit(self, *_: object) -> None:
        wrapped = max(1, round(self.document().size().height()))
        lines = min(self.max_lines, wrapped)
        # Line height from the laid-out text itself: font metrics can disagree with the styled font.
        block = self.blockBoundingRect(self.document().firstBlock()).height()
        line = block / wrapped if block > 0 else self.fontMetrics().lineSpacing()
        frame = self.height() - self.viewport().height()  # border and padding from the stylesheet
        height = int(lines * line + 0.999) + 2 * int(self.document().documentMargin()) + frame
        if height != self.height():
            self.setFixedHeight(height)
        self.setToolTip(self.toPlainText() if wrapped > self.max_lines else "Click to edit")


class MainWindow(HistoryMixin, QMainWindow):
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
        self.model_base_url.textChanged.connect(lambda *_: self._sync_model_line())
        self._sync_model_line()
        self.load_models()
        self.load_techniques()

        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut.activated.connect(self.run_pipeline)
        shortcut2 = QShortcut(QKeySequence("Meta+Return"), self)
        shortcut2.activated.connect(self.run_pipeline)

    # ── левая колонка ─────────────────────────────────────────────
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
        self.thoughts.setPlaceholderText(
            "Describe what you need"
        )
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
        self.technique = Dropdown("— choose a technique —", columns=2, searchable=True, popup_width=820,
                                  search_placeholder="Filter techniques")
        box.addWidget(self.technique)

        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(self._mini_label("Provider"))
        self.provider = Dropdown("Ollama", popup_width=300)
        self.provider.set_items(
            [
                {"key": "ollama", "label": "Ollama (local/cloud)"},
                {"key": "gemini", "label": "Gemini"},
                {"key": "openai", "label": "OpenAI"},
                {"key": "anthropic", "label": "Anthropic (Claude)"},
                {"key": "xai", "label": "xAI (Grok)"},
            ]
        )
        self.provider.set_current("ollama")
        left.addWidget(self.provider)

        mid = QVBoxLayout()
        mid.setSpacing(4)
        mid.addWidget(self._mini_label("Model"))
        model_row = QHBoxLayout()
        model_row.setSpacing(6)
        self.model = Dropdown("Choose a model", searchable=True, popup_width=460, search_placeholder="Filter models")
        self.model.set_items([{"key": name, "label": name} for name in FALLBACK_MODELS])
        self.model.set_current("minimax-m3.1-flash:cloud")
        model_row.addWidget(self.model, 1)
        self.refresh_button = QPushButton("↻")
        self.refresh_button.setObjectName("ghost")
        self.refresh_button.setFixedSize(34, 34)
        self.refresh_button.setToolTip("Refresh models from Ollama")
        self.refresh_button.clicked.connect(self.load_models)
        model_row.addWidget(self.refresh_button)
        mid.addLayout(model_row)
        self.models_hint = QLabel("Loading Ollama models")
        self.models_hint.setObjectName("muted")
        self.models_hint.setWordWrap(True)

        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle("Settings")
        self.settings_dialog.setModal(True)
        self.settings_dialog.setMinimumWidth(420)
        self.settings_dialog.resize(860, 640)
        settings_outer = QVBoxLayout(self.settings_dialog)
        settings_outer.setContentsMargins(24, 24, 24, 24)
        settings_outer.setSpacing(14)
        settings_title = QLabel("Settings")
        settings_title.setObjectName("title")  # same face as the main window header
        settings_title.setFont(title_font())
        settings_outer.addWidget(settings_title)
        self.settings_tabs = QTabWidget()
        self.settings_tabs.setAccessibleName("Settings sections")
        model_page = QWidget()
        settings_layout = QVBoxLayout(model_page)
        settings_layout.setContentsMargins(0, 18, 0, 0)
        settings_layout.setSpacing(14)
        settings_layout.addLayout(left)
        settings_layout.addLayout(mid)
        settings_layout.addWidget(self.models_hint)
        settings_layout.addWidget(self._mini_label("API key"))
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Enter your API key")
        self.api_key.setAccessibleName("API key")
        settings_layout.addWidget(self.api_key)
        self.remember_key = QCheckBox("Remember in Keychain")
        self.remember_key.setToolTip("Save this provider's key in your macOS login Keychain and fill it in next time. "
                                     "Unchecking removes the saved key.")
        self.remember_key.toggled.connect(self._on_remember_key_toggled)
        settings_layout.addWidget(self.remember_key)
        key_hint = QLabel("Use a key for cloud providers. Local Ollama and local OpenAI-compatible servers can run without one.\n"
                          "Without Remember, the key stays in memory only.")
        key_hint.setObjectName("muted")
        key_hint.setWordWrap(True)
        settings_layout.addWidget(key_hint)
        self._load_saved_key(self.provider.current_key())
        settings_layout.addWidget(self._mini_label("Model base URL"))
        self.model_base_url = QLineEdit()
        self.model_base_url.setPlaceholderText("Optional · http://127.0.0.1:8080/v1")
        self.model_base_url.setAccessibleName("Model base URL")
        self.model_base_url.setToolTip("Requests and any API key you enter go to this endpoint. "
                                       "For local MLX, choose OpenAI and enter the model name manually.")
        settings_layout.addWidget(self.model_base_url)
        url_hint = QLabel("For local MLX, choose OpenAI and enter your model name and server URL.")
        url_hint.setObjectName("muted")
        url_hint.setWordWrap(True)
        settings_layout.addWidget(url_hint)
        settings_layout.addStretch(1)
        self.settings_tabs.addTab(model_page, "Model && API")
        self.library = LibraryWidget(ROOT)
        self.settings_tabs.addTab(self.library, "Library")
        self.mcp_settings = McpSettingsWidget(ROOT, node_binary, self._mini_label, HistoryComboBox)
        mcp_scroll = QScrollArea()  # the apps list is taller than the dialog: scroll, don't squeeze rows
        mcp_scroll.setWidgetResizable(True)
        mcp_scroll.setFrameShape(QFrame.Shape.NoFrame)
        mcp_scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        mcp_scroll.setWidget(self.mcp_settings)
        use_step_scroll(mcp_scroll)
        self.settings_tabs.addTab(mcp_scroll, "MCP server")
        self.settings_tabs.addTab(self._build_history_settings(), "History")
        self.settings_tabs.currentChanged.connect(self._settings_tab_changed)
        settings_outer.addWidget(self.settings_tabs, 1)
        settings_actions = QHBoxLayout()
        settings_actions.addStretch(1)
        done_button = QPushButton("Done")
        done_button.setObjectName("primary")
        done_button.clicked.connect(self.settings_dialog.accept)
        settings_actions.addWidget(done_button)
        settings_outer.addLayout(settings_actions)

        target_grid = QGridLayout()
        target_grid.setHorizontalSpacing(8)
        target_grid.setVerticalSpacing(8)
        for index, (target, (label, _)) in enumerate((key, value) for key, value in PROMPT_TARGETS.items() if key != "openModel"):
            toggle = QCheckBox(f"For {label}")
            toggle.setObjectName("targetOption")
            toggle.setToolTip(f"Use saved official {label} guidance only. Your selected generator model stays the same.")
            toggle.toggled.connect(lambda enabled, key=target: self._on_target_toggled(key, enabled))
            setattr(self, f"{target}_only", toggle)
            target_grid.addWidget(toggle, index // 2, index % 2)
        self.openModel_only = QCheckBox(card)
        self.openModel_only.hide()
        self.openModel_only.toggled.connect(lambda enabled: self._on_target_toggled("openModel", enabled))
        self.prompt_model = HistoryComboBox()
        self.prompt_model.setAccessibleName("Prompting target model")
        self.prompt_model.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.prompt_model.setMinimumContentsLength(12)
        self.prompt_model.addItem("For open-weight model", "")
        try:
            manifest = json.loads((ROOT / "open_model_prompt_guides/manifest.json").read_text())
            add_grouped_models(self.prompt_model, manifest["models"])
        except (OSError, ValueError, KeyError, TypeError):
            self.prompt_model.setEnabled(False)
        self.prompt_model.setToolTip("Build a prompt using the selected model's saved official documentation. The generator model stays the same.")
        self.prompt_model.currentIndexChanged.connect(self._on_prompt_model_changed)
        target_grid.addWidget(self.prompt_model, 3, 0, 1, 2)
        target_grid.setColumnStretch(0, 1)
        target_grid.setColumnStretch(1, 1)
        box.addLayout(target_grid)

        divider = QFrame()
        divider.setObjectName("inputDivider")
        divider.setFixedHeight(1)
        box.addSpacing(4)
        box.addWidget(divider)
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
        # While a run is going the same button stops it (PromptaWindow); MainWindow keeps a separate Cancel.
        self.run_button.clicked.connect(lambda: self.cancel_run() if self._running() else self.run_pipeline())
        actions.addWidget(self.run_button, 1)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("ghost")
        self.cancel_button.setFixedSize(80, 42)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_run)
        actions.addWidget(self.cancel_button)
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
        return next((key for key in PROMPT_TARGETS if getattr(self, f"{key}_only").isChecked()), None)

    def _on_prompt_model_changed(self, index: int) -> None:
        self.openModel_only.setChecked(bool(self.prompt_model.currentData()))

    def _on_target_toggled(self, target: str, enabled: bool) -> None:
        if enabled:
            for key in PROMPT_TARGETS:
                if key == target:
                    continue
                toggle = getattr(self, f"{key}_only")
                previous = toggle.blockSignals(True)
                toggle.setChecked(False)
                toggle.blockSignals(previous)
        if enabled and target != "openModel":
            previous = self.prompt_model.blockSignals(True)
            self.prompt_model.setCurrentIndex(0)
            self.prompt_model.blockSignals(previous)
        selected = self._selected_target()
        self.technique.setEnabled(selected is None)
        self.technique.setToolTip(
            f"{PROMPT_TARGETS[selected][0]} mode uses official rules instead of the technique catalog."
            if selected else "Choose a technique to build a prompt using its method"
        )

    def open_settings(self) -> None:
        self.settings_dialog.open()
        if self.settings_tabs.currentIndex() == 0:
            self.api_key.setFocus()
        elif self.settings_tabs.currentIndex() == 2:  # MCP server (wrapped in a scroll area)
            self.mcp_settings.refresh()
        else:
            self.library.reload()
            self.library.search.setFocus()

    def _settings_tab_changed(self, index: int) -> None:
        if index == 1:
            self.library.reload()
        elif index == 2:  # MCP server
            self.mcp_settings.refresh()

    def _mini_label(self, text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setObjectName("fieldLabel")
        return label

    def load_techniques(self) -> None:
        self.techniques_loader = TechniquesLoader()
        self.techniques_loader.loaded.connect(self._on_techniques_loaded)
        self.techniques_loader.start()

    def _on_techniques_loaded(self, techniques: list) -> None:
        loader = getattr(self, "techniques_loader", None)
        self.prompt_version = getattr(loader, "prompt_version", "") or getattr(self, "prompt_version", "")
        if not techniques:
            return
        for item in techniques:
            if item.get("status") == "procedure":
                item["name"] = f"{item.get('name', item['key'])} (procedure)"
            item["label"] = item.get("name", item["key"])
        self.technique.set_items(techniques, keep=self.technique.current_key())
        self.technique_label.setText(f"TECHNIQUE · {len(techniques)}")

    def load_models(self) -> None:
        self.models_hint.setText("Fetching Ollama models")
        self.refresh_button.setEnabled(False)
        self.models_loader = ModelsLoader()
        self.models_loader.loaded.connect(self._on_models_loaded)
        self.models_loader.start()

    def _on_models_loaded(self, names: list) -> None:
        QTimer.singleShot(0, self._sync_model_line)  # the list may change the current model without a signal
        self.refresh_button.setEnabled(True)
        if not names:
            self.models_hint.setText(
                "Ollama is unavailable at localhost:11434. Using the previous model list."
            )
            return

        current = self.model.current_key().strip()
        self.model.set_items([{"key": name, "label": name} for name in names], keep=current)
        self.mcp_settings.set_models(names)
        if not self.model.current_key():
            self.model.set_current(names[0])
        self.models_hint.setText(f"{len(names)} models loaded")

    def _load_saved_key(self, provider: str) -> None:
        """Each provider has its own key: show the saved one, or an empty field."""
        saved = keychain.load(provider) if provider != "ollama" else ""
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

    def _on_provider_changed(self, provider: str) -> None:
        self.model_base_url.clear()
        self._load_saved_key(provider)
        if provider == "ollama":
            self.load_models()
        else:
            self.models_hint.setText("Enter the model name used by your provider")

    # ── правая колонка ────────────────────────────────────────────
    def _build_output(self) -> QWidget:
        card = Card()
        card.setObjectName("mainColumn")
        box = card.vbox()
        box.setContentsMargins(16, 0, 0, 0)

        history_row = QHBoxLayout()
        history_row.setSpacing(8)
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Search requests and prompts")
        self.history_search.setClearButtonEnabled(True)
        self.history_search.textChanged.connect(self._filter_history)
        history_row.addWidget(self.history_search, 1)
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
        # Скролл должен расти под содержимое, иначе виджеты наезжают друг на друга.
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

    def _show_placeholder(self) -> None:
        # Empty output area stays blank: no hint text.
        self._clear_output()
        self.output_layout.addStretch(1)

    # ── запуск ────────────────────────────────────────────────────
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
        self.history_search.clear()
        previous = self.history.blockSignals(True)
        self.history.setCurrentIndex(0)
        self.history.blockSignals(previous)
        self.history_notice.hide()
        self._show_placeholder()
        self.generation_progress.hide()
        self.generation_progress.setValue(0)
        self._set_running(running)
        self.status.setText("Thoughts → brief → technique → ready-to-use prompt")
        self.thoughts.setFocus()

    def _sync_model_line(self) -> None:
        model = self.model.current_key().strip()
        where = self.provider.text()
        if self.model_base_url.text().strip():
            where += " · custom URL"
        self.model_line.setText(f"Generator model: {model} · {where}" if model else "Generator model: none chosen · open Settings")

    def _running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _set_running(self, running: bool) -> None:
        self.cancel_button.setEnabled(running)
        if getattr(self, "single_run_button", False):
            self.run_button.setEnabled(True)
            self.run_button.setToolTip("Stop this run" if running else "⌘↵ builds the prompt")
            if running:
                self.run_button.setText("Stop")
            else:
                self._sync_build_label(force=True)  # the finished signal arrives while the thread still counts as running
        else:
            self.run_button.setEnabled(not running)

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
        """The edited brief from the assumptions card, if the user changed it and the request is the one it belongs to."""
        card = self.assumptions_card
        revise = getattr(card, "revised_brief", None)
        return revise() if revise is not None else None

    def _sync_build_label(self, force: bool = False) -> None:
        """One button: it says Rebuild when the card has edits, so the user knows the request is not re-read."""
        if not hasattr(self, "run_button"):
            return
        if not force and getattr(self, "single_run_button", False) and self._running():
            return  # the button says Stop until the run ends
        card = self.assumptions_card
        count = card.change_count() if card is not None and hasattr(card, "change_count") else 0
        base = getattr(self, "build_label", "Build prompt")
        shortcut = base[len("Build prompt"):]
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
        model = self.model.current_key().strip()
        api_key = self.api_key.text().strip()
        if self.remember_key.isChecked() and api_key and api_key != keychain.load(provider):
            keychain.save(provider, api_key)  # the key that works is the one to remember

        if not model:
            self.status.setText("Choose a model")
            return
        base_url = self.model_base_url.text().strip()
        if provider != "ollama" and not api_key and not (provider == "openai" and base_url):
            self.status.setText("Add an API key in Settings")
            return

        technique_keys = self.technique.current_keys()
        payload = {
            "thoughts": thoughts,
            "provider": provider,
            "model": model,
            "apiKey": api_key,
            "baseUrl": base_url,
            "claudeOnly": self.claude_only.isChecked(),
            "chatgptOnly": self.chatgpt_only.isChecked(),
            "geminiOnly": self.gemini_only.isChecked(),
            "grokOnly": self.grok_only.isChecked(),
            "hermesOnly": self.hermes_only.isChecked(),
            "variants": self.variants.value(),
        }
        execution_profile = getattr(self, "execution_profile", None)
        if execution_profile is not None:
            profile = execution_profile.current_key()
            payload["executionProfile"] = profile
            if profile == "agent":
                payload["agentCapabilities"] = list(execution_profile.AGENT_CAPABILITIES)
        if self.openModel_only.isChecked():
            payload["openModel"] = self.prompt_model.currentData()
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
        target_label = self.prompt_model.currentText() if selected == "openModel" else PROMPT_TARGETS[selected][0] if selected else ""
        self.status.setText(f"Building {target_label} prompt from official sources" if selected else "Brief → technique selection → synthesis")

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
            return

        self.render(data["result"], source_thoughts=self._active_thoughts)
        self._push_history(data["result"]["choice"]["name"], "pipeline", data["result"])
        choice = data["result"]["choice"]
        warnings = len(data["result"]["synthesis"]["warnings"])
        self.status.setText(f"{choice['name']} · warnings: {warnings}")

    def _add_usage(self, payload: dict) -> None:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return
        calls = usage["calls"]
        input_tokens, output_tokens = usage["inputTokens"], usage["outputTokens"]
        tokens = (f"{input_tokens:,} input · {output_tokens:,} output tokens"
                  if input_tokens or output_tokens else "Token counts unavailable")
        label = muted_label(f"{calls} model {'call' if calls == 1 else 'calls'} · {tokens}")
        label.setToolTip("Token counts come from the model provider. Calls count generation attempts, "
                         "including format retries. HTTP retries are counted within the same call.")
        self.output_layout.addWidget(label)

    def _add_zero_shot(self, payload: dict) -> None:
        text = payload.get("zeroShotPrompt")
        if not text:
            brief = payload.get("brief") or {}
            task = brief.get("goal") or self.thoughts.toPlainText().strip()
            if not task:
                return
            text = f"Задача:\n{task}"
            if brief.get("input"):
                text += f"\n\nВходные данные:\n{brief['input']}"
            if brief.get("output_format"):
                text += f"\n\nФормат ответа:\n{brief['output_format']}"
            if brief.get("constraints"):
                text += "\n\nОграничения:\n" + "\n".join(brief["constraints"])
            text += "\n\nВыполни задачу напрямую. Не выдумывай отсутствующие факты; явно укажи, каких исходных данных не хватает."
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
        editor = PromptEdit(text, self.output_scroll)
        editor.setAccessibleName("Zero-shot baseline prompt")
        editor.setFixedHeight(260)
        details.addWidget(editor)
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #d8c593; border: none;")
        self.output_layout.addWidget(divider)
        self.output_layout.addSpacing(14)

    def render_procedure(self, procedure: dict) -> None:
        self._clear_output()

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

        explain = QLabel(
            "This is a procedure for data or models. Follow the steps in code or manually."
        )
        explain.setObjectName("warn")
        explain.setWordWrap(True)
        self.output_layout.addWidget(explain)

        steps = QLabel("\n".join(f"{i}. {step}" for i, step in enumerate(procedure["steps"], 1)))
        steps.setWordWrap(True)
        steps.setStyleSheet(
            "background: #fff8e7; border: 1px solid #d8c593; border-radius: 8px; padding: 12px;"
        )
        self.output_layout.addWidget(steps)

        when = QLabel(f"When to use: {procedure['when_to_use']}")
        when.setObjectName("muted")
        when.setWordWrap(True)
        self.output_layout.addWidget(when)

        self.output_layout.addStretch(1)

    def render_manual(self, manual: dict, *, source_thoughts: str | None = None) -> None:
        self._clear_output()

        technique = manual["technique"]
        title = QLabel(manual.get("topic") or technique["name"])
        title.setObjectName("goal")
        title.setWordWrap(True)
        self.output_layout.addWidget(title)

        meta = QLabel(f"Source: {manual['source_ref']}")
        meta.setObjectName("muted")
        meta.setWordWrap(True)
        self.output_layout.addWidget(meta)
        self._add_zero_shot(manual)

        self.prompt_edit = PromptEdit(manual["prompt"], self.output_scroll)
        self.prompt_edit.setFixedHeight(400)
        self.output_layout.addWidget(self.prompt_edit, 1)

        config = manual["config"]
        config_label = QLabel(
            f"temperature {config['temperature']} · top_p {config['top_p']} · {config['rationale']}"
        )
        config_label.setObjectName("muted")
        config_label.setWordWrap(True)
        self.output_layout.addWidget(config_label)

        self.output_layout.addStretch(1)

    # ── рендер результата ─────────────────────────────────────────
    def render(self, result: dict, *, source_thoughts: str | None = None) -> None:
        self._clear_output()
        brief = result["brief"]
        choice = result["choice"]
        synthesis = result["synthesis"]
        config = synthesis["config"]
        source_target = next((key for key in PROMPT_TARGETS if isinstance(result.get(f"{key}Guidance"), dict)), None)
        guidance = result.get(f"{source_target}Guidance") if source_target else None

        goal = QLabel(brief.get("topic") or brief["goal"])
        goal.setObjectName("goal")
        goal.setWordWrap(True)
        self.output_layout.addWidget(goal)
        if brief.get("topic"):
            description = QLabel(brief["goal"])
            description.setObjectName("muted")
            description.setWordWrap(True)
            self.output_layout.addWidget(description)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        for text in (
            f"type: {brief['task_type']}",
            f"language: {brief['language']}",
            f"stakes: {brief['stakes']}",
        ):
            chip = QLabel(text)
            chip.setObjectName("chip")
            chips.addWidget(chip)
        chips.addStretch(1)
        self.output_layout.addLayout(chips)

        fmt = QLabel(f"Format: {brief['output_format']}")
        fmt.setObjectName("muted")
        fmt.setWordWrap(True)
        self.output_layout.addWidget(fmt)

        if brief.get("assumptions"):
            assumptions = QLabel("Assumptions: " + "; ".join(brief["assumptions"]))
            assumptions.setObjectName("muted")
            assumptions.setWordWrap(True)
            self.output_layout.addWidget(assumptions)

        self._add_zero_shot(result)

        tech = QFrame()
        tech.setObjectName("tech")
        tech_box = QVBoxLayout(tech)
        tech_box.setContentsMargins(0, 4, 0, 0)
        tech_box.setSpacing(6)

        head = QHBoxLayout()
        name = QLabel(choice["name"])
        name.setObjectName("section")
        name.setWordWrap(True)
        confidence = QLabel("Official sources" if guidance is not None else f"confidence {round(choice['confidence'] * 100)}%")
        confidence.setObjectName("muted")
        confidence.setWordWrap(True)
        head.addWidget(name, 1)
        head.addWidget(confidence)
        if guidance is None:
            percent = max(0, min(100, round(choice["confidence"] * 100)))
            meter = QWidget()
            meter.setObjectName("confidenceSquares")
            meter.setAccessibleName(f"Confidence {percent}%")
            meter.setToolTip(f"Confidence {percent}%")
            squares = QHBoxLayout(meter)
            squares.setContentsMargins(0, 0, 0, 0)
            squares.setSpacing(3)
            filled = (percent + 5) // 10
            for index in range(10):
                square = QFrame()
                square.setFixedSize(6, 6)
                square.setStyleSheet(f"background: {'#e1b72c' if index < filled else '#e5e1d4'}; border: none;")
                squares.addWidget(square)
            meter.setFixedSize(87, 10)
            head.addWidget(meter, 0, Qt.AlignmentFlag.AlignVCenter)
        tech_box.addLayout(head)

        why = QLabel(f"Why: {choice['reason']}")
        why.setWordWrap(True)
        why.setObjectName("muted")
        tech_box.addWidget(why)

        why_not = QLabel(f"Why not a cheaper method: {choice['whyNotCheaper']}")
        why_not.setWordWrap(True)
        why_not.setObjectName("muted")
        tech_box.addWidget(why_not)

        self.output_layout.addWidget(tech)

        self.prompt_edit = PromptEdit(synthesis["prompt"], self.output_scroll, source_target)
        self.prompt_edit.setFixedHeight(340)
        self.output_layout.addWidget(self.prompt_edit)

        config_label = QLabel(
            f"temperature {config['temperature']} · top_p {config['top_p']} · "
            f"max_tokens {config['max_tokens']}"
        )
        config_label.setObjectName("muted")
        config_label.setWordWrap(True)
        self.output_layout.addWidget(config_label)

        rationale = QLabel(config["rationale"])
        rationale.setObjectName("muted")
        rationale.setWordWrap(True)
        self.output_layout.addWidget(rationale)

        if synthesis["warnings"]:
            warn = QLabel("\n".join(f"• {w}" for w in dict.fromkeys(synthesis["warnings"])))
            warn.setObjectName("warn")
            warn.setWordWrap(True)
            self.output_layout.addWidget(warn)

        for index, alt in enumerate(result.get("alternatives") or [], start=2):
            alt_choice = alt["choice"]
            alt_synth = alt["synthesis"]

            head = QLabel(f"Variant {index}: {alt_choice['name']}")
            head.setObjectName("section")
            head.setWordWrap(True)
            head.setStyleSheet("margin-top: 4px; border-top: 1px solid #d8c593; padding-top: 22px;")
            self.output_layout.addWidget(head)

            why = QLabel(alt_choice["reason"])
            why.setObjectName("muted")
            why.setWordWrap(True)
            self.output_layout.addWidget(why)

            box = PromptEdit(alt_synth["prompt"], self.output_scroll, source_target)
            box.setFixedHeight(260)
            self.output_layout.addWidget(box)

            cfg = alt_synth["config"]
            meta = QLabel(f"temperature {cfg['temperature']} · {cfg['max_tokens']}")
            meta.setObjectName("muted")
            self.output_layout.addWidget(meta)

        if isinstance(guidance, dict) and source_target:
            source_title = QLabel(f"{PROMPT_TARGETS[source_target][0]} rules · {guidance.get('rule_set_version', 'unknown')} · checked {guidance.get('verified_at', 'unknown')}")
            source_title.setObjectName("section")
            source_title.setWordWrap(True)
            self.output_layout.addWidget(source_title)
            variants = guidance.get("variants", [])
            for variant_index, variant in enumerate(variants, 1):
                usage = QLabel(f"Variant {variant_index} rules: {', '.join(variant.get('rule_ids', []))}")
                usage.setObjectName("muted")
                usage.setWordWrap(True)
                self.output_layout.addWidget(usage)
            for rule in guidance.get("rules", []):
                url = rule.get("source_url", "")
                if not is_official_source(url, source_target):
                    continue
                label = QLabel(f"<a href=\"{escape(url, quote=True)}\">{escape(rule.get('id', ''))} · {escape(rule.get('source_section', 'Source'))}</a>")
                label.setOpenExternalLinks(True)
                label.setWordWrap(True)
                label.setToolTip(rule.get("rule_text", ""))
                self.output_layout.addWidget(label)

        footer = QLabel(f"Techniques filtered out: {len(result['rejected'])}")
        footer.setObjectName("muted")
        self.output_layout.addWidget(footer)

        self.output_layout.addStretch(1)


QSS += """
QPushButton#segment { background: rgba(255, 245, 214, 222); border: 1px solid #d8c593; color: #665b42;
  font-size: 12px; padding: 8px 4px; border-radius: 0; }
QPushButton#segment[first="true"] { border-top-left-radius: 9px; border-bottom-left-radius: 9px; }
QPushButton#segment[last="true"] { border-top-right-radius: 9px; border-bottom-right-radius: 9px; }
QPushButton#segment:hover { background: #fff0c6; }
QPushButton#segment:checked { background: #f4ca38; border-color: #e1b72c; color: #352b10; font-weight: 600; }
QToolButton#disclosure { background: transparent; border: none; color: #665b42; font-size: 12px; font-weight: 600; padding: 4px 0; }
QToolButton#disclosure:hover { color: #332e24; }
QToolButton#disclosure[field="true"] { color: #74694f; font-size: 10px; font-weight: 500; letter-spacing: 2px; padding: 2px 0; }
QToolButton#disclosure[field="true"]:hover { color: #4a4232; }
QPushButton#segment:disabled { color: #b5ab90; background: rgba(250, 241, 214, 160); }
QPushButton#segment:checked:disabled { background: #efdc9c; color: #8a7a4e; border-color: #dcc583; }
QLabel#meta { color: #665d49; font-size: 12px; }
QFrame#variantSegments { background: transparent; border: none; }
QListView#historySuggestions { background: #fff8e7; color: #4a4232; border: 1px solid #d8c593; border-radius: 9px; padding: 4px; outline: none; font-size: 13px; }
QListView#historySuggestions::item { padding: 7px 10px; border: none; border-radius: 5px; }
QListView#historySuggestions::item:hover, QListView#historySuggestions::item:selected { background: #f6e5b3; color: #4a4232; }
QFrame#techItem[selected="true"] { background: #fbe7a1; border: 2px solid #e1b72c; }
QFrame#techItem[selected="true"]:hover { background: #f8df8a; }
QTabWidget#variantTabs::pane { border: none; background: transparent; top: 12px; }
QTabWidget#variantTabs > QWidget { background: transparent; }
QTabWidget#variantTabs QTabBar { background: transparent; }
QTabWidget#variantTabs::tab-bar { alignment: left; }
QTabWidget#settingsTabs::tab-bar { alignment: left; }
QTabWidget#settingsTabs QTabBar { background: rgba(120, 96, 30, 26); border-radius: 8px; }
QTabWidget#settingsTabs QTabBar::tab { background: transparent; border: none; border-radius: 6px; margin: 2px; padding: 4px 16px; color: #6b6047; font-size: 12px; }
QTabWidget#settingsTabs QTabBar::tab:hover { background: rgba(255, 255, 255, 110); }
QTabWidget#settingsTabs QTabBar::tab:selected { background: #f4ca38; color: #2f260c; font-weight: 600; }
QTabWidget#settingsTabs::pane { border: none; top: 6px; }
QDialog QLabel#goal { font-size: 17px; letter-spacing: -0.3px; }
QLabel#title { font-family: 'Avenir Next'; font-size: 17px; letter-spacing: -0.2px; color: #2b2412; }
QDialog QPushButton#primary, QDialog QPushButton#ghost { min-height: 28px; max-height: 28px; padding: 0 14px; }
QDialog QPushButton#primary[compact="true"], QDialog QPushButton#ghost[compact="true"] {
  min-height: 22px; max-height: 22px; padding: 0 12px; font-size: 12px; border-radius: 7px; }
"""

class PromptaWindow(MainWindow):
    """Prompt-first layout on top of MainWindow's logic.

    The finished prompt comes first (variants as tabs); brief, zero-shot baseline, technique rationale
    and sources fold into "How this prompt was built". The target is one segmented switch, while the
    technique and variant count live under "Advanced". MainWindow's hidden target checkboxes remain
    the single source of truth, so history restore and request building are unchanged.
    """

    def __init__(self) -> None:
        self.visible_warnings: list[str] = []
        self.catalog_summary = ""
        self._variants_before_manual: int | None = None
        super().__init__()
        self._restyle_input()
        self.build_label = "Build prompt   ⌘↵"
        self.run_button.setText(self.build_label)
        self.run_button.setToolTip("⌘↵ builds the prompt")
        self.single_run_button = True  # Build turns into Stop while running; no separate button
        self.cancel_button.hide()
        self.status.setText("")
        # History is a picker like every other: the same button, chevron and panel with search inside.
        self.history_search.hide()  # MainWindow's filter field stays for restore logic; the picker replaces it here
        self.history_picker = IconDropdown("search.svg", "Search history", searchable=True, popup_width=480,
                                           search_placeholder="Search requests and prompts")
        self.history_picker.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_picker.changed.connect(self._on_history_picked)
        self.history_picker.deleteRequested.connect(self._on_history_delete)
        self.header_layout.insertWidget(self.header_layout.indexOf(self.clear_button), self.history_picker)
        self._sync_history_row()
        self._fit_input_column()  # the restyled column (target switch with Open) is wider than at construction
        self._restyle_settings()

    # ── settings: same controls and rhythm as the main window ─────
    def _restyle_settings(self) -> None:
        self.settings_tabs.setObjectName("settingsTabs")
        self.settings_tabs.tabBar().setDrawBase(False)
        self.settings_tabs.tabBar().setExpanding(False)
        self.settings_tabs.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        self.settings_tabs.tabBar().setUsesScrollButtons(False)
        # Tab sizes were measured with the old style; re-polish so the new padding counts.
        for widget in (self.settings_tabs, self.settings_tabs.tabBar()):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        for child in self.settings_dialog.findChildren(QWidget):
            if isinstance(child, QLineEdit) and not isinstance(child.parentWidget(), QComboBox):
                child.setFixedHeight(CONTROL_HEIGHT)
            elif isinstance(child, (QComboBox, Dropdown)):
                child.setFixedHeight(CONTROL_HEIGHT)
            elif isinstance(child, QPushButton) and child.objectName() in ("ghost", "primary"):
                child.setFixedHeight(CONTROL_HEIGHT)
        self.refresh_button.setText("")
        self.refresh_button.setIcon(QIcon(str(ROOT / "desktop" / "refresh.svg")))
        self.refresh_button.setIconSize(QSize(14, 14))
        self.refresh_button.setFixedSize(CONTROL_HEIGHT, CONTROL_HEIGHT)
        self.refresh_button.setToolTip("Refresh models from Ollama")

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
            items.append({
                "key": str(index),
                "label": label,
                # The date, and the request when the topic does not already say it.
                "hint": entry['created_at'][:10] + ("" if request.casefold() == label.casefold() else f" · {request[:90]}"),
                "search": json.dumps(entry['payload'], ensure_ascii=False),
                "deletable": True,
            })
        picker.set_items(items)
        shown = getattr(self, "_shown_entry", None)
        previous = picker.blockSignals(True)
        picker.set_current(str(shown) if isinstance(shown, int) and 0 <= shown < len(self._history_items) else "")
        picker.blockSignals(previous)
        picker.setVisible(bool(self._history_items))

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
        self.history_search.clear()
        self._filter_history("", selected=item_index)
        combo_index = self.history.findData(item_index)
        if combo_index > 0:
            self.history.setCurrentIndex(combo_index)
            self._on_history_selected(combo_index)

    # ── left column ───────────────────────────────────────────────
    def _restyle_input(self) -> None:
        card_layout = self.thoughts.parentWidget().layout()

        grid = find_layout(card_layout, self.prompt_model)
        # Open-weight models are the last segment; choosing it reveals the model picker below the switch.
        segments = TARGET_SEGMENTS + [("openModel", "Open")]
        self._open_mode = False
        for key, _ in segments[1:]:
            getattr(self, f"{key}_only").hide()
        row = QWidget()
        self.target_track = row
        row.setObjectName("segmentTrack")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(2, 2, 2, 2)
        row_layout.setSpacing(2)
        self.segments = QButtonGroup(self)
        self.segments.setExclusive(True)
        for index, (key, label) in enumerate(segments):
            button = QPushButton(label)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("first", index == 0)
            button.setProperty("last", index == len(segments) - 1)
            button.setProperty("target", key)
            button.setAccessibleName("Target: open-weight model" if key == "openModel" else f"Target: {label}")
            button.setToolTip("Use the prompting-technique catalog" if key == GENERAL_TARGET
                              else "Open-weight model: build from its pinned official model card" if key == "openModel"
                              else f"Use saved official {label} guidance only. Your generator model stays the same.")
            self.segments.addButton(button)
            row_layout.addWidget(button, 1)
        self.segments.buttonClicked.connect(self._on_segment_clicked)
        grid.addWidget(self._mini_label("Written for"), 0, 0, 1, 2)  # pairs with "Runs in" below
        grid.addWidget(row, 1, 0, 1, 2)
        self.prompt_model.setItemText(0, "— choose an open-weight model —")
        # One control for open-weight models: the Open segment opens this picker under the switch and shows the choice.
        self.prompt_model.popup_anchor = row
        self.open_segment = next(b for b in self.segments.buttons() if b.property("target") == "openModel")
        # The same chevron icon as every picker: this segment opens the list of open-weight models.
        self.open_segment.setProperty("chevron", True)
        chevron = QLabel()
        chevron.setPixmap(QIcon(str(ROOT / "desktop" / "chevron-down.svg")).pixmap(10, 10))
        chevron.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        chevron.setStyleSheet("background: transparent;")
        chevron_row = QHBoxLayout(self.open_segment)
        chevron_row.setContentsMargins(0, 0, 7, 0)
        chevron_row.addStretch(1)
        chevron_row.addWidget(chevron, 0, Qt.AlignmentFlag.AlignVCenter)
        # The chosen open-weight model, named under the switch (a caption, not a second picker); click to change it.
        self.open_caption = QPushButton()
        self.open_caption.setObjectName("modelLine")
        self.open_caption.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_caption.setToolTip("Change the open-weight model")
        self.open_caption.clicked.connect(self.prompt_model.showPopup)
        self.open_caption.hide()
        grid.addWidget(self.open_caption, 2, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
        self.prompt_model.currentIndexChanged.connect(lambda *_: self._sync_open_segment())
        for key in PROMPT_TARGETS:
            getattr(self, f"{key}_only").toggled.connect(self._sync_segments)

        variants_row = find_layout(card_layout, self.variants)
        variants_label = next(variants_row.itemAt(i).widget() for i in range(variants_row.count())
                              if isinstance(variants_row.itemAt(i).widget(), QLabel))
        self.advanced = Disclosure("Technique", field_label=True, collapsible=False)
        self.advanced.body_layout.setContentsMargins(0, 4, 0, 8)
        self.advanced.body_layout.setSpacing(6)
        self.technique.set_multi(True)
        self.technique._placeholder = "— automatic —"
        self.technique.set_current_keys([])
        for widget in (self.technique_label, self.technique):
            card_layout.removeWidget(widget)
            self.advanced.body_layout.addWidget(widget)
        for widget in (variants_label, self.variants):
            variants_row.removeWidget(widget)
        # Full-width segmented switch under the technique picker, with a plain caption saying what the numbers are.
        variants_label.hide()
        variants_label.deleteLater()
        self.advanced.body_layout.addSpacing(6)
        self.variants_caption = muted_label("Variants · prompts built with different techniques to compare", "variantsCaption")
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
        for widget in [self.variants, *buttons]:
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        divider = self.findChild(QFrame, "inputDivider")
        if divider is not None:
            divider.hide()
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
        self.execution_profile.setToolTip("Where the generated prompt will be used. "
                                          "Tool steps in the prompt follow what that environment can do.")
        runs_in.addWidget(self.execution_profile)
        # Where the prompt goes and where it runs belong together: right under the target switch.
        grid_index = next(i for i in range(card_layout.count()) if card_layout.itemAt(i).layout() is grid)
        runs_in.setContentsMargins(0, 6, 0, 4)
        card_layout.insertLayout(grid_index + 1, runs_in)
        self.technique.changed.connect(self._update_advanced_title)
        self.variants.buttons.idClicked.connect(self._update_advanced_title)
        self.advanced.button.toggled.connect(self._update_advanced_title)
        self.technique_label.hide()  # its count moves into the Advanced title
        # One control height for fields and segmented tracks so rows line up.
        for widget in (self.history_search, self.history, self.prompt_model, self.technique, self.target_track, self.variants,
                       self.execution_profile):
            widget.ensurePolished()  # its own stylesheet would reset the minimum height when polished later
            widget.setFixedHeight(CONTROL_HEIGHT)
        for button in [*self.segments.buttons(), *self.variants.buttons.buttons()]:
            button.setFixedHeight(CONTROL_HEIGHT - 4)
        self.run_button.setFixedHeight(ACTION_HEIGHT)
        self.cancel_button.setFixedHeight(ACTION_HEIGHT)
        self._sync_segments()

    def _on_techniques_loaded(self, techniques: list) -> None:
        super()._on_techniques_loaded(techniques)
        if techniques:
            procedures = sum(1 for item in techniques if item.get("status") == "procedure")
            ready = len(techniques) - procedures
            self.catalog_summary = f"{ready} technique{'s' if ready != 1 else ''}" + (
                f" + {procedures} procedure{'s' if procedures != 1 else ''}" if procedures else "") + " available"
            self._update_advanced_title()

    def _sync_open_segment(self) -> None:
        button = getattr(self, "open_segment", None)
        if button is None:
            return
        name = self.prompt_model.currentText() if self.prompt_model.currentData() else ""
        button.setText("Open")
        button.setToolTip(f"Open-weight model: {name} · click to change" if name
                          else "Open-weight model: build from its pinned official model card")
        caption = getattr(self, "open_caption", None)
        if caption is not None:
            caption.setText(f"{name} · open-weight model" if name else "")
            caption.setVisible(bool(name) and self._selected_target() == "openModel")

    def run_pipeline(self, *, revised_brief: dict | None = None) -> None:
        if getattr(self, "_open_mode", False) and not self.openModel_only.isChecked() and not self._running():
            self.status.setText("Choose an open-weight model")
            self.prompt_model.showPopup()
            return
        super().run_pipeline(revised_brief=revised_brief)

    def _on_segment_clicked(self, button: QPushButton) -> None:
        key = button.property("target")
        self._open_mode = key == "openModel"
        if key == "openModel":
            for target in PROMPT_TARGETS:
                if target != "openModel":
                    getattr(self, f"{target}_only").setChecked(False)
            self._sync_segments()
            QTimer.singleShot(0, self.prompt_model.showPopup)  # pick or change the model right from the segment
            return
        if key == GENERAL_TARGET:
            for target in PROMPT_TARGETS:
                getattr(self, f"{target}_only").setChecked(False)
            previous = self.prompt_model.blockSignals(True)
            self.prompt_model.setCurrentIndex(0)
            self.prompt_model.blockSignals(previous)
        else:
            getattr(self, f"{key}_only").setChecked(True)
        self._sync_segments()

    def _sync_segments(self, *_: object) -> None:
        selected = self._selected_target()
        if selected == "openModel":
            self._open_mode = True
        elif selected is not None:
            self._open_mode = False
        shown = "openModel" if getattr(self, "_open_mode", False) else selected
        self.segments.setExclusive(False)
        for button in self.segments.buttons():
            key = button.property("target")
            button.setChecked(key == shown or (key == GENERAL_TARGET and shown is None))
        self.segments.setExclusive(True)
        self.prompt_model.hide()  # opened from the Open segment; the segment shows the chosen model
        self._sync_open_segment()
        if hasattr(self, "advanced"):
            self._update_advanced_title()

    def _update_advanced_title(self, *_: object) -> None:
        extra = []
        keys = self.technique.current_keys()
        # The Open segment counts as a target even before a model is picked: techniques are for Any only.
        target = self._selected_target() or ("openModel" if getattr(self, "_open_mode", False) else None)
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

    def clear_workspace(self) -> None:
        super().clear_workspace()
        self.status.setText("")

    def on_finished(self, data: dict) -> None:
        super().on_finished(data)
        manual = data.get("manual") if data.get("ok") and not self._discard_result else None
        if manual and len(manual.get("variants") or []) > 1:
            built = len(manual["variants"])
            failed = len(manual.get("failed") or [])
            self.status.setText(f"{built} techniques built" + (f" · {failed} failed, see below the prompt" if failed else ""))
        if data.get("ok") and data.get("result") and not self._discard_result:
            count = len(self.visible_warnings)
            name = data["result"]["choice"]["name"]
            self.status.setText(f"{name} · {count} warning{'s' if count != 1 else ''} below the prompt" if count else f"{name} · ready")

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
        return f"Task:\n{brief.get('goal') or self.thoughts.toPlainText().strip()}"

    def _prompt_view(self, prompts: list[tuple[str, str]], target: str | None, zero_shot: str, named_tabs: bool = False) -> QWidget:
        """Tabs: Variant 0 is always the zero-shot baseline; the built prompts follow and the first one is selected."""
        def editor(text: str) -> PromptEdit:
            box = PromptEdit(text, self.output_scroll, target)
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
        tabs.addTab(zero, "No technique" if by_name else "Variant 0")
        tabs.setTabToolTip(0, "Zero-shot: the task stated directly, without a prompting technique")
        self.prompt_edit = editor(prompts[0][1])
        tabs.addTab(self.prompt_edit, names[0] if by_name else "Variant 1")
        for index, (_, prompt) in enumerate(prompts[1:], 2):
            tabs.addTab(editor(prompt), names[index - 1] if by_name else f"Variant {index}")
        for index, (name, _) in enumerate(prompts, 1):
            tabs.setTabToolTip(index, name)

        for index in range(tabs.count()):  # the user's edits go into the saved result
            editor = tabs.widget(index)
            editor.textChanged.connect(lambda i=index, e=editor: self._prompt_edited(i, e.toPlainText()))
            base = tabs.tabText(index)
            editor.on_edited = lambda edited, i=index, b=base: tabs.setTabText(i, f"{b} •" if edited else b)

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

    def _prompt_edited(self, variant: int, text: str) -> None:
        """Remember the edit and save it shortly after typing stops."""
        if self._shown_entry is None:
            return
        if not hasattr(self, "_edit_timer"):
            self._edit_timer = QTimer(self)
            self._edit_timer.setSingleShot(True)
            self._edit_timer.timeout.connect(self._save_prompt_edits)
            self._pending_edits: dict[tuple[int, int], str] = {}
        self._pending_edits[(self._shown_entry, variant)] = text
        self._edit_timer.start(700)

    @staticmethod
    def _prompt_at(kind: str, payload: dict, variant: int) -> str:
        if variant == 0:
            return payload.get("zeroShotPrompt", "")
        if kind == "manual":
            return payload["variants"][variant - 1]["prompt"] if payload.get("variants") else payload["prompt"]
        return payload["synthesis"]["prompt"] if variant == 1 else payload["alternatives"][variant - 2]["synthesis"]["prompt"]

    @classmethod
    def _apply_prompt_edit(cls, kind: str, payload: dict, variant: int, text: str) -> None:
        """Variant 0 is the zero-shot baseline; 1 is the first built prompt; the rest follow in order.
        The model's text is kept under originalPrompts on the first edit, so it can be restored."""
        originals = payload.setdefault("originalPrompts", {})
        originals.setdefault(str(variant), cls._prompt_at(kind, payload, variant))
        if originals[str(variant)] == text:
            del originals[str(variant)]
        if not originals:
            del payload["originalPrompts"]
        if variant == 0:
            payload["zeroShotPrompt"] = text
        elif kind == "manual":
            if payload.get("variants"):
                payload["variants"][variant - 1]["prompt"] = text
            if variant == 1:
                payload["prompt"] = text
        elif variant == 1:
            payload["synthesis"]["prompt"] = text
        else:
            payload["alternatives"][variant - 2]["synthesis"]["prompt"] = text

    def _save_prompt_edits(self) -> None:
        pending, self._pending_edits = self._pending_edits, {}
        touched: set[int] = set()
        for (entry_index, variant), text in pending.items():
            if not 0 <= entry_index < len(self._history_items):
                continue
            entry = self._history_items[entry_index]
            try:
                self._apply_prompt_edit(entry["kind"], entry["payload"], variant, text)
            except (KeyError, IndexError, TypeError):
                continue
            touched.add(entry_index)
        for entry_index in touched:
            entry = self._history_items[entry_index]
            if entry.get("id") is None:
                continue  # never reached the disk: the edit lives in this window only
            try:
                self.history_store.update_payload(entry["id"], entry["payload"])
            except (OSError, sqlite3.Error):
                self.history_notice.setText("Could not save your prompt edit to disk. It stays in this window.")
                self.history_notice.show()

    def closeEvent(self, event) -> None:  # noqa: N802
        if getattr(self, "_edit_timer", None) is not None and self._edit_timer.isActive():
            self._edit_timer.stop()
            self._save_prompt_edits()  # do not lose the last keystrokes on quit
        super().closeEvent(event)

    ZERO_SHOT_NOTE = "Zero-shot: the task stated directly, without a prompting technique. A baseline to compare the variants with."

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
        original_request = source_thoughts if source_thoughts is not None else self.thoughts.toPlainText().strip()
        questions = self._brief_questions(brief)
        assumptions = [item.strip() for item in brief.get("assumptions") or [] if isinstance(item, str) and item.strip()]
        if not questions and not assumptions:
            return

        box = QFrame()
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
            self._sync_build_label()

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
            return self.thoughts.toPlainText().strip() == original_request

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
                revised_questions.append({"question": row["question"], "default": value} if value else {"question": row["question"]})
            revised_assumptions = [row["field"].text().strip() for row in assumption_rows
                                   if not row["removed"] and row["field"].text().strip()]
            return {**brief, "assumptions": revised_assumptions, "questions": revised_questions}

        def apply() -> None:  # Enter in a card field does what the Build button does
            self.run_pipeline()

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
        self._set_assumptions_card(box)
        self._sync_build_label()

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
        label = QLabel(f"Official {escape(str(name))} rules: {' · '.join(parts)}"
                       f'<span style="color:#9a8d6c"> · checked {checked}</span>')
        label.setObjectName("muted")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setOpenExternalLinks(True)
        label.setWordWrap(True)
        label.setToolTip(f"Rule set {guidance.get('rule_set_version', 'unknown')}")
        label.linkHovered.connect(lambda href: QToolTip.showText(QCursor.pos(), hints.get(href, href), label) if href else None)
        return label

    def render(self, result: dict, *, source_thoughts: str | None = None) -> None:
        self._clear_output()
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
                name = guidance.get("target") if source_target == "openModel" else PROMPT_TARGETS[source_target][0]
                own = item_choice["name"]
                return own if "guidance" in own.lower() else f"{own} · official {name} guidance"
            confidence = item_choice.get("confidence")
            return item_choice["name"] + (f" · confidence {round(confidence * 100)}%" if isinstance(confidence, (int, float)) else "")
        metas = ["Zero-shot · baseline without a technique", meta_for(choice)] + [meta_for(a["choice"]) for a in alternatives]
        meta_label = muted_label(metas[1], "meta")
        layout.addWidget(meta_label)
        self._add_usage(result)
        layout.addSpacing(10)
        self._add_brief_refinement(brief, source_thoughts)
        prompts = [(choice["name"], synthesis["prompt"])] + [(a["choice"]["name"], a["synthesis"]["prompt"]) for a in alternatives]
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
        self._clear_output()
        variants = manual.get("variants") or [
            {"technique": manual["technique"], "prompt": manual["prompt"], "config": manual["config"], "source_ref": manual["source_ref"]}
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
        tabs = self._prompt_view([(v["technique"]["name"], v["prompt"]) for v in variants], None, self._zero_shot_text(manual), named_tabs=True)
        self._mark_originals(tabs, manual)
        self.output_layout.addWidget(tabs)
        self.output_layout.addSpacing(BLOCK_GAP)
        failed = manual.get("failed") or []
        self.visible_warnings = [f"{f['name']}: {f['error']}" for f in failed]
        if failed:
            self.output_layout.addWidget(muted_label("\n".join(f"• Not built — {w}" for w in self.visible_warnings), "warn"))
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
            own = [muted_label(variant["why"])] if variant.get("why") else []
            own += [field_label("Method source"), muted_label(variant["source_ref"])]
            pages.append(own)
        for widgets in pages:
            for widget in widgets:
                body.addWidget(widget)
        self.output_layout.addWidget(details)
        self.output_layout.addStretch(1)
        self._follow_tabs(tabs, pages)
        tabs.currentChanged.connect(lambda index: meta_label.setText(metas[index]))


# Flat, borderless controls: soft translucent fills, a focus ring only when focused,
# iOS-style segmented tracks. Applied last so it overrides the older bordered look.
QSS += """
QPlainTextEdit { background: rgba(255, 255, 255, 120); border: 1px solid transparent; border-radius: 12px; padding: 12px; }
QPlainTextEdit:hover { background: rgba(255, 255, 255, 150); }
QPlainTextEdit:focus { background: rgba(255, 255, 255, 175); border: 1px solid #e1b72c; }
QPlainTextEdit#prompt { background: #3f3f3f; border: none; border-radius: 12px; padding: 12px; }
QPlainTextEdit#prompt:focus { background: #444444; border: none; }
QLineEdit, QComboBox, QPushButton#picker { background: rgba(255, 255, 255, 120); border: 1px solid transparent; border-radius: 8px; padding: 3px 10px; min-height: 0; }
QPushButton#picker { padding-right: 28px; }  /* room for the chevron every picker shows */
QLineEdit:hover, QComboBox:hover, QPushButton#picker:hover { background: rgba(255, 255, 255, 160); border-color: transparent; }
QLineEdit:focus, QComboBox:focus, QPushButton#picker:focus { background: rgba(255, 255, 255, 185); border: 1px solid #e1b72c; }
QPushButton#picker:pressed { background: rgba(255, 255, 255, 200); }
QPushButton#picker:disabled { background: rgba(255, 255, 255, 60); color: #b0a78e; border-color: transparent; }

QWidget#segmentTrack, QFrame#segmentTrack { background: rgba(120, 96, 30, 26); border: none; border-radius: 8px; }
QPushButton#segment, QPushButton#segment[first="true"], QPushButton#segment[last="true"] {
  background: transparent; border: none; border-radius: 6px; color: #6b6047; font-size: 12px; padding: 0 4px; }
QPushButton#segment:hover { background: rgba(255, 255, 255, 110); }
QPushButton#segment[chevron="true"] { padding: 0 18px 0 4px; }  /* text clear of the chevron, like the pickers */
QPushButton#segment:checked { background: #f4ca38; color: #2f260c; font-weight: 600; }
QPushButton#segment:focus { border: none; }
QPushButton#segment:disabled { background: transparent; color: #b8ad8f; }
QPushButton#segment:checked:disabled { background: rgba(244, 202, 56, 110); color: #8a7a4e; }

QPushButton#buildPrompt { border: none; border-radius: 10px; }
QPushButton#buildPrompt:focus { border: none; }
QPushButton#buildPrompt:disabled { background: rgba(244, 202, 56, 140); color: #7d6a33; }
QPushButton#ghost, QPushButton#primary { background: rgba(120, 96, 30, 22); border: none; border-radius: 9px; color: #5f4f1f; }
QPushButton#ghost:hover, QPushButton#primary:hover { background: rgba(120, 96, 30, 36); }
QPushButton#ghost:pressed, QPushButton#primary:pressed { background: rgba(120, 96, 30, 50); }
QPushButton#ghost:disabled, QPushButton#primary:disabled { background: rgba(120, 96, 30, 12); color: #b8ad8f; }
QPushButton#primary { background: #f4ca38; color: #352b10; font-weight: 600; }  /* our yellow, as Build prompt */
QPushButton#primary:hover { background: #e9bc24; }
QPushButton#primary:pressed { background: #d9aa16; }
QPushButton#primary:disabled { background: rgba(244, 202, 56, 140); color: #7d6a33; }
QPushButton#settings { border: none; border-radius: 8px; }
QPushButton#settings:hover { background: rgba(120, 96, 30, 26); }
QPushButton:focus { border: none; }

QTabBar::tab { background: transparent; border: none; border-radius: 8px; color: #7a6d4f; padding: 7px 14px; margin-right: 4px; }
QTabBar::tab:hover { background: rgba(255, 255, 255, 110); }
QTabBar::tab:selected { background: rgba(255, 255, 255, 200); color: #3a3121; font-weight: 600; }

QFrame#techniquePopup, QFrame#historyPopup { background: #fffaee; border: 1px solid rgba(120, 96, 30, 40); border-radius: 12px; }
/* One row style for every dropdown: list rows (history, open-weight, MCP) and Dropdown items. */
QFrame#techItem { background: transparent; border: none; border-radius: 6px; }
QFrame#techItem:hover { background: rgba(120, 96, 30, 26); }
QFrame#techItem[selected="true"] { background: #f6e5b3; border: none; }
QFrame#techItem[selected="true"]:hover { background: #f1dc9f; }
QLabel#techName { font-size: 13px; font-weight: 400; color: #4a4232; }
QLabel#techHint { font-size: 12px; color: #82745a; }
QListWidget#historyList { background: transparent; font-size: 13px; }
QListWidget#historyList::item { padding: 7px 30px 7px 10px; border: none; border-radius: 6px; color: #4a4232; }
QListWidget#historyList::item:hover { background: rgba(120, 96, 30, 26); color: #4a4232; }
QListWidget#historyList::item:selected { background: #f6e5b3; color: #4a4232; }
QListWidget#historyList::item:selected:hover { background: #f1dc9f; }
QFrame#techniquePopup QScrollArea, QFrame#techniquePopup QWidget#scrollContent { background: transparent; }
QTreeWidget#libraryTree { background: rgba(255, 255, 255, 120); border: none; border-radius: 12px; }
QListView#historySuggestions { background: transparent; border: none; padding: 5px; }
QLabel#chip { background: rgba(120, 96, 30, 20); border: none; border-radius: 7px; color: #5f5440; }
QLabel#warn { background: rgba(244, 170, 40, 36); border: none; border-radius: 10px; }
QLabel#error { background: rgba(220, 80, 70, 30); border: none; border-radius: 10px; }
QCheckBox::indicator { border: none; background: rgba(120, 96, 30, 30); border-radius: 4px; }
QFrame#questionsCard { background: rgba(255, 248, 225, 235); border: none; border-radius: 10px; }
QFrame#questionsCard QLineEdit { background: rgba(255, 255, 255, 185); }
QFrame#questionsCard QPlainTextEdit#answer { background: rgba(255, 255, 255, 185); border: 1px solid transparent; border-radius: 7px; padding: 1px 6px; color: #332e24; font-size: 13px; }
QFrame#questionsCard QPlainTextEdit#answer:hover { border-color: #e6d7ad; }
QFrame#questionsCard QPlainTextEdit#answer:focus { border-color: #c69b12; }
QPushButton#removeAssumption, QPushButton#deleteItem { background: transparent; border: none; border-radius: 6px; }
QPushButton#deleteItem:hover { background: rgba(216, 197, 147, 90); }
QPushButton#removeAssumption:hover { background: rgba(216, 197, 147, 90); }
QPushButton#addAssumption { background: transparent; border: none; color: #80620a; font-size: 12px; padding: 4px 4px; }
QPushButton#addAssumption:hover { color: #5c4606; }
QLabel#cardTitle { color: #3a3121; font-size: 13px; font-weight: 600; }
QLineEdit#historySearch, QLineEdit#historySearch:focus, QLineEdit#historySearch:hover { border: none; }
QLabel#wordmark { color: rgba(74, 58, 24, 46); background: transparent; }
QLabel#slogan { color: rgba(74, 58, 24, 46); font-size: 12px; font-weight: 500; letter-spacing: 2.5px; background: transparent; }
QPushButton#modelLine { background: transparent; border: none; color: #8a7d5c; font-size: 11px; padding: 2px 0; text-align: left; }
QPushButton#modelLine:hover { color: #5c4606; text-decoration: underline; }
QLabel#variantsCaption { color: #8a7d5c; font-size: 11px; }
QLabel#question { color: #4f4635; font-size: 12px; }
QLabel#briefGoal { color: #3a3121; font-size: 13px; }
QLabel#briefMeta { color: #9a8d6c; font-size: 11px; padding: 3px 0; }
QPushButton#restorePrompt { background: transparent; border: none; padding: 0 2px; color: #f4ca38; font-size: 11px; }
QPushButton#restorePrompt:hover { color: #ffe08a; text-decoration: underline; }
/* Hover hints in the app's style: warm paper, brown text, thin border, like the dropdown panels. */
QToolTip { background-color: #fffaee; color: #4a4232; border: 1px solid #e3d5ae; border-radius: 0;  /* opaque: a translucent border shows the black window behind it */
  padding: 6px 9px; font-size: 12px; }
QLabel#sourceSummary { color: #5f5440; font-size: 12px; line-height: 140%; }
QLabel#promptSpec { color: rgba(255, 255, 255, 125); font-size: 11px; background: #3f3f3f; padding: 6px 0 0 0; }
QLabel#rowLabel { color: #8a7d5c; font-size: 10px; font-weight: 500; letter-spacing: 1px; padding-top: 2px; min-width: 84px; }
/* Variant tabs look like the Target model switch: one track, the chosen one in our yellow. */
/* Tabs and prompt are one grey card: the tab row is the card's header, the chosen tab is a yellow pill. */
QTabWidget#variantTabs { background: #3f3f3f; border-radius: 12px; }
QTabWidget#variantTabs::pane { top: 0; border: none; background: transparent; }
QTabWidget#variantTabs::tab-bar { left: 10px; }
QTabWidget#variantTabs QTabBar { background: transparent; }
QTabWidget#variantTabs QTabBar::tab { background: transparent; border: none; border-radius: 7px; margin: 10px 4px 2px 0;
  padding: 5px 16px; color: rgba(255, 255, 255, 150); font-size: 12px; min-width: 56px; }
QTabWidget#variantTabs QTabBar::tab:hover { background: rgba(255, 255, 255, 22); color: #f5f5f5; }
QTabWidget#variantTabs QTabBar::tab:selected { background: #f4ca38; color: #2f260c; font-weight: 600; }
QTabWidget#variantTabs QPlainTextEdit#prompt { border-top-left-radius: 0; border-top-right-radius: 0; }
"""


def main() -> int:
    qt_log.install()  # глушит только известный шум моста доступности macOS; PROMPTA_QT_DEBUG=1 — всё
    app = QApplication(sys.argv)
    app.setApplicationName("Prompta")
    app.setWindowIcon(QIcon(str(ROOT / "desktop" / "icon.png")))
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#f4ca38"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#352b10"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#80620a"))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor("#80620a"))
    app.setPalette(palette)
    app.setStyleSheet(QSS)
    app.hint_filter = HintFilter(app)  # our own hover hints instead of the black-framed system ones
    app.installEventFilter(app.hint_filter)
    window = PromptaWindow()
    window.show()

    if "--screenshot" in sys.argv:
        # Самопроверка вёрстки: рендерим демо-результат и сохраняем окно в PNG.
        index = sys.argv.index("--screenshot")
        path = sys.argv[index + 1] if len(sys.argv) > index + 1 else "/tmp/app.png"
        window.thoughts.setPlainText(
            "I want AI to review my meeting notes "
            "and extract decisions, tasks, and owners into a table"
        )
        window._on_models_loaded(fetch_ollama_models())
        # техники тоже нужны в скриншоте: тянем синхронно через мост
        try:
            proc = subprocess.run(
                [node_binary(), str(BRIDGE)],
                input=json.dumps({"thoughts": "x", "listTechniques": True, "model": "dummy"}),
                capture_output=True, text=True, timeout=120, cwd=str(ROOT),
            )
            window._on_techniques_loaded(json.loads(proc.stdout or "{}").get("techniques", []))
        except Exception:
            pass
        window.render(
            {
                "brief": {
                    "goal": "Extract decisions, tasks, and owners from meeting notes into a table",
                    "task_type": "extraction",
                    "language": "en",
                    "stakes": "high",
                    "output_format": "Markdown table: Type | Item | Owner",
                    "assumptions": ["Notes are provided as text rather than audio"],
                    "questions": [{"question": "Which meeting types are in scope?", "default": "all internal meetings"},
                                  {"question": "Should owners be names or roles?", "default": "names as written in the notes"}],
                },
                "choice": {
                    "name": "Contextual prompting",
                    "key": "contextual_prompting",
                    "confidence": 0.82,
                    "reason": "The task is grounded in supplied notes and limited to their contents.",
                    "whyNotCheaper": "Zero-shot may miss the table format; few-shot needs examples not supplied in the brief.",
                },
                "synthesis": {
                    "prompt": "Use ONLY the material below. Cite [n] for every claim.\n\n[1] meeting notes\n\nTask: extract items from the notes into a table\nOutput: Markdown table",
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
                            "prompt": "Task: extract items from the notes into a table.\n\nExample 1:\nInput: Prepare the report by Friday\nOutput: | Prepare report | Owner | Friday |\n\nInput: INSERT HERE: meeting notes\nOutput:",
                            "config": {"temperature": 0.2, "top_p": 0.95, "max_tokens": "1024"},
                            "warnings": [],
                            "rationale": "Low temperature keeps output formats consistent.",
                        },
                    }
                ],
                "rejected": [{}] * 53,
            }
        )
        window.status.setText("Contextual prompting · warnings: 1")
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
            print(f"попапы: {base}-*.png")
        print(f"скриншот: {path}")
        return 0

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
