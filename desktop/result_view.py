"""Вёрстка результата Prompta: раскрывающиеся блоки, поток чипов, подписи и константы целей."""

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


GENERAL_TARGET = "general"
CONTROL_HEIGHT = 28
BLOCK_GAP = 28  # air between the result blocks: prompt, understood, why
SUBSECTION_GAP = 14  # air above each subsection inside "How this prompt was built"
ACTION_HEIGHT = 34
# Routine pipeline notes, present on most results; they stay in the folded details and are not counted.
NOTE_PREFIXES = ("General ", "High stakes:", "Low stakes:", "Prompt-injection guard added")


def split_warnings(warnings: list[str]) -> tuple[list[str], list[str]]:
    """(actionable warnings shown under the prompt, routine notes kept in the details)."""
    unique = list(dict.fromkeys(warnings))
    notes = [w for w in unique if w.startswith(NOTE_PREFIXES)]
    return [w for w in unique if w not in notes], notes
TARGET_SEGMENTS = [(GENERAL_TARGET, "Any")] + [(key, label) for key, (label, _) in PROMPT_TARGETS.items() if key != "openModel"]


def find_layout(layout: QLayout, widget: QWidget) -> QLayout | None:
    """The layout that directly holds `widget`, searched recursively from `layout`."""
    if layout.indexOf(widget) >= 0:
        return layout
    for i in range(layout.count()):
        child = layout.itemAt(i).layout()
        if child is not None and (found := find_layout(child, widget)) is not None:
            return found
    return None


class Disclosure(QWidget):
    """A ▸/▾ toggle with collapsible content below it."""

    def __init__(self, title: str, expanded: bool = False, field_label: bool = False, collapsible: bool = True) -> None:
        super().__init__()
        self._title = title
        self._field_label = field_label
        self._collapsible = collapsible
        expanded = expanded or not collapsible
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.button = QToolButton()
        self.button.setObjectName("disclosure")
        self.button.setProperty("field", field_label)
        self.button.setCheckable(True)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.button.toggled.connect(self._toggle)
        if not collapsible:  # a plain section heading: always open, nothing to click
            self.button.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.button.unsetCursor()
        box.addWidget(self.button, 0, Qt.AlignmentFlag.AlignLeft)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        box.addWidget(self.body)
        self.button.setChecked(expanded)
        self._toggle(expanded)

    def title(self) -> str:
        return self._title

    def set_title(self, title: str) -> None:
        self._title = title
        self._toggle(self.button.isChecked())

    def _toggle(self, expanded: bool) -> None:
        title = self._title.upper() if self._field_label else self._title
        self.button.setText(f"{'▾' if expanded else '▸'}  {title}" if self._collapsible else title)
        self.body.setVisible(expanded)


class FlowLayout(QLayout):
    """Left-to-right rows that wrap: chips never get squeezed into two-line pills. Hidden widgets take no room."""

    def __init__(self, spacing: int = 6, line_spacing: int = 8) -> None:
        super().__init__()
        self._items = []
        self.line_spacing = line_spacing  # air between wrapped rows
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect, apply: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        gap = self.spacing()
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if x > rect.x() and x + hint.width() > rect.right() + 1:
                x, y, line = rect.x(), y + line + self.line_spacing, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + gap
            line = max(line, hint.height())
        return y + line - rect.y()


def chip_label(text: str, tooltip: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("chip")
    if tooltip:
        label.setToolTip(tooltip)
    return label


def spec_text(config: dict) -> tuple[str, str]:
    """Run settings as one quiet line plus hover text: 'temp 0.3 · top_p 0.95 · max 1024'."""
    value = lambda key: config.get(key) if config.get(key) is not None else "default"
    max_tokens = str(value("max_tokens"))
    short, _, tail = max_tokens.partition(" (")
    tooltip = " ".join(part for part in (f"max_tokens: {max_tokens}." if tail else "", config.get("rationale", "")) if part)
    return f"temp {value('temperature')} · top_p {value('top_p')} · max {short.lower()}", tooltip


def field_label(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("fieldLabel")
    return label


def config_chips(config: dict) -> list[QLabel]:
    """Generation settings as chips; the rationale is the hover text."""
    why = config.get("rationale", "")
    chips = [chip_label(f"{key} {config.get(key) if config.get(key) is not None else 'default'}", why)
             for key in ("temperature", "top_p")]  # always first, even when the model's default applies
    if config.get("max_tokens") is not None:
        chips.append(chip_label(f"max_tokens {str(config['max_tokens']).lower()}", why))
    return chips


def note_chip(note: str) -> QLabel:
    """A pipeline note as a short chip (text before the colon), full text on hover."""
    head = re.split(r":|\.\s", note, maxsplit=1)[0].strip()  # "K3.1" keeps its dot
    return chip_label(head if len(head) <= 48 else head[:46] + "…", note)


def muted_label(text: str, name: str = "muted") -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def keyed_label(key: str, text: str, stacked: bool = False) -> QLabel:
    """Body text led by a quiet key: "Format  Markdown table"; a list goes under its key."""
    body = escape(text).replace("\n", "<br>")
    label = QLabel(f'<span style="color:#9a8d6c">{escape(key)}</span>' + ("<br>" if stacked else "&nbsp;&nbsp;") + body)
    label.setObjectName("muted")
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label
