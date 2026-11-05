#!/usr/bin/env python3
"""Prompta — нативное приложение для macOS.

UI на PyQt6, логика — существующий TS-пайплайн через мост desktop/bridge.ts.
История хранится локально; ключи API на диск не записываются.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
import subprocess
import sys
import urllib.request
from pathlib import Path

try:
    from .history import HistoryStore
except ImportError:
    from history import HistoryStore

from PyQt6.QtCore import QPoint, QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QGuiApplication, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

ROOT = Path(__file__).resolve().parent.parent
BRIDGE = ROOT / "desktop" / "bridge.ts"

OLLAMA_TAGS = "http://localhost:11434/api/tags"
FALLBACK_MODELS = [
    "minimax-m3.1-flash:cloud",
    "glm-5.3:cloud",
    "deepseek-v4-pro:cloud",
    "qwen3:30b",
]


def fetch_ollama_models(timeout: float = 3.0) -> list[str]:
    """Полный список моделей из локального демона Ollama. Пусто — демон не запущен."""
    try:
        with urllib.request.urlopen(OLLAMA_TAGS, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    names = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    return sorted(set(names), key=str.lower)

QSS = """
QWidget { font-family: 'Helvetica Neue'; font-size: 13px; color: #334155; }
QMainWindow, QWidget#root { background: #f2f5f9; }
QDialog { background: #ffffff; }
QPushButton#settings { background: transparent; border: 1px solid transparent; border-radius: 9px; }
QPushButton#settings:hover { background: #e7edf5; border-color: #dfe6ef; }
QPushButton#settings:pressed { background: #dce6f2; }
QPushButton#settings:focus { border-color: #438fe1; }
QFrame#card { background: #ffffff; border: 1px solid #dfe6ef; border-radius: 14px; }
QLabel#title { font-size: 28px; letter-spacing: -0.8px; font-weight: 600; color: #1f2d3d; }
QLabel#subtitle { color: #64748b; font-size: 13px; }
QLabel#section { font-weight: 600; color: #1e293b; font-size: 14px; }
QLabel#fieldLabel { color: #52657b; font-size: 11px; font-weight: 600; letter-spacing: 0.7px; }
QLabel#muted { color: #64748b; font-size: 12px; }
QLabel#goal { font-size: 16px; font-weight: 600; color: #1f2d3d; }
QLabel#chip { color: #41576d; background: #f0f6fc; border: 1px solid #e2edf7; border-radius: 9px; padding: 2px 8px; font-size: 12px; }
QLabel#warn { color: #8a5300; background: #fffaf0; border: 1px solid #f6e2bd; border-radius: 8px; padding: 8px 10px; font-size: 12px; }
QLabel#error { color: #b03a2e; background: #fff5f5; border: 1px solid #f5c2c2; border-radius: 8px; padding: 8px 10px; }
QLabel#status { color: #52657b; font-size: 12px; }
QPlainTextEdit { font-size: 13px; background: #ffffff; border: 1px solid #d6e0ea; border-radius: 8px; padding: 8px; selection-background-color: #cfe6ff; }
QPlainTextEdit:focus { border-color: #007bff; }
QPlainTextEdit#prompt { padding: 10px; background: #0f172a; color: #e6edf7; border: 1px solid #1b2437; font-family: Menlo, monospace; font-size: 12px; }
QLineEdit, QComboBox { font-size: 13px; background: #ffffff; border: 1px solid #d6e0ea; border-radius: 8px; padding: 7px 9px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
  font-size: 13px; background: #ffffff; color: #334155; border: 1px solid #d6e0ea; outline: none;
  selection-background-color: #e3f0ff; selection-color: #0b62c6;
}
QPushButton#picker {
  font-size: 13px; background: #ffffff; color: #334155; border: 1px solid #d6e0ea; border-radius: 8px;
  padding: 8px 10px; text-align: left;
}
QPushButton#picker:hover { border-color: #007bff; }
QFrame#techniquePopup { background: #ffffff; border: 1px solid #d6e0ea; border-radius: 12px; }
QFrame#techItem { background: #fbfdff; border: 1px solid #e6eef6; border-radius: 8px; }
QFrame#techItem:hover { background: #eef6ff; border-color: #a9cdf5; }
QLabel#techName { font-weight: 600; color: #1e293b; font-size: 13px; }
QLabel#techHint { color: #6b7a8c; font-size: 12px; }
QLabel#catHeader { color: #64748b; font-size: 11px; font-weight: 600; letter-spacing: 0.7px; }
QLineEdit:focus, QComboBox:focus { border-color: #007bff; }
QPushButton#primary { background: #007bff; color: #ffffff; border: none; border-radius: 8px; padding: 10px 18px; font-weight: 600; }
QPushButton#primary:hover { background: #0067d6; }
QPushButton#primary:pressed { background: #005abd; }
QPushButton:focus { border: 1px solid #438fe1; }
QPushButton#primary:disabled { background: #a9c7e8; }
QPushButton#ghost { background: #eef6ff; color: #0b62c6; border: 1px solid #cfe3f7; border-radius: 6px; padding: 5px 10px; font-size: 12px; }
QPushButton#ghost:hover { background: #dcecff; }
QPushButton#ghost:pressed { background: #cfe2fa; }
QPushButton#ghost:disabled { color: #8494a6; background: #f5f7fa; border-color: #e6ebf2; }
QProgressBar { background: #e4eef7; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; }
QProgressBar::chunk { background: #007bff; border-radius: 2px; }
QScrollArea { border: none; background: #ffffff; }
QWidget#scrollContent { background: #ffffff; }
QCheckBox { color: #5b6b7c; font-size: 12px; spacing: 8px; }
QSplitter::handle:horizontal { width: 12px; background: transparent; }
QSplitter::handle:horizontal:hover { background: #e2eaf3; border-radius: 4px; }
/* Keep the scrollbar hit area usable while the visible handle stays slim. */
QScrollBar:vertical { border: none; background: #f5f7fa; width: 12px; margin: 3px 2px; border-radius: 4px; }
QScrollBar:horizontal { border: none; background: #f5f7fa; height: 12px; margin: 2px 3px; border-radius: 4px; }
QScrollBar::handle:vertical { border: none; background: #bbc7d5; min-height: 32px; border-radius: 4px; }
QScrollBar::handle:horizontal { border: none; background: #bbc7d5; min-width: 32px; border-radius: 4px; }
QScrollBar::handle:hover { background: #95a6ba; }
QScrollBar::handle:pressed { background: #71869f; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; border: none; background: transparent; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QAbstractScrollArea::corner { background: transparent; }
"""


DARK_SCROLL_QSS = """
QScrollBar:vertical, QScrollBar:horizontal { background: #162238; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #52647e; }
QScrollBar::handle:hover { background: #7185a2; }
QScrollBar::handle:pressed { background: #91a5c0; }
"""


def node_binary() -> str:
    for candidate in (shutil.which("node"), "/opt/homebrew/bin/node", "/usr/local/bin/node"):
        if candidate and Path(candidate).exists():
            return candidate
    return "node"


class TechniquesLoader(QThread):
    loaded = pyqtSignal(list)

    def run(self) -> None:
        try:
            proc = subprocess.run(
                [node_binary(), str(BRIDGE)],
                input=json.dumps({"thoughts": "x", "listTechniques": True, "model": "dummy"}),
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(ROOT),
            )
            data = json.loads(proc.stdout or "{}")
            self.loaded.emit(data.get("techniques", []))
        except Exception:
            self.loaded.emit([])


class ModelsLoader(QThread):
    loaded = pyqtSignal(list)

    def run(self) -> None:
        self.loaded.emit(fetch_ollama_models())


class Worker(QThread):
    finished_ok = pyqtSignal(dict)

    def __init__(self, payload: dict) -> None:
        super().__init__()
        self.payload = payload
        self.proc: subprocess.Popen | None = None
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def run(self) -> None:
        try:
            if self.cancelled:
                self.finished_ok.emit({"ok": False, "error": "Cancelled"})
                return
            self.proc = subprocess.Popen(
                [node_binary(), str(BRIDGE)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(ROOT),
            )
            if self.cancelled:
                self.proc.terminate()
            out, err = self.proc.communicate(json.dumps(self.payload), timeout=900)
            if self.cancelled:
                self.finished_ok.emit({"ok": False, "error": "Cancelled"})
                return
            out = (out or "").strip()
            if not out:
                raise RuntimeError((err or "Empty response from the pipeline")[-400:])
            self.finished_ok.emit(json.loads(out))
        except Exception as exc:  # noqa: BLE001
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
                self.proc.communicate()
            message = "Cancelled" if self.cancelled else str(exc)
            self.finished_ok.emit({"ok": False, "error": message})


CATEGORY_LABELS = {
    "context": "Context and framing",
    "reasoning": "Reasoning",
    "thought_generation": "Thought generation",
    "decomposition": "Decomposition",
    "icl": "Examples (ICL)",
    "zero_shot_boost": "Zero-shot enhancement",
    "ensembling": "Ensembles",
    "self_critique": "Self-critique",
    "optimization": "Prompt optimization",
    "answer_engineering": "Answer extraction",
    "agents": "Agents",
    "rag": "RAG",
    "automation": "Automation and code",
    "pedagogy": "Teaching",
    "procedure": "Procedures",
    "security": "Security",
    "generation_config": "Settings",
}


class TechniqueItem(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, key: str, name: str, hint: str = "") -> None:
        super().__init__()
        self.key = key
        self.setObjectName("techItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(2)

        title = QLabel(name)
        title.setObjectName("techName")
        title.setWordWrap(True)
        layout.addWidget(title)

        if hint:
            note = QLabel(hint)
            note.setObjectName("techHint")
            note.setWordWrap(True)
            layout.addWidget(note)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.key)


class Dropdown(QPushButton):
    """Единый выпадающий список: одна панель на провайдера, модель, варианты и техники.

    Умеет: одну или две колонки, заголовки категорий, подсказки, поиск по списку.
    """

    changed = pyqtSignal(str)

    def __init__(
        self,
        placeholder: str = "—",
        columns: int = 1,
        searchable: bool = False,
        popup_width: int = 380,
    ) -> None:
        super().__init__(placeholder)
        self.setObjectName("picker")
        self._placeholder = placeholder
        self._items: list[dict] = []
        self._current = ""
        self._columns = columns
        self._searchable = searchable
        self._popup_width = popup_width
        self._popup: QFrame | None = None
        self.clicked.connect(self._open)

    # ── данные ───────────────────────────────────────────────────
    def set_items(self, items: list[dict], keep: str = "") -> None:
        self._items = items
        want = keep or self._current
        if want and any(item.get("key") == want for item in items):
            self.set_current(want)

    def current_key(self) -> str:
        return self._current

    def set_current(self, key: str, emit: bool = False) -> None:
        self._current = key
        item = next((i for i in self._items if i.get("key") == key), None)
        self.setText(item.get("label") or item.get("name") or key if item else (key or self._placeholder))
        if emit:
            self.changed.emit(key)

    # ── панель ───────────────────────────────────────────────────
    def _open(self) -> None:
        popup = QFrame(self, Qt.WindowType.Popup)
        popup.setObjectName("techniquePopup")
        self._popup = popup

        outer = QVBoxLayout(popup)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        search: QLineEdit | None = None
        if self._searchable:
            search = QLineEdit()
            search.setPlaceholderText("Filter by name…")
            outer.addWidget(search)

        scroll = QScrollArea(popup)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: #ffffff; border: none; }")

        content = QWidget()
        content.setObjectName("scrollContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)

        entries: list[tuple[TechniqueItem, str]] = []
        headers: list[tuple[QLabel, list[TechniqueItem]]] = []

        grouped: dict[str, list[dict]] = {}
        for item in self._items:
            grouped.setdefault(item.get("category") or "", []).append(item)

        multi_group = any(key for key in grouped)

        for category, items in grouped.items():
            if multi_group:
                header = QLabel(CATEGORY_LABELS.get(category, category).upper() if category else "GENERAL")
                header.setObjectName("catHeader")
                body.addWidget(header)

            grid = QGridLayout()
            grid.setSpacing(6)
            grid_items: list[TechniqueItem] = []
            for index, item in enumerate(items):
                label = item.get("label") or item.get("name") or item["key"]
                widget = TechniqueItem(item["key"], label, item.get("hint", ""))
                widget.clicked.connect(lambda key: self._choose(key))
                grid.addWidget(widget, index // self._columns, index % self._columns)
                entries.append((widget, f"{label} {item.get('hint','')} {category}".lower()))
                grid_items.append(widget)
            for column in range(self._columns):
                grid.setColumnStretch(column, 1)
            body.addLayout(grid)
            if multi_group:
                headers.append((header, grid_items))

        body.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        def apply_filter(text: str) -> None:
            needle = text.strip().lower()
            for widget, haystack in entries:
                widget.setVisible(needle in haystack)
            for header, grid_items in headers:
                header.setVisible(any(w.isVisible() for w in grid_items))

        if search is not None:
            search.textChanged.connect(apply_filter)

        # Высота по содержимому: пустая панель на весь экран выглядит неаккуратно.
        rows = sum(
            (len(items) + self._columns - 1) // self._columns for items in grouped.values()
        )
        height = 44 + rows * 50 + (len(grouped) * 24 if multi_group else 0)
        if self._searchable:
            height += 46
        popup.resize(self._popup_width, min(560, max(120, height)))
        popup.move(self.mapToGlobal(QPoint(0, self.height() + 4)))
        popup.show()
        if search is not None:
            search.setFocus()

    def _choose(self, key: str) -> None:
        self.set_current(key, emit=True)
        if self._popup is not None:
            self._popup.close()


class Card(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")

    def vbox(self) -> QVBoxLayout:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(10)
        return layout


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Prompta")
        self.resize(1160, 780)
        self.worker: Worker | None = None
        self.history_store = HistoryStore()
        self._history_items: list[dict] = []
        self._active_thoughts = ""

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 22, 24, 18)
        outer.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(20)
        title = QLabel("Prompta")
        title.setObjectName("title")
        subtitle = QLabel("Thoughts → brief → technique → ready-to-use prompt")
        subtitle.setObjectName("subtitle")
        header.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        self.settings_button = QPushButton()
        self.settings_button.setObjectName("settings")
        self.settings_button.setIcon(QIcon(str(ROOT / "desktop" / "settings.svg")))
        self.settings_button.setIconSize(QSize(20, 20))
        self.settings_button.setFixedSize(36, 36)
        self.settings_button.setToolTip("Settings")
        self.settings_button.setAccessibleName("Settings")
        self.settings_button.clicked.connect(self.open_settings)
        header.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_input())
        splitter.addWidget(self._build_output())
        splitter.setSizes([440, 700])
        outer.addWidget(splitter, 1)

        self.status = QLabel("Ready")
        self.status.setObjectName("status")
        outer.addWidget(self.status)
        self._load_history()

        self.provider.changed.connect(self._on_provider_changed)
        self.load_models()
        self.load_techniques()

        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut.activated.connect(self.run_pipeline)
        shortcut2 = QShortcut(QKeySequence("Meta+Return"), self)
        shortcut2.activated.connect(self.run_pipeline)

    # ── левая колонка ─────────────────────────────────────────────
    def _build_input(self) -> QWidget:
        card = Card()
        box = card.vbox()

        box.addWidget(self._mini_label("Thoughts"))

        hint = QLabel("Write freely. The pipeline will turn your thoughts into a brief.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        box.addWidget(hint)

        self.thoughts = QPlainTextEdit()
        self.thoughts.setPlaceholderText(
            "I want AI to review my meeting notes "
            "and extract decisions, tasks, and owners into a table"
        )
        self.thoughts.setMinimumHeight(150)
        box.addWidget(self.thoughts, 1)

        box.addWidget(self._mini_label("Technique"))
        self.technique = Dropdown("Auto — let the pipeline choose", columns=2, searchable=True, popup_width=820)
        box.addWidget(self.technique)
        self.technique_hint = QLabel("Choose a technique to build a prompt using its method")
        self.technique_hint.setObjectName("muted")
        self.technique_hint.setWordWrap(True)
        box.addWidget(self.technique_hint)

        row = QHBoxLayout()
        row.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(self._mini_label("Provider"))
        self.provider = Dropdown("Ollama", popup_width=300)
        self.provider.set_items(
            [
                {"key": "ollama", "label": "Ollama (local/cloud)"},
                {"key": "gemini", "label": "Gemini"},
                {"key": "openai", "label": "OpenAI"},
            ]
        )
        self.provider.set_current("ollama")
        left.addWidget(self.provider)
        row.addLayout(left, 1)

        mid = QVBoxLayout()
        mid.setSpacing(4)
        mid.addWidget(self._mini_label("Model"))
        model_row = QHBoxLayout()
        model_row.setSpacing(6)
        self.model = Dropdown("Choose a model", searchable=True, popup_width=460)
        self.model.set_items([{"key": name, "label": name} for name in FALLBACK_MODELS])
        self.model.set_current("minimax-m3.1-flash:cloud")
        model_row.addWidget(self.model, 1)
        self.refresh_button = QPushButton("↻")
        self.refresh_button.setObjectName("ghost")
        self.refresh_button.setFixedWidth(34)
        self.refresh_button.setToolTip("Refresh models from Ollama")
        self.refresh_button.clicked.connect(self.load_models)
        model_row.addWidget(self.refresh_button)
        mid.addLayout(model_row)
        self.models_hint = QLabel("Loading Ollama models…")
        self.models_hint.setObjectName("muted")
        self.models_hint.setWordWrap(True)
        row.addLayout(mid, 1)

        box.addLayout(row)
        box.addWidget(self.models_hint)

        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle("Settings")
        self.settings_dialog.setModal(True)
        self.settings_dialog.setMinimumWidth(420)
        settings_layout = QVBoxLayout(self.settings_dialog)
        settings_layout.setContentsMargins(24, 24, 24, 24)
        settings_layout.setSpacing(14)
        settings_title = QLabel("Settings")
        settings_title.setObjectName("goal")
        settings_layout.addWidget(settings_title)
        settings_layout.addWidget(self._mini_label("API key"))
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Enter your API key")
        self.api_key.setAccessibleName("API key")
        settings_layout.addWidget(self.api_key)
        key_hint = QLabel("Required for OpenAI and Gemini. Not needed for Ollama.\nYour key stays in memory and is not saved to disk.")
        key_hint.setObjectName("muted")
        key_hint.setWordWrap(True)
        settings_layout.addWidget(key_hint)
        settings_actions = QHBoxLayout()
        settings_actions.addStretch(1)
        done_button = QPushButton("Done")
        done_button.setObjectName("primary")
        done_button.clicked.connect(self.settings_dialog.accept)
        settings_actions.addWidget(done_button)
        settings_layout.addLayout(settings_actions)

        self.deterministic = QCheckBox("Skip LLM synthesis")
        self.deterministic.setToolTip("The brief and technique selection still use the model.")
        box.addWidget(self.deterministic)

        variants_row = QHBoxLayout()
        variants_row.setSpacing(8)
        variants_label = QLabel("Prompt variants:")
        variants_label.setObjectName("muted")
        variants_row.addWidget(variants_label)
        self.variants = Dropdown("3", popup_width=160)
        self.variants.set_items([
            {"key": "3", "label": "3 variants"},
            {"key": "2", "label": "2 variants"},
            {"key": "1", "label": "1 variant"},
        ])
        self.variants.set_current("3")
        variants_row.addWidget(self.variants)
        variants_row.addStretch(1)
        box.addLayout(variants_row)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.run_button = QPushButton("Build prompt")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.run_pipeline)
        actions.addWidget(self.run_button, 1)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("ghost")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_run)
        actions.addWidget(self.cancel_button)
        box.addLayout(actions)

        return card

    def open_settings(self) -> None:
        self.settings_dialog.open()
        self.api_key.setFocus()

    def _mini_label(self, text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setObjectName("fieldLabel")
        return label

    def load_techniques(self) -> None:
        self.techniques_loader = TechniquesLoader()
        self.techniques_loader.loaded.connect(self._on_techniques_loaded)
        self.techniques_loader.start()

    def _on_techniques_loaded(self, techniques: list) -> None:
        if not techniques:
            return
        for item in techniques:
            if item.get("status") == "procedure":
                item["name"] = f"{item.get('name', item['key'])} (procedure)"
            item["label"] = item.get("name", item["key"])
        self.technique.set_items(techniques, keep=self.technique.current_key())
        self.technique_hint.setText(f"Choose a technique ({len(techniques)} available)")

    def load_models(self) -> None:
        self.models_hint.setText("Fetching Ollama models…")
        self.refresh_button.setEnabled(False)
        self.models_loader = ModelsLoader()
        self.models_loader.loaded.connect(self._on_models_loaded)
        self.models_loader.start()

    def _on_models_loaded(self, names: list) -> None:
        self.refresh_button.setEnabled(True)
        if not names:
            self.models_hint.setText(
                "Ollama is unavailable at localhost:11434. Using the previous model list."
            )
            return

        current = self.model.current_key().strip()
        self.model.set_items([{"key": name, "label": name} for name in names], keep=current)
        if not self.model.current_key():
            self.model.set_current(names[0])
        self.models_hint.setText(f"{len(names)} models loaded")

    def _on_provider_changed(self, provider: str) -> None:
        if provider == "ollama":
            self.load_models()
        else:
            self.models_hint.setText("Enter the model name for your cloud provider")

    # ── правая колонка ────────────────────────────────────────────
    def _build_output(self) -> QWidget:
        card = Card()
        box = card.vbox()

        history_row = QHBoxLayout()
        history_row.setSpacing(8)
        history_label = QLabel("HISTORY")
        history_label.setObjectName("muted")
        history_row.addWidget(history_label)
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Search requests and prompts…")
        self.history_search.setClearButtonEnabled(True)
        self.history_search.textChanged.connect(self._filter_history)
        history_row.addWidget(self.history_search, 1)
        self.history = QComboBox()
        self.history.addItem("— no history yet —", -1)
        self.history.currentIndexChanged.connect(self._on_history_selected)
        history_row.addWidget(self.history, 1)
        box.addLayout(history_row)
        self.history_notice = QLabel()
        self.history_notice.setObjectName("error")
        self.history_notice.setWordWrap(True)
        self.history_notice.hide()
        box.addWidget(self.history_notice)

        self.output_scroll = QScrollArea()
        self.output_scroll.setWidgetResizable(True)
        self.output_holder = QWidget()
        self.output_holder.setObjectName("scrollContent")
        self.output_layout = QVBoxLayout(self.output_holder)
        self.output_layout.setContentsMargins(0, 0, 0, 0)
        self.output_layout.setSpacing(10)
        # Скролл должен расти под содержимое, иначе виджеты наезжают друг на друга.
        self.output_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.output_scroll.setWidget(self.output_holder)
        box.addWidget(self.output_scroll, 1)

        self._show_placeholder()
        return card

    def _load_history(self) -> None:
        try:
            self._history_items = self.history_store.load()
        except (OSError, ValueError, sqlite3.Error):
            self.history_notice.setText("Could not load history. The existing file has been preserved.")
            self.history_notice.show()
        self._filter_history()

    def _filter_history(self, text: str = "", selected: int | None = None) -> None:
        needle = text.strip().casefold()
        current = self.history.currentData() if selected is None else selected
        self.history.blockSignals(True)
        self.history.clear()
        self.history.addItem("— choose a request —" if self._history_items else "— no history yet —", -1)
        for index, entry in enumerate(self._history_items):
            searchable = entry['thoughts'] + ' ' + entry['label'] + ' ' + json.dumps(entry['payload'], ensure_ascii=False)
            if needle and needle not in searchable.casefold():
                continue
            date = entry['created_at'][:16].replace('T', ' ')
            query = ' '.join(entry['thoughts'].split())
            label = f"{date} · {query[:80] or entry['label']} · {entry['label']}"
            self.history.addItem(label, index)
            self.history.setItemData(self.history.count() - 1, entry['thoughts'], Qt.ItemDataRole.ToolTipRole)
        if self.history.count() == 1 and needle:
            self.history.setItemText(0, "— no matches —")
        target = self.history.findData(current)
        self.history.setCurrentIndex(max(0, target))
        self.history.blockSignals(False)

    def _push_history(self, label: str, kind: str, payload: dict) -> None:
        thoughts = self._active_thoughts or self.thoughts.toPlainText().strip()
        try:
            entry = self.history_store.add(label, kind, thoughts, payload)
        except (OSError, ValueError, sqlite3.Error):
            self.history_notice.setText("Could not save history to disk. This result is still available in this window.")
            self.history_notice.show()
            entry = {'label': label, 'kind': kind, 'thoughts': thoughts,
                     'payload': payload, 'created_at': datetime.now().isoformat()}
        self._history_items.append(entry)
        self.history_search.clear()
        self._filter_history(selected=len(self._history_items) - 1)

    def _on_history_selected(self, index: int) -> None:
        item_index = self.history.itemData(index)
        if not isinstance(item_index, int) or not 0 <= item_index < len(self._history_items):
            return
        entry = self._history_items[item_index]
        kind, payload = entry['kind'], entry['payload']
        try:
            if kind == "manual":
                self.render_manual(payload)
            elif kind == "procedure":
                self.render_procedure(payload)
            else:
                self.render(payload)
        except (KeyError, TypeError, ValueError):
            self.history_notice.setText("Could not open this history entry: invalid data.")
            self.history_notice.show()
            return
        self.thoughts.setPlainText(entry['thoughts'])

    def _clear_output(self) -> None:
        while self.output_layout.count():
            item = self.output_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _show_placeholder(self) -> None:
        self._clear_output()
        label = QLabel(
            "Your brief, selected technique, prompt, and settings will appear here."
        )
        label.setObjectName("muted")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.output_layout.addStretch(1)
        self.output_layout.addWidget(label)
        self.output_layout.addStretch(1)

    # ── запуск ────────────────────────────────────────────────────
    def cancel_run(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.status.setText("Cancelling…")

    def run_pipeline(self) -> None:
        if self.worker and self.worker.isRunning():
            return

        thoughts = self.thoughts.toPlainText().strip()
        if not thoughts:
            self.status.setText("Enter your thoughts")
            return

        provider = self.provider.current_key()
        model = self.model.current_key().strip()
        api_key = self.api_key.text().strip()

        if not model:
            self.status.setText("Choose a model")
            return
        if provider != "ollama" and not api_key:
            self.status.setText("Add an API key in Settings")
            return

        technique_key = self.technique.current_key() or ""
        payload = {
            "thoughts": thoughts,
            "provider": provider,
            "model": model,
            "apiKey": api_key,
            "deterministic": self.deterministic.isChecked(),
            "variants": int(self.variants.current_key() or "3"),
        }
        if technique_key:
            payload["manualTechnique"] = technique_key

        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText("Brief → technique selection → synthesis…")

        self._active_thoughts = thoughts
        self.worker = Worker(payload)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.start()

    def on_finished(self, data: dict) -> None:
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if not data.get("ok"):
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
            self.render_manual(data["manual"])
            self._push_history(data["manual"]["technique"]["name"], "manual", data["manual"])
            self.status.setText(f"{data['manual']['technique']['name']} · built using this method")
            return

        self.render(data["result"])
        self._push_history(data["result"]["choice"]["name"], "pipeline", data["result"])
        choice = data["result"]["choice"]
        warnings = len(data["result"]["synthesis"]["warnings"])
        self.status.setText(f"{choice['name']} · warnings: {warnings}")

    def render_procedure(self, procedure: dict) -> None:
        self._clear_output()

        technique = procedure["technique"]
        title = QLabel(technique["name"])
        title.setObjectName("goal")
        title.setWordWrap(True)
        self.output_layout.addWidget(title)

        meta = QLabel(f"{technique['key']} · {technique['category']} · source: {procedure['source_ref']}")
        meta.setObjectName("muted")
        meta.setWordWrap(True)
        self.output_layout.addWidget(meta)

        explain = QLabel(
            "This is a procedure for data or models. Follow the steps in code or manually."
        )
        explain.setObjectName("warn")
        explain.setWordWrap(True)
        self.output_layout.addWidget(explain)

        steps = QLabel("\n".join(f"{i}. {step}" for i, step in enumerate(procedure["steps"], 1)))
        steps.setWordWrap(True)
        steps.setStyleSheet(
            "background: #ffffff; border: 1px solid #e6eef6; border-radius: 8px; padding: 12px;"
        )
        self.output_layout.addWidget(steps)

        when = QLabel(f"When to use: {procedure['when_to_use']}")
        when.setObjectName("muted")
        when.setWordWrap(True)
        self.output_layout.addWidget(when)

        self.output_layout.addStretch(1)

    def render_manual(self, manual: dict) -> None:
        self._clear_output()

        technique = manual["technique"]
        title = QLabel(technique["name"])
        title.setObjectName("goal")
        title.setWordWrap(True)
        self.output_layout.addWidget(title)

        meta = QLabel(f"{technique['key']} · {technique['category']} · source: {manual['source_ref']}")
        meta.setObjectName("muted")
        meta.setWordWrap(True)
        self.output_layout.addWidget(meta)

        prompt_head = QHBoxLayout()
        label = QLabel("PROMPT")
        label.setObjectName("muted")
        prompt_head.addWidget(label)
        prompt_head.addStretch(1)
        copy_button = QPushButton("Copy")
        copy_button.setObjectName("ghost")
        prompt_head.addWidget(copy_button)
        self.output_layout.addLayout(prompt_head)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setObjectName("prompt")
        for scrollbar in (self.prompt_edit.verticalScrollBar(), self.prompt_edit.horizontalScrollBar()):
            scrollbar.setStyleSheet(DARK_SCROLL_QSS)
        self.prompt_edit.setPlainText(manual["prompt"])
        self.prompt_edit.setReadOnly(True)
        self.prompt_edit.setFixedHeight(320)
        copy_button.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.prompt_edit.toPlainText())
        )
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
    def render(self, result: dict) -> None:
        self._clear_output()
        brief = result["brief"]
        choice = result["choice"]
        synthesis = result["synthesis"]
        config = synthesis["config"]

        goal = QLabel(brief["goal"])
        goal.setObjectName("goal")
        goal.setWordWrap(True)
        self.output_layout.addWidget(goal)

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

        tech = QFrame()
        tech.setObjectName("tech")
        tech.setStyleSheet(
            "QFrame#tech { background: #f7fbff; border: 1px solid #e2edf7; border-radius: 10px; }"
        )
        tech_box = QVBoxLayout(tech)
        tech_box.setContentsMargins(12, 10, 12, 12)
        tech_box.setSpacing(6)

        head = QHBoxLayout()
        name = QLabel(choice["name"])
        name.setObjectName("section")
        key = QLabel(choice["key"])
        key.setObjectName("muted")
        confidence = QLabel(f"confidence {round(choice['confidence'] * 100)}%")
        confidence.setObjectName("muted")
        head.addWidget(name)
        head.addWidget(key)
        head.addStretch(1)
        head.addWidget(confidence)
        tech_box.addLayout(head)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(round(choice["confidence"] * 100))
        bar.setTextVisible(False)
        tech_box.addWidget(bar)

        why = QLabel(f"Why: {choice['reason']}")
        why.setWordWrap(True)
        why.setObjectName("muted")
        tech_box.addWidget(why)

        why_not = QLabel(f"Why not a cheaper method: {choice['whyNotCheaper']}")
        why_not.setWordWrap(True)
        why_not.setObjectName("muted")
        tech_box.addWidget(why_not)

        self.output_layout.addWidget(tech)

        prompt_head = QHBoxLayout()
        prompt_label = QLabel("PROMPT")
        prompt_label.setObjectName("muted")
        prompt_head.addWidget(prompt_label)
        prompt_head.addStretch(1)
        copy_button = QPushButton("Copy")
        copy_button.setObjectName("ghost")
        copy_button.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.prompt_edit.toPlainText())
        )
        prompt_head.addWidget(copy_button)
        self.output_layout.addLayout(prompt_head)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setObjectName("prompt")
        for scrollbar in (self.prompt_edit.verticalScrollBar(), self.prompt_edit.horizontalScrollBar()):
            scrollbar.setStyleSheet(DARK_SCROLL_QSS)
        self.prompt_edit.setPlainText(synthesis["prompt"])
        self.prompt_edit.setReadOnly(True)
        self.prompt_edit.setFixedHeight(220)
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

            head = QLabel(f"Variant {index}: {alt_choice['name']} ({alt_choice['key']})")
            head.setObjectName("section")
            head.setWordWrap(True)
            head.setStyleSheet("margin-top: 10px; border-top: 1px dashed #e6eef6; padding-top: 10px;")
            self.output_layout.addWidget(head)

            why = QLabel(alt_choice["reason"])
            why.setObjectName("muted")
            why.setWordWrap(True)
            self.output_layout.addWidget(why)

            box = QPlainTextEdit()
            box.setObjectName("prompt")
            for scrollbar in (box.verticalScrollBar(), box.horizontalScrollBar()):
                scrollbar.setStyleSheet(DARK_SCROLL_QSS)
            box.setPlainText(alt_synth["prompt"])
            box.setReadOnly(True)
            box.setFixedHeight(150)
            alt_prompt_head = QHBoxLayout()
            alt_prompt_label = QLabel("PROMPT")
            alt_prompt_label.setObjectName("muted")
            alt_prompt_head.addWidget(alt_prompt_label)
            alt_prompt_head.addStretch(1)
            alt_copy_button = QPushButton("Copy")
            alt_copy_button.setObjectName("ghost")
            alt_copy_button.clicked.connect(
                lambda checked=False, editor=box: QGuiApplication.clipboard().setText(editor.toPlainText())
            )
            alt_prompt_head.addWidget(alt_copy_button)
            self.output_layout.addLayout(alt_prompt_head)
            self.output_layout.addWidget(box)

            cfg = alt_synth["config"]
            meta = QLabel(f"temperature {cfg['temperature']} · {cfg['max_tokens']}")
            meta.setObjectName("muted")
            self.output_layout.addWidget(meta)

        footer = QLabel(f"Techniques filtered out: {len(result['rejected'])}")
        footer.setObjectName("muted")
        self.output_layout.addWidget(footer)

        self.output_layout.addStretch(1)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Prompta")
    app.setWindowIcon(QIcon(str(ROOT / "desktop" / "icon.png")))
    app.setStyleSheet(QSS)
    window = MainWindow()
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
        app.processEvents()
        app.processEvents()
        window.grab().save(path)

        if "--screenshot-popup" in sys.argv:
            popup_index = sys.argv.index("--screenshot-popup")
            popup_path = sys.argv[popup_index + 1] if len(sys.argv) > popup_index + 1 else "/tmp/popup.png"
            base = popup_path.rsplit(".", 1)[0]
            for name, widget in (
                ("provider", window.provider),
                ("model", window.model),
                ("variants", window.variants),
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
