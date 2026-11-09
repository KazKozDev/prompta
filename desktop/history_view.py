"""История запросов в окне Prompta: вынесена из MainWindow, подмешивается в него."""

from __future__ import annotations

import json
import os
import re
from html import escape
from urllib.parse import urlparse, urlencode
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
    from .history import HistoryStore, history_topic
    from .library import LibraryWidget
    from .mcp_settings import McpSettingsWidget
except ImportError:
    from history import HistoryStore, history_topic
    from library import LibraryWidget
    from mcp_settings import McpSettingsWidget

from PyQt6.QtCore import QModelIndex, QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QUrl, QProcess, QThread, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel, QColor, QCursor, QPainter, QPalette, QPen, QFont, QGuiApplication, QIcon, QPixmap, QKeySequence, QShortcut, QDesktopServices, QTextDocument
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
    from .theme import CHAT_URLS, DARK_SCROLL_QSS, PROMPT_TARGETS, QSS, ROOT
    from .widgets import *  # noqa: F401,F403 — базовые виджеты, вынесенные из этого файла
except ImportError:
    from theme import CHAT_URLS, DARK_SCROLL_QSS, PROMPT_TARGETS, QSS, ROOT
    from widgets import *  # noqa: F401,F403
import os
from datetime import datetime
try:
    from .result_view import *  # noqa: F401,F403
except ImportError:
    from result_view import *  # noqa: F401,F403


class HistoryMixin:
    """История в главном окне: поиск, выбор, удаление, очистка и настройки хранения."""

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
        self.history.addItem("— history —" if self._history_items else "— no history yet —", -1)
        for index, entry in enumerate(self._history_items):
            searchable = entry['thoughts'] + ' ' + entry['label'] + ' ' + json.dumps(entry['payload'], ensure_ascii=False)
            if needle and needle not in searchable.casefold():
                continue
            label = history_topic(entry['thoughts'], entry['payload'], entry['label'])
            self.history.addItem(label, index)
            date = entry['created_at'][:16].replace('T', ' ')
            self.history.setItemData(self.history.count() - 1, f"{label}\n{date}\n{entry['thoughts']}", Qt.ItemDataRole.ToolTipRole)
        if self.history.count() == 1 and needle:
            self.history.setItemText(0, "— no matches —")
        target = self.history.findData(current)
        self.history.setCurrentIndex(max(0, target))
        self.history.blockSignals(False)

    def _delete_history(self, row: int) -> None:
        removed = self.history.itemData(row)
        if not isinstance(removed, int) or not 0 <= removed < len(self._history_items):
            return
        entry = self._history_items[removed]
        if entry.get('id') is not None:
            try:
                self.history_store.delete(entry['id'])
            except (OSError, sqlite3.Error):
                self.history_notice.setText("Could not delete this entry from disk.")
                self.history_notice.show()
                return
        del self._history_items[removed]
        current = self.history.currentData()
        if isinstance(current, int) and current >= 0:
            current = -1 if current == removed else current - (current > removed)
        self._filter_history(self.history_search.text(), selected=current)
        if self.history.count() > 1:
            self.history.showPopup()  # rebuild the open list without the deleted row
        else:
            self.history.hidePopup()

    HISTORY_LIMITS = [(100, "Keep the newest 100"), (500, "Keep the newest 500"), (2000, "Keep the newest 2,000"),
                      (0, "Keep everything"), (-1, "Don't save history")]
    HISTORY_AGES = [(0, "Forever"), (30, "30 days"), (90, "90 days"), (365, "1 year")]

    def _history_prefs_path(self) -> Path:
        return self.history_store.path.with_name("settings.json")

    def _load_history_prefs(self) -> None:
        """Saved choice applies unless an environment variable already set the limit."""
        try:
            prefs = json.loads(self._history_prefs_path().read_text())
        except (OSError, ValueError):
            return
        if "PROMPTA_HISTORY_MAX" not in os.environ and isinstance(prefs.get("history_max"), int):
            self.history_store.max_entries = prefs["history_max"]
        if "PROMPTA_HISTORY_DAYS" not in os.environ and isinstance(prefs.get("history_days"), int):
            self.history_store.max_age_days = max(0, prefs["history_days"])

    def _build_history_settings(self) -> QWidget:
        self._load_history_prefs()
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 18, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self._mini_label("How many requests to keep"))
        self.history_limit = QComboBox()
        self.history_limit.setAccessibleName("How many requests to keep")
        for value, label in self.HISTORY_LIMITS:
            self.history_limit.addItem(label, value)
        index = self.history_limit.findData(self.history_store.max_entries)
        if index < 0:
            self.history_limit.addItem(f"Keep the newest {self.history_store.max_entries}", self.history_store.max_entries)
            index = self.history_limit.count() - 1
        self.history_limit.setCurrentIndex(index)
        layout.addWidget(self.history_limit)
        layout.addWidget(self._mini_label("Delete requests older than"))
        self.history_age = QComboBox()
        self.history_age.setAccessibleName("Delete requests older than")
        for value, label in self.HISTORY_AGES:
            self.history_age.addItem(label, value)
        self.history_age.setCurrentIndex(max(0, self.history_age.findData(self.history_store.max_age_days)))
        layout.addWidget(self.history_age)
        hint = QLabel("History stays on this Mac, readable only by your user account. "
                      "Older entries are removed when a new result is saved.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        delete_all = QPushButton("Delete all history…")
        self.delete_all_history_button = delete_all
        delete_all.setAccessibleName("Delete all history")
        delete_all.clicked.connect(self.clear_history)
        layout.addWidget(delete_all, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        self.history_limit.currentIndexChanged.connect(self._history_prefs_changed)
        self.history_age.currentIndexChanged.connect(self._history_prefs_changed)
        return page

    def _history_prefs_changed(self, *_: object) -> None:
        self.history_store.max_entries = int(self.history_limit.currentData())
        self.history_store.max_age_days = int(self.history_age.currentData())
        path = self._history_prefs_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_text(json.dumps({"history_max": self.history_store.max_entries,
                                        "history_days": self.history_store.max_age_days}))
            removed = self.history_store.prune()
        except (OSError, sqlite3.Error):
            self.history_notice.setText("Could not save the history setting.")
            self.history_notice.show()
            return
        if removed:
            self._history_items = self.history_store.load()
            self._shown_entry = None
            self._filter_history()

    def clear_history(self) -> None:
        """Delete every saved entry after an explicit confirmation: the database file is removed."""
        if not self._history_items:
            return
        answer = QMessageBox.question(
            self, "Delete all history?",
            f"Delete all {len(self._history_items)} saved requests and prompts? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.history_store.clear()
        except OSError:
            self.history_notice.setText("Could not delete the history file.")
            self.history_notice.show()
            return
        self._history_items = []
        self._shown_entry = None
        self.history_search.clear()
        self._filter_history()
        self.history_notice.setText("History deleted.")
        self.history_notice.show()

    def _push_history(self, label: str, kind: str, payload: dict) -> None:
        thoughts = self._active_thoughts or self.thoughts.toPlainText().strip()
        label = history_topic(thoughts, payload, label)
        try:
            entry = self.history_store.add(label, kind, thoughts, payload)
        except (OSError, ValueError, sqlite3.Error):
            self.history_notice.setText("Could not save history to disk. This result is still available in this window.")
            self.history_notice.show()
            entry = {'label': label, 'kind': kind, 'thoughts': thoughts,
                     'payload': payload, 'created_at': datetime.now().isoformat()}
        self._history_items.append(entry)
        self._shown_entry = len(self._history_items) - 1  # prompt edits are saved into this entry
        self.history_search.clear()
        self._filter_history(selected=len(self._history_items) - 1)

    def _on_history_selected(self, index: int) -> None:
        item_index = self.history.itemData(index)
        if not isinstance(item_index, int) or not 0 <= item_index < len(self._history_items):
            return
        entry = self._history_items[item_index]
        kind, payload = entry['kind'], entry['payload']
        self.thoughts.setPlainText(entry['thoughts'])
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
        self._shown_entry = item_index
        self.thoughts.setPlainText(entry['thoughts'])
        selected = next((key for key in PROMPT_TARGETS if payload.get(f"{key}Guidance")), None)
        model_index = 0
        if selected == "openModel":
            # The hidden openModel toggle is only valid with a concrete model chosen in the dropdown.
            model_index = max(0, self.prompt_model.findText(str(payload["openModelGuidance"].get("target", ""))))
            if model_index == 0:
                selected = None
        previous = self.prompt_model.blockSignals(True)
        self.prompt_model.setCurrentIndex(model_index)
        self.prompt_model.blockSignals(previous)
        for key in PROMPT_TARGETS:
            getattr(self, f"{key}_only").setChecked(key == selected)
