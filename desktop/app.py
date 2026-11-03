#!/usr/bin/env python3
"""Prompt Pipeline — нативное приложение для macOS.

UI на PyQt6, логика — существующий TS-пайплайн через мост desktop/bridge.ts.
Ключ и модель задаются в окне; ничего не пишется на диск.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QPoint, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
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
QWidget { font-family: 'Helvetica Neue', Helvetica, sans-serif; font-size: 13px; color: #333; }
QMainWindow, QWidget#root { background: #eef3f8; }
QFrame#card { background: #ffffff; border: 1px solid #e6eef6; border-radius: 12px; }
QLabel#title { font-size: 21px; font-weight: 600; color: #1f2d3d; }
QLabel#subtitle { color: #6b7a8c; font-size: 12px; }
QLabel#section { font-weight: 600; color: #2c3e50; font-size: 13px; }
QLabel#muted { color: #6b7a8c; font-size: 12px; }
QLabel#goal { font-size: 15px; font-weight: 600; color: #1f2d3d; }
QLabel#chip { color: #41576d; background: #f0f6fc; border: 1px solid #e2edf7; border-radius: 9px; padding: 2px 8px; font-size: 11px; }
QLabel#warn { color: #8a5300; background: #fffaf0; border: 1px solid #f6e2bd; border-radius: 8px; padding: 8px 10px; font-size: 12px; }
QLabel#error { color: #b03a2e; background: #fff5f5; border: 1px solid #f5c2c2; border-radius: 8px; padding: 8px 10px; }
QLabel#status { color: #0b62c6; font-size: 12px; }
QPlainTextEdit { background: #ffffff; border: 1px solid #d6e0ea; border-radius: 8px; padding: 8px; selection-background-color: #cfe6ff; }
QPlainTextEdit:focus { border-color: #007bff; }
QPlainTextEdit#prompt { background: #0f172a; color: #e6edf7; border: 1px solid #1b2437; font-family: Menlo, monospace; font-size: 12px; }
QLineEdit, QComboBox { background: #ffffff; border: 1px solid #d6e0ea; border-radius: 8px; padding: 7px 9px; }
QComboBox QAbstractItemView {
  background: #ffffff; color: #333333; border: 1px solid #d6e0ea; outline: none;
  selection-background-color: #e3f0ff; selection-color: #0b62c6;
}
QPushButton#picker {
  background: #ffffff; color: #333333; border: 1px solid #d6e0ea; border-radius: 8px;
  padding: 8px 10px; text-align: left;
}
QPushButton#picker:hover { border-color: #007bff; }
QFrame#techniquePopup { background: #ffffff; border: 1px solid #d6e0ea; border-radius: 12px; }
QFrame#techItem { background: #fbfdff; border: 1px solid #e6eef6; border-radius: 8px; }
QFrame#techItem:hover { background: #eef6ff; border-color: #a9cdf5; }
QLabel#techName { font-weight: 600; color: #1f2d3d; font-size: 12px; }
QLabel#techHint { color: #6b7a8c; font-size: 11px; }
QLabel#catHeader { color: #93a4b5; font-size: 10px; font-weight: 600; letter-spacing: 1px; }
QLineEdit:focus, QComboBox:focus { border-color: #007bff; }
QPushButton#primary { background: #007bff; color: #ffffff; border: none; border-radius: 8px; padding: 10px 18px; font-weight: 600; }
QPushButton#primary:hover { background: #0067d6; }
QPushButton#primary:disabled { background: #a9c7e8; }
QPushButton#ghost { background: #eef6ff; color: #0b62c6; border: 1px solid #cfe3f7; border-radius: 6px; padding: 5px 10px; font-size: 12px; }
QPushButton#ghost:hover { background: #dcecff; }
QProgressBar { background: #e4eef7; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; }
QProgressBar::chunk { background: #007bff; border-radius: 2px; }
QScrollArea { border: none; background: #ffffff; }
QScrollArea > QWidget > QWidget { background: #ffffff; }
QCheckBox { color: #5b6b7c; font-size: 12px; }
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
            self.proc = subprocess.Popen(
                [node_binary(), str(BRIDGE)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(ROOT),
            )
            out, err = self.proc.communicate(json.dumps(self.payload), timeout=900)
            if self.cancelled:
                self.finished_ok.emit({"ok": False, "error": "отменено"})
                return
            out = (out or "").strip()
            if not out:
                raise RuntimeError((err or "пустой ответ моста")[-400:])
            self.finished_ok.emit(json.loads(out))
        except Exception as exc:  # noqa: BLE001
            message = "отменено" if self.cancelled else str(exc)
            self.finished_ok.emit({"ok": False, "error": message})


CATEGORY_LABELS = {
    "context": "Контекст и подача",
    "reasoning": "Рассуждение",
    "thought_generation": "Генерация мыслей",
    "decomposition": "Декомпозиция",
    "icl": "Примеры (ICL)",
    "zero_shot_boost": "Усиление zero-shot",
    "ensembling": "Ансамбли",
    "self_critique": "Самокритика",
    "optimization": "Оптимизация промптов",
    "answer_engineering": "Извлечение ответа",
    "agents": "Агенты",
    "rag": "RAG",
    "automation": "Автоматизация и код",
    "pedagogy": "Обучение",
    "procedure": "Процедуры",
    "security": "Безопасность",
    "generation_config": "Настройки",
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
            search.setPlaceholderText("фильтр по названию…")
            outer.addWidget(search)

        scroll = QScrollArea(popup)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: #ffffff; border: none; }")

        content = QWidget()
        content.setStyleSheet("background: #ffffff;")
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
                header = QLabel(CATEGORY_LABELS.get(category, category).upper() if category else "ОСНОВНОЕ")
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
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        return layout


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Prompt Pipeline")
        self.resize(1160, 780)
        self.worker: Worker | None = None

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        header = QVBoxLayout()
        title = QLabel("Prompt Pipeline")
        title.setObjectName("title")
        subtitle = QLabel("Поток мыслей → бриф → техника → готовый промпт")
        subtitle.setObjectName("subtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        outer.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_input())
        splitter.addWidget(self._build_output())
        splitter.setSizes([440, 700])
        outer.addWidget(splitter, 1)

        self.status = QLabel("готово")
        self.status.setObjectName("status")
        outer.addWidget(self.status)

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

        label = QLabel("Поток мыслей")
        label.setObjectName("section")
        box.addWidget(label)

        hint = QLabel("Опиши как думаешь, без структуры — пайплайн сам соберёт бриф.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        box.addWidget(hint)

        self.thoughts = QPlainTextEdit()
        self.thoughts.setPlaceholderText(
            "хочу чтобы нейросеть разбирала мои заметки после встреч "
            "и вытаскивала решения, задачи и ответственных в таблицу"
        )
        self.thoughts.setMinimumHeight(150)
        box.addWidget(self.thoughts, 1)

        box.addWidget(self._mini_label("Техника"))
        self.technique = Dropdown("авто — пайплайн выберет сам", columns=2, searchable=True, popup_width=820)
        box.addWidget(self.technique)
        self.technique_hint = QLabel("конкретная техника → промпт собирается по её методике")
        self.technique_hint.setObjectName("muted")
        self.technique_hint.setWordWrap(True)
        box.addWidget(self.technique_hint)

        row = QHBoxLayout()
        row.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(self._mini_label("Провайдер"))
        self.provider = Dropdown("Ollama", popup_width=300)
        self.provider.set_items(
            [
                {"key": "ollama", "label": "Ollama (локально/облако)"},
                {"key": "gemini", "label": "Gemini"},
                {"key": "openai", "label": "OpenAI"},
            ]
        )
        self.provider.set_current("ollama")
        left.addWidget(self.provider)
        row.addLayout(left, 1)

        mid = QVBoxLayout()
        mid.setSpacing(4)
        mid.addWidget(self._mini_label("Модель"))
        model_row = QHBoxLayout()
        model_row.setSpacing(6)
        self.model = Dropdown("выбери модель", searchable=True, popup_width=460)
        self.model.set_items([{"key": name, "label": name} for name in FALLBACK_MODELS])
        self.model.set_current("minimax-m3.1-flash:cloud")
        model_row.addWidget(self.model, 1)
        self.refresh_button = QPushButton("↻")
        self.refresh_button.setObjectName("ghost")
        self.refresh_button.setFixedWidth(34)
        self.refresh_button.setToolTip("Обновить список моделей из Ollama")
        self.refresh_button.clicked.connect(self.load_models)
        model_row.addWidget(self.refresh_button)
        mid.addLayout(model_row)
        self.models_hint = QLabel("список моделей Ollama загружается…")
        self.models_hint.setObjectName("muted")
        self.models_hint.setWordWrap(True)
        row.addLayout(mid, 1)

        box.addLayout(row)
        box.addWidget(self.models_hint)

        key_row = QVBoxLayout()
        key_row.setSpacing(4)
        key_row.addWidget(self._mini_label("API Key (для Ollama не нужен)"))
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("sk-…")
        key_row.addWidget(self.api_key)
        box.addLayout(key_row)

        self.deterministic = QCheckBox("без LLM-синтеза (быстро, офлайн)")
        box.addWidget(self.deterministic)

        variants_row = QHBoxLayout()
        variants_row.setSpacing(8)
        variants_label = QLabel("Вариантов техник:")
        variants_label.setObjectName("muted")
        variants_row.addWidget(variants_label)
        self.variants = Dropdown("3", popup_width=160)
        self.variants.set_items([
            {"key": "3", "label": "3 варианта"},
            {"key": "2", "label": "2 варианта"},
            {"key": "1", "label": "1 вариант"},
        ])
        self.variants.set_current("3")
        variants_row.addWidget(self.variants)
        variants_row.addStretch(1)
        box.addLayout(variants_row)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.run_button = QPushButton("Собрать промпт")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.run_pipeline)
        actions.addWidget(self.run_button, 1)

        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.setObjectName("ghost")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_run)
        actions.addWidget(self.cancel_button)
        box.addLayout(actions)

        return card

    def _mini_label(self, text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setObjectName("muted")
        font = label.font()
        font.setPointSize(9)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        label.setFont(font)
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
                item["name"] = f"{item.get('name', item['key'])} (процедура)"
            item["label"] = item.get("name", item["key"])
        self.technique.set_items(techniques, keep=self.technique.current_key())
        self.technique_hint.setText(f"конкретная техника → промпт по её методике ({len(techniques)} доступно)")

    def load_models(self) -> None:
        self.models_hint.setText("запрашиваю модели у Ollama…")
        self.refresh_button.setEnabled(False)
        self.models_loader = ModelsLoader()
        self.models_loader.loaded.connect(self._on_models_loaded)
        self.models_loader.start()

    def _on_models_loaded(self, names: list) -> None:
        self.refresh_button.setEnabled(True)
        if not names:
            self.models_hint.setText(
                "Ollama не отвечает на localhost:11434 — список оставлен прежним, имя можно вписать вручную"
            )
            return

        current = self.model.current_key().strip()
        self.model.set_items([{"key": name, "label": name} for name in names], keep=current)
        if not self.model.current_key():
            self.model.set_current(names[0])
        self.models_hint.setText(f"загружено моделей: {len(names)}")

    def _on_provider_changed(self, provider: str) -> None:
        if provider == "ollama":
            self.load_models()
        else:
            self.models_hint.setText("для облачных провайдеров имя модели вводится вручную")

    # ── правая колонка ────────────────────────────────────────────
    def _build_output(self) -> QWidget:
        card = Card()
        box = card.vbox()

        history_row = QHBoxLayout()
        history_row.setSpacing(8)
        history_label = QLabel("ИСТОРИЯ")
        history_label.setObjectName("muted")
        history_row.addWidget(history_label)
        self.history = QComboBox()
        self.history.addItem("— пусто —", -1)
        self.history.currentIndexChanged.connect(self._on_history_selected)
        history_row.addWidget(self.history, 1)
        box.addLayout(history_row)

        self.output_scroll = QScrollArea()
        self.output_scroll.setWidgetResizable(True)
        self.output_holder = QWidget()
        self.output_holder.setStyleSheet("background: #ffffff;")
        self.output_layout = QVBoxLayout(self.output_holder)
        self.output_layout.setContentsMargins(0, 0, 0, 0)
        self.output_layout.setSpacing(10)
        # Скролл должен расти под содержимое, иначе виджеты наезжают друг на друга.
        self.output_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.output_scroll.setWidget(self.output_holder)
        box.addWidget(self.output_scroll, 1)

        self._show_placeholder()
        return card

    def _push_history(self, label: str, kind: str, payload: dict) -> None:
        self.history.blockSignals(True)
        self.history.addItem(label, len(self.history))
        self.history.setCurrentIndex(self.history.count() - 1)
        self.history.blockSignals(False)
        if not hasattr(self, "_history_items"):
            self._history_items = []
        self._history_items.append((kind, payload))

    def _on_history_selected(self, index: int) -> None:
        items = getattr(self, "_history_items", [])
        if index <= 0 or index - 1 >= len(items):
            return
        kind, payload = items[index - 1]
        if kind == "manual":
            self.render_manual(payload)
        elif kind == "procedure":
            self.render_procedure(payload)
        else:
            self.render(payload)

    def _clear_output(self) -> None:
        while self.output_layout.count():
            item = self.output_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _show_placeholder(self) -> None:
        self._clear_output()
        label = QLabel(
            "Здесь появятся бриф, выбранная техника с обоснованием,\nпромпт и конфиг."
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
            self.status.setText("отмена…")

    def run_pipeline(self) -> None:
        if self.worker and self.worker.isRunning():
            return

        thoughts = self.thoughts.toPlainText().strip()
        if not thoughts:
            self.status.setText("напиши поток мыслей")
            return

        provider = self.provider.current_key()
        model = self.model.current_key().strip()
        api_key = self.api_key.text().strip()

        if not model:
            self.status.setText("укажи модель")
            return
        if provider != "ollama" and not api_key:
            self.status.setText("нужен API key")
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
        self.status.setText("бриф → выбор техники → синтез…")

        self.worker = Worker(payload)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.start()

    def on_finished(self, data: dict) -> None:
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if not data.get("ok"):
            self._clear_output()
            error = QLabel(f"Ошибка: {data.get('error', 'неизвестно')}")
            error.setObjectName("error")
            error.setWordWrap(True)
            self.output_layout.addStretch(1)
            self.output_layout.addWidget(error)
            self.output_layout.addStretch(1)
            self.status.setText("ошибка")
            return

        if data.get("procedure"):
            self.render_procedure(data["procedure"])
            self._push_history(data["procedure"]["technique"]["name"], "procedure", data["procedure"])
            self.status.setText(f"{data['procedure']['technique']['name']} · процедура, промпта нет")
            return

        if data.get("manual"):
            self.render_manual(data["manual"])
            self._push_history(data["manual"]["technique"]["name"], "manual", data["manual"])
            self.status.setText(f"{data['manual']['technique']['name']} · собрано по методике")
            return

        self.render(data["result"])
        self._push_history(data["result"]["choice"]["name"], "pipeline", data["result"])
        choice = data["result"]["choice"]
        warnings = len(data["result"]["synthesis"]["warnings"])
        self.status.setText(f"{choice['name']} · предупреждений: {warnings}")

    def render_procedure(self, procedure: dict) -> None:
        self._clear_output()

        technique = procedure["technique"]
        title = QLabel(technique["name"])
        title.setObjectName("goal")
        title.setWordWrap(True)
        self.output_layout.addWidget(title)

        meta = QLabel(f"{technique['key']} · {technique['category']} · источник: {procedure['source_ref']}")
        meta.setObjectName("muted")
        meta.setWordWrap(True)
        self.output_layout.addWidget(meta)

        explain = QLabel(
            "Это не промпт, а процедура над данными или моделью. Шаги выполняются кодом или вручную."
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

        when = QLabel(f"Когда уместно: {procedure['when_to_use']}")
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

        meta = QLabel(f"{technique['key']} · {technique['category']} · источник: {manual['source_ref']}")
        meta.setObjectName("muted")
        meta.setWordWrap(True)
        self.output_layout.addWidget(meta)

        prompt_head = QHBoxLayout()
        label = QLabel("ПРОМПТ")
        label.setObjectName("muted")
        prompt_head.addWidget(label)
        prompt_head.addStretch(1)
        copy_button = QPushButton("Копировать")
        copy_button.setObjectName("ghost")
        prompt_head.addWidget(copy_button)
        self.output_layout.addLayout(prompt_head)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setObjectName("prompt")
        self.prompt_edit.setStyleSheet(
            "QPlainTextEdit { background: #0f172a; color: #e6edf7; border: 1px solid #1b2437;"
            " border-radius: 8px; padding: 10px; font-family: Menlo, monospace; font-size: 12px; }"
        )
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
            f"тип: {brief['task_type']}",
            f"язык: {brief['language']}",
            f"цена ошибки: {brief['stakes']}",
        ):
            chip = QLabel(text)
            chip.setObjectName("chip")
            chips.addWidget(chip)
        chips.addStretch(1)
        self.output_layout.addLayout(chips)

        fmt = QLabel(f"Формат: {brief['output_format']}")
        fmt.setObjectName("muted")
        fmt.setWordWrap(True)
        self.output_layout.addWidget(fmt)

        if brief.get("assumptions"):
            assumptions = QLabel("Допущения: " + "; ".join(brief["assumptions"]))
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
        confidence = QLabel(f"уверенность {round(choice['confidence'] * 100)}%")
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

        why = QLabel(f"Почему: {choice['reason']}")
        why.setWordWrap(True)
        why.setObjectName("muted")
        tech_box.addWidget(why)

        why_not = QLabel(f"Почему не дешевле: {choice['whyNotCheaper']}")
        why_not.setWordWrap(True)
        why_not.setObjectName("muted")
        tech_box.addWidget(why_not)

        self.output_layout.addWidget(tech)

        prompt_head = QHBoxLayout()
        prompt_label = QLabel("ПРОМПТ")
        prompt_label.setObjectName("muted")
        prompt_head.addWidget(prompt_label)
        prompt_head.addStretch(1)
        copy_button = QPushButton("Копировать")
        copy_button.setObjectName("ghost")
        copy_button.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.prompt_edit.toPlainText())
        )
        prompt_head.addWidget(copy_button)
        self.output_layout.addLayout(prompt_head)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setObjectName("prompt")
        self.prompt_edit.setStyleSheet(
            "QPlainTextEdit { background: #0f172a; color: #e6edf7; border: 1px solid #1b2437;"
            " border-radius: 8px; padding: 10px; font-family: Menlo, monospace; font-size: 12px; }"
        )
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

            head = QLabel(f"Вариант {index}: {alt_choice['name']} ({alt_choice['key']})")
            head.setObjectName("section")
            head.setWordWrap(True)
            head.setStyleSheet("margin-top: 10px; border-top: 1px dashed #e6eef6; padding-top: 10px;")
            self.output_layout.addWidget(head)

            why = QLabel(alt_choice["reason"])
            why.setObjectName("muted")
            why.setWordWrap(True)
            self.output_layout.addWidget(why)

            box = QPlainTextEdit()
            box.setStyleSheet(
                "QPlainTextEdit { background: #0f172a; color: #e6edf7; border: 1px solid #1b2437;"
                " border-radius: 8px; padding: 8px; font-family: Menlo, monospace; font-size: 11px; }"
            )
            box.setPlainText(alt_synth["prompt"])
            box.setReadOnly(True)
            box.setFixedHeight(150)
            self.output_layout.addWidget(box)

            cfg = alt_synth["config"]
            meta = QLabel(f"temperature {cfg['temperature']} · {cfg['max_tokens']}")
            meta.setObjectName("muted")
            self.output_layout.addWidget(meta)

        footer = QLabel(f"отсеяно до выбора: {len(result['rejected'])} техник")
        footer.setObjectName("muted")
        self.output_layout.addWidget(footer)

        self.output_layout.addStretch(1)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Prompt Pipeline")
    app.setStyleSheet(QSS)
    window = MainWindow()
    window.show()

    if "--screenshot" in sys.argv:
        # Самопроверка вёрстки: рендерим демо-результат и сохраняем окно в PNG.
        index = sys.argv.index("--screenshot")
        path = sys.argv[index + 1] if len(sys.argv) > index + 1 else "/tmp/app.png"
        window.thoughts.setPlainText(
            "хочу чтобы нейросеть разбирала мои заметки после встреч "
            "и вытаскивала решения, задачи и ответственных в таблицу"
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
                    "goal": "Разбирать заметки после встреч: вытащить решения, задачи и ответственных в таблицу",
                    "task_type": "extraction",
                    "language": "ru",
                    "stakes": "high",
                    "output_format": "markdown-таблица: Тип | Формулировка | Ответственный",
                    "assumptions": ["заметки приходят текстом, не аудио"],
                },
                "choice": {
                    "name": "Contextual prompting",
                    "key": "contextual_prompting",
                    "confidence": 0.82,
                    "reason": "Задача заземлена на материале: заметки вставляются в промпт, ответ ограничен ими.",
                    "whyNotCheaper": "zero_shot не удержит формат таблицы, few_shot — нет примеров в брифе.",
                },
                "synthesis": {
                    "prompt": "Use ONLY the material below. Cite [n] for every claim.\n\n[1] текст заметок на русском\n\nTask: разобрать заметки и вернуть таблицу\nOutput: markdown-таблица",
                    "config": {
                        "temperature": 0.2,
                        "top_p": 0.95,
                        "max_tokens": "1024",
                        "rationale": "Низкая температура: нужен стабильный формат и следование инструкции.",
                    },
                    "warnings": [],
                },
                "alternatives": [
                    {
                        "choice": {
                            "name": "Few-shot (one-shot)",
                            "key": "few_shot",
                            "confidence": 0.64,
                            "reason": "Нужен строгий формат таблицы — примеры задают его лучше инструкции.",
                            "whyNotCheaper": "zero_shot не удержит формат.",
                        },
                        "synthesis": {
                            "prompt": "Task: разбери заметки и верни таблицу.\n\nПример 1:\nInput: «Петя подготовит отчёт к пятнице»\nOutput: | Подготовить отчёт | Петя | пятница |\n\nInput: ВСТАВЬ СЮДА: текст заметок\nOutput:",
                            "config": {"temperature": 0.2, "top_p": 0.95, "max_tokens": "1024"},
                            "warnings": [],
                            "rationale": "Низкая температура: форматы должны совпадать.",
                        },
                    }
                ],
                "rejected": [{}] * 53,
            }
        )
        window.status.setText("Contextual prompting · предупреждений: 1")
        window.resize(1160, 1180)
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
