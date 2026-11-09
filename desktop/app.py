#!/usr/bin/env python3
"""Prompta — нативное приложение для macOS.

UI на PyQt6, логика — существующий TS-пайплайн через мост desktop/bridge.ts.
История хранится локально; ключи API на диск не записываются.
"""

from __future__ import annotations

import json
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

ROOT = Path(__file__).resolve().parent.parent
BRIDGE = ROOT / "desktop" / "bridge.ts"

OLLAMA_TAGS = "http://localhost:11434/api/tags"
FALLBACK_MODELS = [
    "minimax-m3.1-flash:cloud",
    "glm-5.3:cloud",
    "deepseek-v4-pro:cloud",
    "qwen3:30b",
]


PROMPT_TARGETS = {
    "claude": ("Claude", ("platform.claude.com",)),
    "chatgpt": ("ChatGPT", ("developers.openai.com", "platform.openai.com", "learn.chatgpt.com")),
    "gemini": ("Gemini", ("ai.google.dev", "aistudio.google.com", "docs.cloud.google.com", "cloud.google.com")),
    "grok": ("Grok", ("docs.x.ai",)),
    "openModel": ("Open-weight model", ("huggingface.co",)),
}


CHAT_URLS = {
    "chatgpt": "https://chatgpt.com/",
    "claude": "https://claude.ai/new",
    "gemini": "https://gemini.google.com/app",
    "grok": "https://grok.com/",
}


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
QWidget { font-family: 'Helvetica Neue'; font-size: 13px; color: #4a4232; }
QMainWindow { background: #f5f6f8; }
QWidget#root { background: transparent; }
QDialog { background: #fff8e7; }
QPushButton#settings { background: transparent; border: 1px solid transparent; border-radius: 9px; }
QPushButton#settings:hover { background: #e7edf5; border-color: #d8c593; }
QPushButton#settings:pressed { background: #f2eddc; }
QPushButton#settings:focus { border-color: #c69b12; }
QFrame#tech { background: transparent; border: none; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #f2e6c5; color: #74839a; padding: 8px 18px; margin-right: 5px; border: 1px solid #dfcfa6; border-radius: 7px; }
QTabBar::tab:selected { background: #fffbed; color: #6f5710; border-color: #efe3b9; }
QTreeWidget#libraryTree { background: #fffdf5; border: 1px solid #d8c593; border-radius: 9px; padding: 5px; outline: none; }
QTreeWidget#libraryTree::item { padding: 5px 2px; }
QTreeWidget#libraryTree::item:selected { background: #fffae9; color: #6f5710; }
QFrame#card { background: #fff8e7; border: 1px solid #d8c593; border-radius: 16px; }
QFrame#mainColumn { background: transparent; border: none; }
QScrollArea#outputScroll, QWidget#outputContent { background: transparent; border: none; }
QLabel#title { font-family: 'Avenir Next'; font-size: 17px; letter-spacing: -0.2px; color: #202632; }
QLabel#subtitle { color: #74694f; font-size: 13px; }
QLabel#section { font-weight: 600; color: #332e24; font-size: 13px; }
QLabel#fieldLabel { color: #74694f; font-size: 10px; font-weight: 500; letter-spacing: 1px; }
QLabel#muted { color: #665d49; font-size: 12px; }
QLabel#oneShotHint { color: #8a7d5c; font-size: 11px; }
QLabel#goal { font-size: 15px; font-weight: 600; color: #332e24; }
QLabel#chip { color: #5b6574; background: #f2e6c5; border: 1px solid #dfd0a8; border-radius: 8px; padding: 3px 8px; font-size: 11px; }
QLabel#warn { color: #8a5300; background: #fffaf0; border: 1px solid #f6e2bd; border-radius: 8px; padding: 8px 10px; font-size: 12px; }
QLabel#error { color: #b03a2e; background: #fff5f5; border: 1px solid #f5c2c2; border-radius: 8px; padding: 8px 10px; }
QLabel#status { color: #74694f; font-size: 12px; }
QPlainTextEdit { font-size: 13px; background: rgba(255, 248, 226, 232); border: 1px solid #d8c593; border-radius: 10px; padding: 10px; selection-background-color: #fff9e3; }
QPlainTextEdit:focus { border-color: #c69b12; }
QPlainTextEdit#prompt { padding: 10px; background: #454545; color: #f5f5f5; border: 1px solid #565656; font-family: 'Helvetica Neue'; font-size: 13px; selection-background-color: #675b32; selection-color: #ffffff; }
QLineEdit, QComboBox { font-size: 13px; background: rgba(255, 248, 226, 240); border: 1px solid #d8c593; border-radius: 8px; padding: 7px 10px; min-height: 18px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
  font-size: 13px; background: transparent; color: #4a4232; border: none; outline: none;
  selection-background-color: #fff9e3; selection-color: #6f5710;
}
QListWidget#historyList { background: #fff8e7; color: #4a4232; border: none; outline: none; font-size: 13px; }
QListWidget#historyList::item { padding: 7px 30px 7px 10px; border: none; border-radius: 5px; }
QListWidget#historyList::item:hover, QListWidget#historyList::item:selected { background: #f6e5b3; color: #4a4232; }
QFrame#variantCount { background: rgba(245, 231, 191, 225); border: 1px solid #d8c593; border-radius: 10px; }
QPushButton#variantOption { background: transparent; border: 1px solid transparent; border-radius: 7px; color: #827456; padding: 0; font-size: 13px; font-weight: 500; }
QPushButton#variantOption:hover { color: #34465f; background: #f4e4b7; }
QPushButton#variantOption:checked { background: #fff8e7; border-color: #d8c593; color: #6f5710; font-weight: 600; }
QPushButton#variantOption:focus { border-color: #c69b12; }
QCheckBox#targetOption { background: rgba(255, 245, 214, 222); border: 1px solid #d8c593; border-radius: 9px; padding: 9px 10px; spacing: 8px; color: #665b42; font-size: 12px; }
QCheckBox#targetOption:hover { background: #fff0c6; border-color: #ede6cc; }
QCheckBox#targetOption:checked { background: #fffbee; border-color: #f1e5ba; color: #6f5710; }
QCheckBox#targetOption:focus { border-color: #c69b12; }
QCheckBox#targetOption:disabled { color: #bab5a3; background: #fafbfc; border-color: #edf0f4; }
QFrame#inputDivider { background: rgba(151, 119, 40, 40); border: none; }
QLabel#variantsLabel { color: #665b42; font-size: 12px; font-weight: 500; }
QPushButton#buildPrompt { background: #f4ca38; color: #352b10; border: 1px solid #f4ca38; border-radius: 10px; padding: 0 18px; font-size: 13px; font-weight: 600; }
QPushButton#buildPrompt:hover { background: #e9bc24; border-color: #e9bc24; }
QPushButton#buildPrompt:pressed { background: #d9aa16; border-color: #d9aa16; }
QPushButton#buildPrompt:focus { border: 2px solid #fceaa9; }
QPushButton#buildPrompt:disabled { background: #e8cc72; color: #796225; border-color: #d8bc62; }
QPushButton#copyPrompt { background: transparent; border: none; border-radius: 6px; padding: 0; }
QPushButton#copyPrompt:hover { background: #575757; }
QPushButton#copyPrompt:pressed { background: #646464; }
QPushButton#copyPrompt:focus { border: 1px solid #c69b12; }
QPushButton#articleLink { background: transparent; border: none; border-radius: 5px; padding: 0; }
QPushButton#articleLink:hover { background: #f8f4e7; }
QPushButton#articleLink:focus { border: 1px solid #c69b12; }
QPushButton#picker {
  font-size: 13px; background: rgba(255, 248, 226, 240); color: #4a4232; border: 1px solid #d8c593; border-radius: 8px;
  padding: 7px 10px; min-height: 18px; text-align: left;
}
QPushButton#picker:hover { border-color: #d6cfb5; }
QPushButton#picker:pressed { background: #f6f0dc; }
QPushButton#picker:disabled { color: #afaa9a; background: #f8f9fb; border-color: #e9ecf1; }
QFrame#techniquePopup, QFrame#historyPopup { background: #fff8e7; border: 1px solid #d8c593; border-radius: 12px; }
QFrame#techItem { background: #fff9ed; border: 1px solid #e5d9bb; border-radius: 10px; }
QFrame#techItem:hover { background: #f8edcf; border-color: #c9ae70; }
QLabel#techName { font-weight: 600; color: #262e3c; font-size: 13px; }
QLabel#techHint { color: #82745a; font-size: 12px; }
QLabel#catHeader { color: #74694f; font-size: 10px; font-weight: 500; letter-spacing: 1px; }
QLineEdit:focus, QComboBox:focus { border-color: #c69b12; }
QPushButton#primary { background: #fff9e5; color: #6f5710; border: 1px solid #d8c593; border-radius: 8px; min-height: 18px; padding: 7px 18px; font-weight: 500; }
QPushButton#primary:hover { background: #faf6e7; border-color: #e9deb8; }
QPushButton#primary:pressed { background: #f6f0dc; border-color: #e1d5a8; }
QPushButton:focus { border: 1px solid #c69b12; }
QLineEdit:hover, QComboBox:hover { border-color: #d6cfb5; }
QPushButton#primary:disabled { background: #f4ead4; color: #b5af9a; border-color: #e5e8ef; }
QPushButton#ghost { background: #f6ebd0; color: #6f5710; border: 1px solid #d8c593; border-radius: 8px; min-height: 18px; padding: 7px 11px; font-size: 12px; }
QPushButton#ghost:hover { background: #f5e5bc; }
QPushButton#ghost:pressed { background: #f5f2e5; }
QPushButton#ghost:disabled { color: #a69f84; background: #f4ead0; border-color: #e1d4b0; }
QProgressBar { background: #f7f3e4; border: none; border-radius: 1px; max-height: 2px; min-height: 2px; }
QProgressBar::chunk { background: #c69b12; border-radius: 1px; }
QProgressBar#generationProgress { background: #e9d8a0; min-height: 3px; max-height: 3px; border-radius: 1px; }
QProgressBar#generationProgress::chunk { background: #e1b72c; border-radius: 1px; }
QScrollArea { border: none; background: #fff8e7; }
QScrollArea#inputScroll, QWidget#inputViewport { background: transparent; }
QWidget#scrollContent { background: #fff8e7; }
QCheckBox { color: #626d7d; font-size: 12px; spacing: 8px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #d8c593; border-radius: 4px; background: #fff8e7; }
QCheckBox::indicator:hover { border-color: #c69b12; background: #fffbec; }
QCheckBox::indicator:checked { background: #f4ca38; border-color: #c69b12; image: url(CHECK_ICON); }
QCheckBox::indicator:disabled { background: #f2f4f7; border-color: #e0e4eb; }
QSplitter::handle:horizontal { width: 24px; background: transparent; }
QSplitter::handle:horizontal:hover { background: #f3efe2; border-radius: 4px; }
/* Keep the scrollbar hit area usable while the visible handle stays slim. */
QScrollBar:vertical { border: none; background: #f4ead0; width: 12px; margin: 3px 2px; border-radius: 4px; }
QScrollBar:horizontal { border: none; background: #f4ead0; height: 12px; margin: 2px 3px; border-radius: 4px; }
QScrollBar::handle:vertical { border: none; background: #d8d5c9; min-height: 32px; border-radius: 4px; }
QScrollBar::handle:horizontal { border: none; background: #d8d5c9; min-width: 32px; border-radius: 4px; }
QScrollBar::handle:hover { background: #c4bfad; }
QScrollBar::handle:pressed { background: #ada790; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; border: none; background: transparent; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QAbstractScrollArea::corner { background: transparent; }
""".replace("CHECK_ICON", (ROOT / "desktop" / "check-yellow.svg").as_posix()).replace("UP_ICON", (ROOT / "desktop" / "chevron-up.svg").as_posix()).replace("DOWN_ICON", (ROOT / "desktop" / "chevron-down.svg").as_posix())


DARK_SCROLL_QSS = """
QScrollBar:vertical, QScrollBar:horizontal { background: #3e3e3e; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #606060; }
QScrollBar::handle:hover { background: #797979; }
QScrollBar::handle:pressed { background: #929292; }
"""


class HintPopup(QLabel):
    """The app's own hover hint: light, rounded, no black system frame (macOS draws one around QToolTip)."""

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName("hint")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWordWrap(True)
        self.setContentsMargins(10, 7, 10, 7)
        self.setStyleSheet("QLabel#hint { color: #4a4232; font-size: 12px; background: transparent; }")

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#e3d5ae"), 1))
        painter.setBrush(QColor("#fffaee"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        painter.end()
        super().paintEvent(event)

    def show_at(self, text: str, pos: QPoint) -> None:
        self.setText(text)
        margins = self.contentsMargins()
        natural = max(self.fontMetrics().horizontalAdvance(line) for line in text.splitlines() or [""])
        width = min(420, natural + margins.left() + margins.right() + 4)  # one line when it fits, wrap beyond 420
        self.setFixedWidth(width)
        self.setFixedHeight(self.heightForWidth(width))
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(area.left() + 4, pos.x() + 12), area.right() - self.width() - 4)
        y = pos.y() + 22
        if y + self.height() > area.bottom() - 4:
            y = pos.y() - self.height() - 8
        self.move(x, y)
        self.show()
        self.raise_()


class HintFilter(QObject):
    """Routes every hover hint (widgets, list items, tabs) to HintPopup instead of the system tooltip."""

    def __init__(self, app) -> None:
        super().__init__(app)
        self.popup = HintPopup()
        self.owner: QWidget | None = None

    @staticmethod
    def _text_for(widget: QWidget, pos: QPoint) -> str:
        parent = widget.parentWidget()
        if isinstance(parent, QAbstractItemView) and widget is parent.viewport():
            index = parent.indexAt(pos)
            return str(index.data(Qt.ItemDataRole.ToolTipRole) or "") if index.isValid() else ""
        if isinstance(widget, QTabBar):
            tab = widget.tabAt(pos)
            return widget.tabToolTip(tab) if tab >= 0 else ""
        return widget.toolTip()

    def hide(self) -> None:
        self.popup.hide()
        self.owner = None

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        kind = event.type()
        if kind == QEvent.Type.ToolTip and isinstance(obj, QWidget):
            text = self._text_for(obj, event.pos())
            if not text:
                self.hide()
                return False if obj.toolTip() else True
            self.owner = obj
            self.popup.show_at(text, event.globalPos())
            return True
        if self.owner is not None and kind in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel,
                                               QEvent.Type.KeyPress, QEvent.Type.Hide, QEvent.Type.WindowDeactivate):
            if obj is self.owner or kind in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.WindowDeactivate):
                self.hide()
        elif self.owner is not None and kind == QEvent.Type.MouseMove and obj is self.owner:
            if self._text_for(obj, event.position().toPoint()) != self.popup.text():
                self.hide()  # moved to another list row or tab
        return False


class PopupAnimation(QObject):
    """One fade for menus and dialogs, including Qt-created combo popups."""
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if isinstance(obj, QWidget) and obj.isWindow() and obj.windowType() in (
            Qt.WindowType.Popup, Qt.WindowType.Dialog, Qt.WindowType.Sheet,
        ):
            if event.type() == QEvent.Type.Show:
                previous = getattr(obj, "popup_animation", None)
                if previous:
                    previous.stop()
                    previous.deleteLater()
                # Headless Qt cannot render window opacity.
                if QApplication.platformName() != "offscreen":
                    obj.setWindowOpacity(0.0)
                    animation = QPropertyAnimation(obj, b"windowOpacity", obj)
                    animation.setDuration(160)
                    animation.setStartValue(0.0)
                    animation.setEndValue(1.0)
                    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
                    obj.popup_animation = animation
                    animation.start()
            elif event.type() == QEvent.Type.Hide:
                animation = getattr(obj, "popup_animation", None)
                if animation:
                    animation.stop()
                    obj.setWindowOpacity(1.0)
        return super().eventFilter(obj, event)


class RoundedPopupBorder(QObject):
    """Paint a rounded surface on the translucent native popup window."""

    def __init__(self, popup) -> None:
        super().__init__(popup)
        popup.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        popup.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint)
        popup.setFrameShape(QFrame.Shape.NoFrame)
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        popup.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() != QEvent.Type.Paint:
            return False
        painter = QPainter(watched)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#d8c593"), 1))
        painter.setBrush(QColor("#fff8e7"))
        painter.drawRoundedRect(QRectF(watched.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        painter.end()
        return True


GROUP_HEADER_ROLE = Qt.ItemDataRole.UserRole + 1
# Hugging Face organization → model family shown as a group header.
MODEL_FAMILIES = {
    "deepseek-ai": "DeepSeek", "google": "Gemma · Google", "MiniMaxAI": "MiniMax", "mistralai": "Mistral",
    "moonshotai": "Kimi · Moonshot AI", "nvidia": "Nemotron · NVIDIA", "openai": "gpt-oss · OpenAI",
    "Qwen": "Qwen · Alibaba", "XiaomiMiMo": "MiMo · Xiaomi", "zai-org": "GLM · Z.ai",
}


def add_grouped_models(combo: QComboBox, models: list[dict]) -> None:
    """Add models under non-selectable family headers, families and models sorted by name."""
    families: dict[str, list[dict]] = {}
    for model in models:
        org = model["repo"].split("/")[0]
        families.setdefault(MODEL_FAMILIES.get(org, org), []).append(model)
    for family in sorted(families, key=str.casefold):
        combo.addItem(family.upper(), None)
        index = combo.count() - 1
        combo.setItemData(index, True, GROUP_HEADER_ROLE)
        item = combo.model().item(index)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
        for model in sorted(families[family], key=lambda m: m["name"].casefold()):
            combo.addItem(model["name"], model["id"])


POPUP_MARGIN = 7  # inner padding of every dropdown panel
DELETABLE_ROLE = Qt.ItemDataRole.UserRole + 41
HISTORY_DELETE_SIZE = 20  # hit area of the cross, px


def history_delete_rect(row_rect):
    """Square at the right edge of a history row, vertically centred."""
    size = HISTORY_DELETE_SIZE
    return QRect(row_rect.right() - size - 5, row_rect.top() + (row_rect.height() - size) // 2, size, size)


class HistoryDeleteDelegate(QStyledItemDelegate):
    """Draws a small cross on deletable rows; brighter halo when the pointer is on it."""

    def __init__(self, view: QListWidget) -> None:
        super().__init__(view)
        self.view = view
        self.icon = QIcon(str(ROOT / "desktop" / "close.svg"))

    def paint(self, painter, option, index) -> None:  # noqa: D401
        super().paint(painter, option, index)
        if not index.data(DELETABLE_ROLE):
            return
        rect = history_delete_rect(option.rect)
        cursor = self.view.viewport().mapFromGlobal(QCursor.pos())
        if rect.contains(cursor):
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(128, 106, 61, 40))
            painter.drawEllipse(rect)
            painter.restore()
        self.icon.paint(painter, rect.adjusted(5, 5, -5, -5))


class HistoryDeleteClicks(QObject):
    """Catches clicks on the cross before the row is chosen."""

    def __init__(self, view: QListWidget, on_delete) -> None:
        super().__init__(view)
        self.view, self.on_delete = view, on_delete
        view.viewport().installEventFilter(self)

    def _hit(self, event) -> int | None:
        index = self.view.indexAt(event.position().toPoint())
        if index.isValid() and index.data(DELETABLE_ROLE):
            if history_delete_rect(self.view.visualRect(index)).contains(event.position().toPoint()):
                return index.row()
        return None

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        kind = event.type()
        if kind == QEvent.Type.MouseMove:
            self.view.viewport().update()  # refresh the cross hover halo
            hit = self._hit(event) is not None
            self.view.viewport().setCursor(Qt.CursorShape.PointingHandCursor if hit else Qt.CursorShape.ArrowCursor)
        elif kind == QEvent.Type.MouseButtonPress:
            self._armed = self._hit(event)  # a deletion needs its own press on this very cross
            return self._armed is not None
        elif kind == QEvent.Type.MouseButtonDblClick:
            self._armed = None  # a double click never deletes twice
            return self._hit(event) is not None
        elif kind == QEvent.Type.MouseButtonRelease:
            row, armed, self._armed = self._hit(event), getattr(self, "_armed", None), None
            if row is not None and row == armed:
                self.on_delete(row)
            return row is not None
        return False


def title_font() -> QFont:
    """Header face; QSS #title must repeat family and size or the global QWidget rule wins."""
    font = QFont("Avenir Next")
    font.setStyleName("Medium")  # exact face; a QSS weight alone may resolve to another face
    font.setPixelSize(17)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.2)
    return font


class HistoryComboBox(QComboBox):
    """List-style dropdown; the look every app dropdown shares (see POPUP_* QSS)."""
    deleteRequested = pyqtSignal(int)  # combo row whose entry should be removed
    deletable = False  # show the delete cross on entries (history only)

    def showPopup(self) -> None:  # noqa: N802
        if old := getattr(self, "_popup_frame", None):
            old.close()
            old.deleteLater()
        popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._popup_frame = popup
        popup.rounded_border = RoundedPopupBorder(popup)
        popup.setObjectName("historyPopup")
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(POPUP_MARGIN, POPUP_MARGIN, POPUP_MARGIN, POPUP_MARGIN)
        listing = QListWidget(popup)
        listing.setObjectName("historyList")
        listing.setMinimumSize(1, 1)
        listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        use_step_scroll(listing)
        for index in range(self.count()):
            item = QListWidgetItem(self.itemText(index), listing)
            item.setToolTip(self.itemData(index, Qt.ItemDataRole.ToolTipRole) or self.itemText(index))
            if self.itemData(index, GROUP_HEADER_ROLE):
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setToolTip("")
                font = item.font()
                font.setPixelSize(10)  # same as Dropdown category headers (QLabel#catHeader)
                font.setWeight(QFont.Weight.Medium)
                font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
                item.setFont(font)
                item.setForeground(QColor("#74694f"))
            elif self.deletable and isinstance(self.itemData(index), int) and self.itemData(index) >= 0:
                item.setData(DELETABLE_ROLE, True)
        listing.setCurrentRow(self.currentIndex())
        listing.setMouseTracking(True)
        listing.setItemDelegate(HistoryDeleteDelegate(listing))
        popup.delete_clicks = HistoryDeleteClicks(listing, self.deleteRequested.emit)
        layout.addWidget(listing)

        def choose(item) -> None:
            if self.itemData(listing.row(item), GROUP_HEADER_ROLE):
                return
            self.setCurrentIndex(listing.row(item))
            self.hidePopup()

        listing.itemClicked.connect(choose)
        listing.itemActivated.connect(choose)
        available = self.screen().availableGeometry()
        width = min(max(240, self.width()), available.width() - 16)
        height = min(460, max(46, self.count() * 32 + 14), available.height() - 16)
        popup.resize(width, height)
        position = self.mapToGlobal(QPoint(0, self.height() + 4))
        x = max(available.left() + 8, min(position.x(), available.right() - width - 8))
        y = position.y()
        if y + height > available.bottom() - 8:
            y = max(available.top() + 8, self.mapToGlobal(QPoint(0, -height - 4)).y())
        popup.move(x, y)
        popup.show()
        listing.setFocus()
        if listing.currentItem():
            listing.scrollToItem(listing.currentItem())

    def hidePopup(self) -> None:  # noqa: N802
        if popup := getattr(self, "_popup_frame", None):
            popup.close()
        super().hidePopup()


class StepScroll(QObject):
    """Small wheel steps; nested result editors can target the enclosing page."""

    def __init__(self, area, scroll_target=None) -> None:
        super().__init__(area)
        self.scroll_target = scroll_target if scroll_target is not None else area
        self.pending = 0.0
        for surface in (area.viewport(), area.verticalScrollBar()):
            surface.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() != QEvent.Type.Wheel:
            return False
        if not event.pixelDelta().y() and not event.angleDelta().y():
            return False
        event.accept()
        if event.phase() in (Qt.ScrollPhase.ScrollMomentum, Qt.ScrollPhase.ScrollEnd):
            self.pending = 0.0
            return True
        if event.phase() == Qt.ScrollPhase.ScrollBegin:
            self.pending = 0.0
        pixels = event.pixelDelta().y()
        delta = pixels / 24 if pixels else event.angleDelta().y() / 120
        if self.pending * delta < 0:
            self.pending = 0.0
        self.pending += delta
        if abs(self.pending) >= 1:
            direction = 1 if self.pending > 0 else -1
            self.pending -= int(self.pending)
            bar = self.scroll_target.verticalScrollBar()
            # Text editors measure scrollbar positions in lines, scroll areas in pixels.
            step = 2 if isinstance(self.scroll_target, QPlainTextEdit) else 32
            bar.setValue(bar.value() - direction * step)
        return True


def use_step_scroll(area, scroll_target=None) -> None:
    area.step_scroll = StepScroll(area, scroll_target)


class ThoughtsEdit(QPlainTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setViewportMargins(0, 0, 52, 0)
        self.microphone_icon = QPushButton(self)
        self.microphone_icon.setIcon(QIcon(str(ROOT / "desktop" / "microphone.svg")))
        self.microphone_icon.setIconSize(QSize(18, 18))
        self.microphone_icon.setFixedSize(24, 24)
        self.microphone_icon.setAccessibleName("Microphone")
        self.microphone_icon.setToolTip("Dictate with Whisper · click to start or stop")
        self.microphone_icon.setCursor(Qt.CursorShape.PointingHandCursor)
        self.microphone_icon.clicked.connect(self._toggle_dictation)
        self.voice_process = None
        self.voice_state = "idle"
        self.voice_buffer = ""
        self.microphone_icon.setStyleSheet("background: transparent; border: none;")
        self.bottom_panel: QWidget | None = None

    def set_bottom_panel(self, panel: QWidget | None) -> None:
        """Dock a widget inside the field, under the text (the clarifying questions); None removes it."""
        if self.bottom_panel is not None:
            self.bottom_panel.hide()
            self.bottom_panel.deleteLater()
        self.bottom_panel = panel
        if panel is not None:
            panel.setParent(self)
            panel.show()
        self._place_bottom_panel()

    def _place_bottom_panel(self) -> None:
        panel = self.bottom_panel
        if panel is None:
            self.setViewportMargins(0, 0, 52, 0)
            return
        inset = 8
        width = max(0, self.width() - 2 * inset)
        layout = panel.layout()
        height = layout.totalHeightForWidth(width) if layout is not None and layout.hasHeightForWidth() else panel.sizeHint().height()
        height = min(height, max(0, self.height() - 90))  # the user's text keeps a few lines above the panel
        panel.setGeometry(inset, self.height() - height - inset, width, height)
        panel.raise_()
        self.setViewportMargins(0, 0, 52, height + inset)

    def _toggle_dictation(self) -> None:
        if self.voice_process is not None:
            if self.voice_state == "recording":
                self.voice_process.write(b"stop\n")
                self._voice_state("transcribing")
            return
        interpreter = ROOT / ".venv-whisper/bin/python"
        if not interpreter.exists():
            self.setToolTip("Whisper is not installed. See desktop/README.md.")
            return
        self.voice_process = QProcess(self)
        self.voice_process.setProgram(str(interpreter))
        self.voice_process.setArguments([str(ROOT / "desktop/voice_input.py")])
        self.voice_process.readyReadStandardOutput.connect(self._voice_output)
        self.voice_process.readyReadStandardError.connect(lambda: self.voice_process.readAllStandardError() if self.voice_process else None)
        self.voice_process.finished.connect(self._voice_finished)
        self.voice_process.errorOccurred.connect(self._voice_process_error)
        self.voice_buffer = ""
        self.setToolTip("")
        self._voice_state("starting")
        self.voice_process.start()

    def _voice_state(self, state: str) -> None:
        self.voice_state = state
        active = state != "idle"
        self.microphone_icon.setIcon(QIcon(str(ROOT / "desktop" / ("stop-recording.svg" if active else "microphone.svg"))))
        self.microphone_icon.setEnabled(state in ("idle", "recording"))
        self.microphone_icon.setToolTip({"idle": "Dictate with Whisper · click to start", "starting": "Opening microphone", "recording": "Recording · click to stop (5 minute maximum)", "transcribing": "Whisper is transcribing"}[state])

    def _voice_output(self) -> None:
        if self.voice_process is None:
            return
        self.voice_buffer += bytes(self.voice_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        while "\n" in self.voice_buffer:
            line, self.voice_buffer = self.voice_buffer.split("\n", 1)
            try:
                event = json.loads(line)
                state = event.get("state")
                if state in ("recording", "transcribing"):
                    self._voice_state(state)
                elif state == "done":
                    text = event.get("text", "")
                    if isinstance(text, str) and text.strip():
                        self.appendPlainText(text.strip())
                        self.ensureCursorVisible()
                    else:
                        self.setToolTip("No speech detected. Please try again.")
                elif state == "error":
                    self._voice_failure(str(event.get("message", "Voice input failed.")))
            except (ValueError, AttributeError):
                continue

    def _voice_process_error(self, error) -> None:
        self._voice_failure("Whisper could not run. Check microphone access in macOS Privacy & Security.")
        if error == QProcess.ProcessError.FailedToStart:
            self._voice_finished()

    def _voice_failure(self, message: str) -> None:
        self.setToolTip(message)
        hints = getattr(QApplication.instance(), "hint_filter", None)
        if hints is not None:  # the app's own hint, not the black-framed system tooltip
            hints.owner = self
            hints.popup.show_at(message, self.microphone_icon.mapToGlobal(QPoint(0, 4)))
        else:
            QToolTip.showText(self.microphone_icon.mapToGlobal(QPoint(0, 24)), message, self)

    def _voice_finished(self, code=0, status=None) -> None:
        process = self.voice_process
        self.voice_process = None
        self._voice_state("idle")
        if process:
            process.deleteLater()
        if code and not self.toolTip():
            self._voice_failure("Whisper stopped. Check microphone access in macOS Privacy & Security.")

    def stop_dictation(self) -> None:
        if self.voice_process:
            self.voice_process.kill()
            self.voice_process.waitForFinished(2000)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "microphone_icon"):
            self.microphone_icon.move(self.width() - self.verticalScrollBar().sizeHint().width() - 29, 7)
            self.microphone_icon.raise_()
        if getattr(self, "bottom_panel", None) is not None:
            self._place_bottom_panel()


def paint_dashed_scrollbar(bar: QScrollBar) -> None:
    """Draw any scroll bar as short ticks: dark on prompt blocks, warm brown elsewhere."""
    # Filled by hand: initStyleOption is protected for scroll bars that Qt created internally.
    option = QStyleOptionSlider()
    option.initFrom(bar)
    option.orientation = bar.orientation()
    option.minimum = bar.minimum()
    option.maximum = bar.maximum()
    option.sliderPosition = bar.sliderPosition()
    option.sliderValue = bar.value()
    option.singleStep = bar.singleStep()
    option.pageStep = bar.pageStep()
    option.upsideDown = bar.invertedAppearance()
    if bar.orientation() == Qt.Orientation.Horizontal:
        option.state |= QStyle.StateFlag.State_Horizontal
    thumb = bar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, option,
                                       QStyle.SubControl.SC_ScrollBarSlider, bar)
    painter = QPainter(bar)
    owner = bar.parentWidget()
    while owner and not isinstance(owner, QAbstractScrollArea):
        owner = owner.parentWidget()
    prompt = owner is not None and owner.objectName() == "prompt"
    if prompt:
        painter.fillRect(bar.rect(), QColor("#454545"))
    vertical = bar.orientation() == Qt.Orientation.Vertical
    length = bar.height() if vertical else bar.width()
    painter.setPen(Qt.PenStyle.NoPen)
    for position in range(5, length - 3, 10):
        active = (thumb.top() <= position <= thumb.bottom()) if vertical else (thumb.left() <= position <= thumb.right())
        painter.setBrush(QColor(("#c1bba9" if active else "#696969") if prompt else ("#806a3d" if active else "#b6a580")))
        if vertical:
            painter.drawRect((bar.width() - 6) // 2, position, 6, 2)
        else:
            painter.drawRect(position, (bar.height() - 6) // 2, 2, 6)
    painter.end()


class DashedScrollBar(QScrollBar):
    """Keep native scroll interaction; render the track and thumb as short ticks."""
    def paintEvent(self, event) -> None:  # noqa: N802
        paint_dashed_scrollbar(self)


class DashedScrollPainter(QObject):
    """App-wide: every other scroll bar (lists, menus, popups, dialogs) is painted as ticks too."""
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Paint and isinstance(obj, QScrollBar) and not isinstance(obj, DashedScrollBar):
            paint_dashed_scrollbar(obj)
            return True
        return False


class PromptEdit(QPlainTextEdit):
    """An editable prompt block with a fixed copy icon inside its upper-right corner."""

    def __init__(self, text: str, scroll_target, target: str | None = None) -> None:
        super().__init__()
        self.setObjectName("prompt")
        self.setPlainText(text)
        # Editable: copy and "open in chat" take the edited text; the block grows with it.
        self.setTabChangesFocus(True)
        self.textChanged.connect(lambda: self._refit())
        self.setVerticalScrollBar(DashedScrollBar(Qt.Orientation.Vertical, self))
        self.setHorizontalScrollBar(DashedScrollBar(Qt.Orientation.Horizontal, self))
        self.chat_target = target
        self.setViewportMargins(0, 0, 96 if target in CHAT_URLS else 64, 0)  # room for the icons, off the scroll ticks
        use_step_scroll(self, scroll_target)
        for scrollbar in (self.verticalScrollBar(), self.horizontalScrollBar()):
            scrollbar.setStyleSheet(DARK_SCROLL_QSS)
        self.copy_button = QPushButton(self)
        self.copy_button.setObjectName("copyPrompt")
        self.copy_button.setIcon(QIcon(str(ROOT / "desktop" / "copy.svg")))
        self.copy_button.setIconSize(QSize(17, 17))
        self.copy_button.setFixedSize(28, 28)
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.setAccessibleName("Copy prompt")
        self.copy_button.setToolTip("Copy prompt")
        self.copy_button.clicked.connect(self._copy)
        if target in CHAT_URLS:
            label = PROMPT_TARGETS[target][0]
            self.chat_button = QPushButton(self)
            self.chat_button.setObjectName("copyPrompt")
            self.chat_button.setIcon(QIcon(str(ROOT / "desktop/open-chat.svg")))
            self.chat_button.setIconSize(QSize(17, 17))
            self.chat_button.setFixedSize(28, 28)
            self.chat_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.chat_button.setAccessibleName(f"Open prompt in {label}")
            self.chat_button.setToolTip(f"Copy prompt and open {label} in your default browser")
            self.chat_button.clicked.connect(self._open_chat)
        self.copy_reset = QTimer(self)
        self.copy_reset.setSingleShot(True)
        self.copy_reset.timeout.connect(self._reset_copy)
        self._right_margin = 96 if target in CHAT_URLS else 64
        self._fit = False
        self._fit_width = -1
        self.spec: QLabel | None = None
        self.on_height = None  # set by the tabs around it, to follow the block's height
        self.on_edited = None  # set by the tabs: called with True/False when the text leaves/returns to the original
        self.original: str | None = None
        self.restore = QPushButton("Edited · Restore original", self)
        self.restore.setObjectName("restorePrompt")
        self.restore.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restore.setToolTip("Put back the prompt as the model wrote it")
        self.restore.clicked.connect(lambda: self.setPlainText(self.original or ""))
        self.restore.hide()
        self.textChanged.connect(self._update_edited)
        self._wrap_width = -1
        self.viewport().installEventFilter(self)

    FIT_MIN, FIT_MAX = 160, 460

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        # QPlainTextEdit re-wraps only on its own width change; the viewport also changes with
        # setViewportMargins and while the tab is hidden, which left text wrapped to a narrow column.
        if obj is self.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._rewrap)
        return super().eventFilter(obj, event)

    def _rewrap(self) -> None:
        width = self.viewport().width()
        if width > 0 and width != self._wrap_width:
            self._wrap_width = width
            self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            self._refit()

    def fit_to_content(self) -> None:
        """Height follows the text (between FIT_MIN and FIT_MAX); longer prompts scroll inside."""
        self._fit = True
        self._refit()

    def _refit(self) -> None:
        if not self._fit:
            return
        width = self.viewport().width()
        if width <= 0:
            return
        self._fit_width = width
        doc = QTextDocument()
        doc.setDefaultFont(self.font())
        doc.setDocumentMargin(self.document().documentMargin())
        doc.setPlainText(self.toPlainText())
        doc.setTextWidth(width)
        chrome = self.height() - self.viewport().height()  # frame, padding and the spec strip
        self.setFixedHeight(max(self.FIT_MIN, min(self.FIT_MAX, int(doc.size().height()) + chrome + 4)))
        if self.on_height is not None:
            self.on_height()

    def set_original(self, original: str) -> None:
        """The model's text; when the shown text differs, the block says so and offers to restore it."""
        self.original = original
        self.setViewportMargins(0, 0, self._right_margin, 30)  # room for the bottom strip
        self._update_edited()

    def is_edited(self) -> bool:
        return self.original is not None and self.toPlainText() != self.original

    def _update_edited(self) -> None:
        edited = self.is_edited()
        self.restore.setVisible(edited)
        self._place_overlays()
        if self.on_edited is not None:
            self.on_edited(edited)

    def set_spec(self, text: str, tooltip: str = "") -> None:
        """How to run this prompt, in a thin strip at the bottom of the block (not copied with the prompt)."""
        self.spec = QLabel(text, self)
        self.spec.setObjectName("promptSpec")
        self.spec.setToolTip(tooltip)
        self.setViewportMargins(0, 0, self._right_margin, 30)
        self._place_overlays()

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.toPlainText())
        self.copy_button.setIcon(QIcon(str(ROOT / "desktop" / "check.svg")))
        self.copy_button.setToolTip("Copied")
        self.copy_reset.start(1400)

    def _reset_copy(self) -> None:
        self.copy_button.setIcon(QIcon(str(ROOT / "desktop" / "copy.svg")))
        self.copy_button.setToolTip("Copy prompt")

    def _open_chat(self) -> None:
        text = self.toPlainText()
        if not text.strip():
            return
        self._copy()
        url = CHAT_URLS[self.chat_target]
        if self.chat_target == "chatgpt":
            url += "?" + urlencode({"q": text})
        opened = QDesktopServices.openUrl(QUrl(url))
        if not opened:
            self.chat_button.setToolTip("Could not open browser. Prompt copied. Paste it into the chat.")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_overlays()
        if self._fit and self.viewport().width() != self._fit_width:
            self._refit()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._place_overlays()  # the width may have changed while the tab was hidden

    def _place_overlays(self) -> None:
        if hasattr(self, "copy_button"):
            self.copy_button.move(self.width() - self.verticalScrollBar().sizeHint().width() - 42, 7)  # clear of the scroll ticks
            self.copy_button.raise_()
        if hasattr(self, "chat_button"):
            self.chat_button.move(self.width() - self.verticalScrollBar().sizeHint().width() - 74, 7)
            self.chat_button.raise_()
        if getattr(self, "restore", None) is not None and self.restore.isVisible():
            self.restore.adjustSize()
            self.restore.move(self.width() - self.restore.width() - 30, self.height() - self.restore.height() - 8)
        if getattr(self, "spec", None) is not None:
            self.spec.adjustSize()
            # A full-width strip in the block's colour: text scrolling under it stays hidden.
            self.spec.resize(self.width() - 32, self.spec.height())
            self.spec.move(16, self.height() - self.spec.height() - 9)
            self.spec.raise_()
        if getattr(self, "restore", None) is not None:
            self.restore.raise_()  # above the spec strip


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
    progress = pyqtSignal(int, str)
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
            errors = deque(maxlen=20)
            stderr = self.proc.stderr
            # Drain progress separately while communicate retains its timeout and stdout handling.
            self.proc.stderr = None

            def read_progress() -> None:
                try:
                    for line in stderr:
                        if line.startswith("PROMPTA_PROGRESS "):
                            try:
                                update = json.loads(line.removeprefix("PROMPTA_PROGRESS "))
                                percent, stage = update["percent"], update["stage"]
                                if type(percent) is int and 0 <= percent <= 100 and isinstance(stage, str):
                                    self.progress.emit(percent, stage[:160])
                            except (ValueError, KeyError, TypeError):
                                pass
                        else:
                            errors.append(line[-400:])
                finally:
                    stderr.close()

            reader = Thread(target=read_progress, daemon=True)
            reader.start()
            try:
                out, err = self.proc.communicate(json.dumps({**self.payload, "reportProgress": True}), timeout=900)
            finally:
                if self.proc.poll() is None:
                    self.proc.kill()
                    self.proc.communicate()
                reader.join(timeout=2)
            err = "".join(errors) or err
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

    def __init__(self, key: str, name: str, hint: str = "", sources: list | None = None) -> None:
        super().__init__()
        self.key = key
        self.setObjectName("techItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)  # same as a list-row padding
        layout.setSpacing(1)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel(name)
        title.setObjectName("techName")
        title.setWordWrap(True)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(title, 1, Qt.AlignmentFlag.AlignVCenter)
        self.sources = [source for source in (sources or []) if self._valid_source(source)]
        if self.sources:
            article = QPushButton()
            article.setObjectName("articleLink")
            article.setIcon(QIcon(str(ROOT / "desktop" / "external-link.svg")))
            article.setIconSize(QSize(14, 14))
            article.setFixedSize(20, 20)
            article.setAccessibleName(f"Sources for {name}")
            article.setToolTip("Read the source article\n" + "\n".join(s['title'] for s in self.sources))
            article.clicked.connect(lambda: self._show_sources(name))
            title_row.addWidget(article, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(title_row)

        if hint:
            note = QLabel(hint)
            note.setObjectName("techHint")
            note.setWordWrap(True)
            layout.addWidget(note)
            layout.addStretch(1)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.key)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    @staticmethod
    def _valid_source(source: object) -> bool:
        if not isinstance(source, dict) or not isinstance(source.get("url"), str):
            return False
        url = urlparse(source["url"])
        return (url.scheme == "https" and url.hostname in ("archive.org", "arxiv.org")
                and not url.username and not url.password and bool(source.get("title")))

    def _show_sources(self, name: str) -> None:
        dialog = QDialog(QApplication.activeWindow())
        dialog.setWindowTitle(f"{name} — sources")
        dialog.setMinimumWidth(560)  # room for the source descriptions
        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(14)
        # Descriptions make the list long: it scrolls, the Done button stays in view.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(18)
        scroll.setWidget(holder)
        use_step_scroll(scroll)
        outer.addWidget(scroll, 1)
        for source in self.sources:
            block = QVBoxLayout()
            block.setSpacing(4)
            label = QLabel(f'<a href="{escape(source["url"], quote=True)}">{escape(source["title"])}</a><br>'
                           f'<span style="color: #7b8799">{escape(source.get("reference", ""))}</span>')
            label.setWordWrap(True)
            label.setOpenExternalLinks(True)
            block.addWidget(label)
            if source.get("summary"):  # 3-4 sentences: the abstract's claim, or the cited passage
                about = QLabel(source["summary"])
                about.setObjectName("sourceSummary")
                about.setWordWrap(True)
                about.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                block.addWidget(about)
            layout.addLayout(block)
        close = QPushButton("Done")
        close.setObjectName("ghost")
        close.clicked.connect(dialog.accept)
        outer.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        dialog.resize(600, min(640, holder.sizeHint().height() + 110))
        dialog.exec()


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
        search_placeholder: str = "Filter",
    ) -> None:
        super().__init__(placeholder)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("picker")
        self._placeholder = placeholder
        self._items: list[dict] = []
        self._current = ""
        self._columns = columns
        self._searchable = searchable
        self._popup_width = popup_width
        self._search_placeholder = search_placeholder
        self._popup: QFrame | None = None
        self._multi = False
        self._selected: list[str] = []
        self._item_widgets: dict[str, TechniqueItem] = {}
        self.clicked.connect(self._open)

    # ── данные ───────────────────────────────────────────────────
    def set_multi(self, multi: bool) -> None:
        """Multi mode: clicks toggle items and the panel stays open. Items with status
        "procedure" are exclusive: they cannot be combined with anything else."""
        self._multi = multi
        self._selected = [self._current] if multi and self._current else []

    def set_items(self, items: list[dict], keep: str = "") -> None:
        self._items = items
        if self._multi:
            known = {item.get("key") for item in items}
            self.set_current_keys([key for key in self._selected if key in known])
            return
        want = keep or self._current
        if want and any(item.get("key") == want for item in items):
            self.set_current(want)

    def current_key(self) -> str:
        return self._current

    def current_keys(self) -> list[str]:
        if self._multi:
            return list(self._selected)
        return [self._current] if self._current else []

    def _label(self, key: str) -> str:
        item = next((i for i in self._items if i.get("key") == key), None)
        return (item.get("label") or item.get("name") or key) if item else key

    def set_current(self, key: str, emit: bool = False) -> None:
        if self._multi:
            self.set_current_keys([key] if key else [], emit)
            return
        self._current = key
        self.setText(self._label(key) if key else self._placeholder)
        if emit:
            self.changed.emit(key)

    def set_current_keys(self, keys: list[str], emit: bool = False) -> None:
        self._selected = list(dict.fromkeys(k for k in keys if k))
        self._current = self._selected[0] if self._selected else ""
        if not self._selected:
            text = self._placeholder
        elif len(self._selected) == 1:
            text = self._label(self._current)
        else:
            text = f"{len(self._selected)} techniques: " + ", ".join(self._label(k) for k in self._selected)
        self.setText(self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(120, self.width() - 28)))
        self.setToolTip("\n".join(self._label(k) for k in self._selected))
        for key, widget in self._item_widgets.items():
            widget.set_selected(key in self._selected)
        if self._popup is not None and hasattr(self, "_selection_label"):
            self._selection_label.setText(f"{len(self._selected)} selected" if self._selected else "Click techniques to select")
            self._update_select_all()
        if emit:
            self.changed.emit(self._current)

    def _is_procedure(self, key: str) -> bool:
        return any(i.get("key") == key and i.get("status") == "procedure" for i in self._items)

    def _selectable_keys(self) -> list[str]:
        """Techniques that "Select all" covers: shown by the current filter, procedures excluded."""
        return [key for key, widget in self._item_widgets.items() if not widget.isHidden() and not self._is_procedure(key)]

    def _all_selected(self) -> bool:
        keys = self._selectable_keys()
        return bool(keys) and all(key in self._selected for key in keys)

    def _update_select_all(self) -> None:
        if button := getattr(self, "_select_all_button", None):
            button.setText("Deselect all" if self._all_selected() else "Select all")
            button.setEnabled(bool(self._selectable_keys()))

    def _toggle_select_all(self) -> None:
        keys = self._selectable_keys()
        if self._all_selected():
            remaining = [k for k in self._selected if k not in keys]
        else:
            remaining = [k for k in self._selected if not self._is_procedure(k)] + [k for k in keys if k not in self._selected]
        self.set_current_keys(remaining, emit=True)

    def _toggle(self, key: str) -> None:
        if key in self._selected:
            keys = [k for k in self._selected if k != key]
        elif self._is_procedure(key):
            keys = [key]
        else:
            keys = [k for k in self._selected if not self._is_procedure(k)] + [key]
        self.set_current_keys(keys, emit=True)

    # ── панель ───────────────────────────────────────────────────
    def _open(self) -> None:
        popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        popup.rounded_border = RoundedPopupBorder(popup)
        popup.setObjectName("techniquePopup")
        self._popup = popup

        outer = QVBoxLayout(popup)
        outer.setContentsMargins(POPUP_MARGIN, POPUP_MARGIN, POPUP_MARGIN, POPUP_MARGIN)
        outer.setSpacing(8)

        search: QLineEdit | None = None
        if self._searchable:
            search = QLineEdit()
            search.setPlaceholderText(self._search_placeholder)
            search.setClearButtonEnabled(True)
            outer.addWidget(search)

        scroll = QScrollArea(popup)
        use_step_scroll(scroll)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setObjectName("scrollContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)

        entries: list[tuple[TechniqueItem, str]] = []
        headers: list[tuple[QLabel, list[TechniqueItem]]] = []
        self._item_widgets = {}

        grouped: dict[str, list[dict]] = {}
        for item in self._items:
            grouped.setdefault(item.get("category") or "", []).append(item)

        multi_group = any(key for key in grouped)

        for category, items in grouped.items():
            if multi_group:
                header = QLabel(CATEGORY_LABELS.get(category, category).upper() if category else "GENERAL")
                header.setObjectName("catHeader")
                header.setContentsMargins(10, 6, 10, 2)
                body.addWidget(header)

            grid = QGridLayout()
            grid.setHorizontalSpacing(4)
            grid.setVerticalSpacing(1)
            grid_items: list[TechniqueItem] = []
            for index, item in enumerate(items):
                label = item.get("label") or item.get("name") or item["key"]
                widget = TechniqueItem(item["key"], label, item.get("hint", ""), item.get("sources"))
                widget.clicked.connect(self._toggle if self._multi else self._choose)
                self._item_widgets[item["key"]] = widget
                widget.set_selected(item["key"] in self.current_keys())  # single mode marks the current one too
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

        if self._multi:
            footer = QHBoxLayout()
            self._selection_label = QLabel()
            self._selection_label.setObjectName("muted")
            footer.addWidget(self._selection_label, 1)
            self._select_all_button = QPushButton("Select all")
            self._select_all_button.setObjectName("ghost")
            self._select_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._select_all_button.setToolTip("Select every technique shown (procedures excluded); click again to deselect")
            self._select_all_button.clicked.connect(self._toggle_select_all)
            footer.addWidget(self._select_all_button)
            clear = QPushButton("Clear")
            clear.setObjectName("ghost")
            clear.setCursor(Qt.CursorShape.PointingHandCursor)
            clear.clicked.connect(lambda: self.set_current_keys([], emit=True))
            footer.addWidget(clear)
            done = QPushButton("Done")
            done.setObjectName("primary")
            done.setCursor(Qt.CursorShape.PointingHandCursor)
            done.clicked.connect(popup.close)
            footer.addWidget(done)
            outer.addLayout(footer)
            self.set_current_keys(self._selected)

        def apply_filter(text: str) -> None:
            needle = text.strip().lower()
            for widget, haystack in entries:
                widget.setVisible(needle in haystack)
            for header, grid_items in headers:
                header.setVisible(any(not w.isHidden() for w in grid_items))
            self._update_select_all()

        if search is not None:
            search.textChanged.connect(apply_filter)

        # Height follows the content: an empty full-screen panel looks sloppy.
        width = min(self._popup_width, self.screen().availableGeometry().width() - 24)
        body.activate()
        height = content.heightForWidth(width - 2 * POPUP_MARGIN) if content.hasHeightForWidth() else -1
        height = max(height, content.sizeHint().height()) + 2 * POPUP_MARGIN + 2
        if self._searchable:
            height += search.sizeHint().height() + outer.spacing()
        if self._multi:
            height += 44
        available = self.screen().availableGeometry()
        popup.resize(min(self._popup_width, available.width() - 24), min(560, max(120, height), available.height() - 24))
        position = self.mapToGlobal(QPoint(0, self.height() + 6))
        if position.y() + popup.height() > available.bottom() - 12:
            above = self.mapToGlobal(QPoint(0, -popup.height() - 6)).y()
            position.setY(max(available.top() + 12, above))
        position.setX(max(available.left() + 12, min(position.x(), available.right() - popup.width() - 12)))
        popup.move(position)
        popup.show()
        if search is not None:
            search.setFocus()

    def _choose(self, key: str) -> None:
        self.set_current(key, emit=True)
        if self._popup is not None:
            self._popup.close()


class BackgroundWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.image = QPixmap(str(ROOT / "desktop/background.png"))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        if not self.image.isNull():
            image = self.image.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                      Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap((self.width() - image.width()) // 2,
                               (self.height() - image.height()) // 2, image)
            # Cream veil over the photo: higher alpha = fainter photo.
            painter.fillRect(self.rect(), QColor(255, 248, 222, 228))
        else:
            painter.fillRect(self.rect(), QColor("#f5f6f8"))


class Card(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")

    def vbox(self) -> QVBoxLayout:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(10)
        return layout


class VariantSelector(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("variantCount")
        self.setAccessibleName("Number of prompt variants")
        self.setFixedSize(184, 36)
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(3)
        self.buttons = QButtonGroup(self)
        self.buttons.setExclusive(True)
        for count in range(1, 6):
            button = QPushButton(str(count))
            button.setObjectName("variantOption")
            button.setFixedHeight(28)
            button.setCheckable(True)
            button.setAccessibleName(f"{count} prompt variant{'s' if count > 1 else ''}")
            button.setToolTip(button.accessibleName())
            self.buttons.addButton(button, count)
            row.addWidget(button, 1)
        self.setValue(1)

    def value(self) -> int:
        return self.buttons.checkedId()

    def setValue(self, value: int) -> None:
        self.buttons.button(max(1, min(5, value))).setChecked(True)


class MainWindow(QMainWindow):
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
        header.setSpacing(20)
        title = QLabel("Prompta")
        title.setObjectName("title")
        title.setFont(title_font())
        header.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
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
        QApplication.instance().aboutToQuit.connect(self.thoughts.stop_dictation)
        self.thoughts.setAccessibleName("Thoughts")
        use_step_scroll(self.thoughts)
        self.thoughts.setPlaceholderText(
            "Describe what you need"
        )
        thoughts_palette = self.thoughts.palette()
        thoughts_palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9a8c6b"))
        self.thoughts.setPalette(thoughts_palette)
        self.thoughts.setMinimumHeight(150)
        box.addWidget(self.thoughts, 1)

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
        key_hint = QLabel("Required for OpenAI and Gemini. Not needed for Ollama.\nYour key stays in memory and is not saved to disk.")
        key_hint.setObjectName("muted")
        key_hint.setWordWrap(True)
        settings_layout.addWidget(key_hint)
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
        target_grid.addWidget(self.prompt_model, 2, 0, 1, 2)
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
        self.run_button = QPushButton("Build prompt")
        self.run_button.setObjectName("buildPrompt")
        self.run_button.setFixedHeight(42)
        self.run_button.clicked.connect(self.run_pipeline)
        actions.addWidget(self.run_button, 1)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("ghost")
        self.cancel_button.setFixedSize(80, 42)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_run)
        actions.addWidget(self.cancel_button)
        box.addLayout(actions)
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

    def _on_provider_changed(self, provider: str) -> None:
        if provider == "ollama":
            self.load_models()
        else:
            self.models_hint.setText("Enter the model name for your cloud provider")

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
        self.thoughts.set_bottom_panel(None)  # the questions belong to the result being replaced

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
        self.run_button.setEnabled(not running)
        self.cancel_button.setEnabled(False)
        self.status.setText("Thoughts → brief → technique → ready-to-use prompt")
        self.thoughts.setFocus()

    def cancel_run(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.status.setText("Cancelling")

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

        technique_keys = self.technique.current_keys()
        payload = {
            "thoughts": thoughts,
            "provider": provider,
            "model": model,
            "apiKey": api_key,
            "claudeOnly": self.claude_only.isChecked(),
            "chatgptOnly": self.chatgpt_only.isChecked(),
            "geminiOnly": self.gemini_only.isChecked(),
            "grokOnly": self.grok_only.isChecked(),
            "variants": self.variants.value(),
            "oneShot": bool(getattr(self, "one_shot", None) and self.one_shot.isChecked()),
        }
        if self.openModel_only.isChecked():
            payload["openModel"] = self.prompt_model.currentData()
        if technique_keys and self._selected_target() is None:
            if len(technique_keys) == 1:
                payload["manualTechnique"] = technique_keys[0]
            else:
                payload["manualTechniques"] = technique_keys

        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.generation_progress.setValue(0)
        self.generation_progress.show()
        selected = self._selected_target()
        target_label = self.prompt_model.currentText() if selected == "openModel" else PROMPT_TARGETS[selected][0] if selected else ""
        self.status.setText(f"Building {target_label} prompt from official sources" if selected else "Brief → technique selection → synthesis")

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
            self.run_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            return
        if data.get("ok"):
            self.generation_progress.setValue(100)
            self.status.setText("Done")
        else:
            self.generation_progress.hide()
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

    def render_manual(self, manual: dict) -> None:
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
    def render(self, result: dict) -> None:
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
                parsed = urlparse(url)
                if parsed.scheme != "https" or parsed.hostname not in PROMPT_TARGETS[source_target][1] or parsed.username or parsed.password:
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
QToolButton#disclosure[field="true"] { color: #74694f; font-size: 10px; font-weight: 500; letter-spacing: 1px; padding: 2px 0; }
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
        self.run_button.setText("Build prompt   ⌘↵")
        self.run_button.setToolTip("⌘↵ builds the prompt")
        self.cancel_button.setText("Stop")
        self.history_search.setPlaceholderText("Search history")
        self.status.setText("")
        self._setup_history_search()
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

    # ── history search: live results under the search field ───────
    def _setup_history_search(self) -> None:
        self.history_matches = QStandardItemModel(self)
        self.history_completer = QCompleter(self.history_matches, self)
        self.history_completer.setWidget(self.history_search)
        # The model is filtered here (full text of request, topic and prompts), not by the completer.
        self.history_completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.history_completer.setMaxVisibleItems(9)
        popup = self.history_completer.popup()
        popup.setObjectName("historySuggestions")
        popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_completer.activated[QModelIndex].connect(self._open_history_match)
        self.history_search.textEdited.connect(self._show_history_matches)
        self.history_search.returnPressed.connect(self._open_first_history_match)

    def _history_match_indexes(self, text: str) -> list[int]:
        needle = text.strip().casefold()
        if not needle:
            return []
        found = []
        for index, entry in enumerate(self._history_items):
            haystack = entry['thoughts'] + ' ' + entry['label'] + ' ' + json.dumps(entry['payload'], ensure_ascii=False)
            if needle in haystack.casefold():
                found.append(index)
        return found[::-1]  # newest first

    def _show_history_matches(self, text: str) -> None:
        self.history_matches.clear()
        indexes = self._history_match_indexes(text)
        for index in indexes:
            entry = self._history_items[index]
            label = history_topic(entry['thoughts'], entry['payload'], entry['label'])
            item = QStandardItem(f"{label}  ·  {entry['created_at'][:10]}")
            item.setData(index, Qt.ItemDataRole.UserRole)
            item.setToolTip(entry['thoughts'])
            self.history_matches.appendRow(item)
        if not text.strip():
            self.history_completer.popup().hide()
            return
        if not indexes:
            item = QStandardItem("No matches")
            item.setEnabled(False)
            self.history_matches.appendRow(item)
        self.history_completer.complete(self.history_search.rect().adjusted(0, 4, 0, 4))

    def _open_history_match(self, index: QModelIndex) -> None:
        item_index = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(item_index, int):
            self._open_history_index(item_index)

    def _open_first_history_match(self) -> None:
        indexes = self._history_match_indexes(self.history_search.text())
        if indexes and not self.history_completer.popup().isVisible():
            self._open_history_index(indexes[0])

    def _open_history_index(self, item_index: int) -> None:
        self.history_completer.popup().hide()
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
        for key, _ in TARGET_SEGMENTS[1:]:
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
        for index, (key, label) in enumerate(TARGET_SEGMENTS):
            button = QPushButton(label)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("first", index == 0)
            button.setProperty("last", index == len(TARGET_SEGMENTS) - 1)
            button.setProperty("target", key)
            button.setAccessibleName(f"Target: {label}")
            button.setToolTip("Use the prompting-technique catalog" if key == GENERAL_TARGET
                              else f"Use saved official {label} guidance only. Your generator model stays the same.")
            self.segments.addButton(button)
            row_layout.addWidget(button, 1)
        self.segments.buttonClicked.connect(self._on_segment_clicked)
        grid.addWidget(self._mini_label("Target model"), 0, 0, 1, 2)
        grid.addWidget(row, 1, 0, 1, 2)
        self.prompt_model.setItemText(0, "— or open-weight model —")
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
        # Full-width segmented switch under the technique picker; no label row (the tooltip explains it).
        variants_label.hide()
        variants_label.deleteLater()
        self.advanced.body_layout.addSpacing(8)
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
        # Off by default: an invented example at the top tends to bury the real task.
        self.one_shot = QCheckBox("Add a sample answer to the prompt")
        self.one_shot.setObjectName("oneShot")
        self.one_shot.setToolTip(
            "The prompt opens with one made-up input and its ideal answer, labelled as an example; "
            "your real task follows. Skipped if the technique already has examples.")
        card_layout.insertWidget(index + 1, self.one_shot)
        hint = muted_label("Shows the model the exact format to copy. Helps with tables, JSON, fixed templates; "
                           "skip for open-ended or creative tasks.", "oneShotHint")
        hint.setContentsMargins(22, 0, 0, 0)  # under the checkbox text, not the box
        card_layout.insertWidget(index + 2, hint)
        self.technique.changed.connect(self._update_advanced_title)
        self.variants.buttons.idClicked.connect(self._update_advanced_title)
        self.advanced.button.toggled.connect(self._update_advanced_title)
        self.technique_label.hide()  # its count moves into the Advanced title
        # One control height for fields and segmented tracks so rows line up.
        for widget in (self.history_search, self.history, self.prompt_model, self.technique, self.target_track, self.variants):
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

    def _on_segment_clicked(self, button: QPushButton) -> None:
        key = button.property("target")
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
        # An open-weight model lights no segment: the dropdown below shows the choice.
        self.segments.setExclusive(False)
        for button in self.segments.buttons():
            key = button.property("target")
            button.setChecked(key == selected or (key == GENERAL_TARGET and selected is None))
        self.segments.setExclusive(True)
        if hasattr(self, "advanced"):
            self._update_advanced_title()

    def _update_advanced_title(self, *_: object) -> None:
        extra = []
        keys = self.technique.current_keys()
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
        tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        zero = editor(zero_shot)
        zero.setAccessibleName("Zero-shot baseline prompt")
        tabs.addTab(zero, "Zero-shot" if named_tabs else "Variant 0")
        tabs.setTabToolTip(0, "Zero-shot: the task stated directly, without a prompting technique")
        self.prompt_edit = editor(prompts[0][1])
        tabs.addTab(self.prompt_edit, prompts[0][0] if named_tabs else "Variant 1")
        for index, (name, prompt) in enumerate(prompts[1:], 2):
            tabs.addTab(editor(prompt), name if named_tabs else f"Variant {index}")
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
        assumptions = [a for a in brief.get("assumptions") or [] if isinstance(a, str) and a.strip()]
        if assumptions:
            text = assumptions[0] if len(assumptions) == 1 else "\n".join(f"• {a}" for a in assumptions)
            box.addWidget(keyed_label("Assumed", text, stacked=len(assumptions) > 1))
        row = FlowLayout()
        meta = muted_label(f"{brief['task_type']} · {brief['stakes']} stakes · {brief['language']}", "briefMeta")
        meta.setWordWrap(False)  # one chip-like run in the flow, not a wrapped column
        row.addWidget(meta)
        box.addSpacing(2)
        box.addLayout(row)
        return box, row

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
            parsed = urlparse(url)
            safe = (parsed.scheme == "https" and parsed.hostname in PROMPT_TARGETS[target][1]
                    and not parsed.username and not parsed.password)
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

    def _questions_block(self, brief: dict | None) -> QWidget | None:
        """What is missing: each question with the assumption used until it is answered; answers go into the thoughts and rebuild."""
        questions = self._brief_questions(brief)
        if not questions:
            return None
        box = QFrame()
        box.setObjectName("questionsCard")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(0)  # explicit rhythm: a question sits with its field, groups stand apart
        title = QLabel("Answer to sharpen the prompt")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        answers: list[tuple[str, QLineEdit]] = []
        for question, default in questions:
            layout.addSpacing(12)
            layout.addWidget(muted_label(question, "question"))
            layout.addSpacing(5)
            answer = QLineEdit()
            answer.setPlaceholderText(f"Assumed: {default}" if default else "Your answer (optional)")
            if default:
                answer.setToolTip("Leave empty to keep this assumption")
            answer.setAccessibleName(question)
            layout.addWidget(answer)
            answers.append((question, answer))
        rebuild = QPushButton("Rebuild with answers")
        rebuild.setObjectName("rebuild")
        rebuild.setCursor(Qt.CursorShape.PointingHandCursor)
        rebuild.setEnabled(False)  # nothing to rebuild with until something is typed
        ru = (brief or {}).get("language") == "ru"

        def sync() -> None:
            rebuild.setEnabled(any(a.text().strip() for _, a in answers))

        def apply() -> None:
            given = [(q, a.text().strip()) for q, a in answers if a.text().strip()]
            if not given:
                self.status.setText("Answer at least one question")
                return
            head = "Уточнения" if ru else "Clarifications"
            extra = "\n".join(f"- {q} — {a}" for q, a in given)
            self.thoughts.setPlainText(f"{self.thoughts.toPlainText().rstrip()}\n\n{head}:\n{extra}")
            self.run_pipeline()
        rebuild.clicked.connect(apply)
        for _, answer in answers:
            answer.textChanged.connect(sync)
            answer.returnPressed.connect(apply)
        layout.addSpacing(16)
        layout.addWidget(rebuild, 0, Qt.AlignmentFlag.AlignLeft)
        self.question_answers = answers
        self.rebuild_button = rebuild
        return box

    def render(self, result: dict) -> None:
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
        layout.addSpacing(10)
        prompts = [(choice["name"], synthesis["prompt"])] + [(a["choice"]["name"], a["synthesis"]["prompt"]) for a in alternatives]
        tabs = self._prompt_view(prompts, source_target, self._zero_shot_text(result))
        self._mark_originals(tabs, result)
        layout.addWidget(tabs)
        layout.addSpacing(BLOCK_GAP)  # air between the prompt and what follows
        self.thoughts.set_bottom_panel(self._questions_block(brief))  # asked where the request is written
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

    def render_manual(self, manual: dict) -> None:
        self._clear_output()
        variants = manual.get("variants") or [
            {"technique": manual["technique"], "prompt": manual["prompt"], "config": manual["config"], "source_ref": manual["source_ref"]}
        ]
        names = [v["technique"]["name"] for v in variants]
        self.output_layout.addWidget(self._heading(manual.get("topic") or names[0], "goal"))
        metas = ["Zero-shot · baseline without a technique"] + [f"{name} · chosen manually" for name in names]
        meta_label = muted_label(metas[1], "meta")
        self.output_layout.addWidget(meta_label)
        self.output_layout.addSpacing(10)
        tabs = self._prompt_view([(v["technique"]["name"], v["prompt"]) for v in variants], None, self._zero_shot_text(manual), named_tabs=True)
        self._mark_originals(tabs, manual)
        self.output_layout.addWidget(tabs)
        self.output_layout.addSpacing(BLOCK_GAP)
        brief = manual.get("brief") if isinstance(manual.get("brief"), dict) else None
        self.thoughts.set_bottom_panel(self._questions_block(brief))
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
QLineEdit:hover, QComboBox:hover, QPushButton#picker:hover { background: rgba(255, 255, 255, 160); border-color: transparent; }
QLineEdit:focus, QComboBox:focus, QPushButton#picker:focus { background: rgba(255, 255, 255, 185); border: 1px solid #e1b72c; }
QPushButton#picker:pressed { background: rgba(255, 255, 255, 200); }
QPushButton#picker:disabled { background: rgba(255, 255, 255, 60); color: #b0a78e; border-color: transparent; }

QWidget#segmentTrack, QFrame#segmentTrack { background: rgba(120, 96, 30, 26); border: none; border-radius: 8px; }
QPushButton#segment, QPushButton#segment[first="true"], QPushButton#segment[last="true"] {
  background: transparent; border: none; border-radius: 6px; color: #6b6047; font-size: 12px; padding: 0 4px; }
QPushButton#segment:hover { background: rgba(255, 255, 255, 110); }
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
QListView#historySuggestions { background: #fffaee; border: 1px solid rgba(120, 96, 30, 40); border-radius: 12px; }
QLabel#chip { background: rgba(120, 96, 30, 20); border: none; border-radius: 7px; color: #5f5440; }
QLabel#warn { background: rgba(244, 170, 40, 36); border: none; border-radius: 10px; }
QLabel#error { background: rgba(220, 80, 70, 30); border: none; border-radius: 10px; }
QCheckBox::indicator { border: none; background: rgba(120, 96, 30, 30); border-radius: 4px; }
QPushButton#rebuild { background: #f4ca38; color: #352b10; border: none; border-radius: 8px; padding: 6px 14px; font-weight: 500; }
QPushButton#rebuild:hover { background: #f7d65e; }
QPushButton#rebuild:disabled { background: rgba(244, 202, 56, 90); color: #8f7f52; }
QFrame#questionsCard { background: rgba(255, 248, 225, 235); border: none; border-radius: 10px; }
QFrame#questionsCard QLineEdit { background: rgba(255, 255, 255, 185); }
QLabel#cardTitle { color: #3a3121; font-size: 13px; font-weight: 600; }
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
