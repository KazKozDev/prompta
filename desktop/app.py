#!/usr/bin/env python3
"""Prompta — нативное приложение для macOS.

UI на PyQt6, логика — существующий TS-пайплайн через мост desktop/bridge.ts.
История хранится локально; ключи API на диск не записываются.
"""

from __future__ import annotations

import json
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
except ImportError:
    from history import HistoryStore, history_topic
    from library import LibraryWidget

from PyQt6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, QUrl, QProcess, QThread, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPalette, QPen, QFont, QGuiApplication, QIcon, QPixmap, QKeySequence, QShortcut, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
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
    QStyleOptionSlider,
    QSplitter,
    QTabWidget,
    QToolButton,
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
QLabel#title { font-size: 17px; letter-spacing: -0.3px; font-weight: 600; color: #202632; }
QLabel#subtitle { color: #74694f; font-size: 13px; }
QLabel#section { font-weight: 600; color: #332e24; font-size: 13px; }
QLabel#fieldLabel { color: #74694f; font-size: 10px; font-weight: 500; letter-spacing: 1px; }
QLabel#muted { color: #665d49; font-size: 12px; }
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
QListWidget#historyList::item { padding: 7px 10px; border: none; border-radius: 5px; }
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


class HistoryComboBox(QComboBox):
    def showPopup(self) -> None:  # noqa: N802
        if old := getattr(self, "_popup_frame", None):
            old.close()
            old.deleteLater()
        popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._popup_frame = popup
        popup.rounded_border = RoundedPopupBorder(popup)
        popup.setObjectName("historyPopup")
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(7, 7, 7, 7)
        listing = QListWidget(popup)
        listing.setObjectName("historyList")
        listing.setMinimumSize(1, 1)
        listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        use_step_scroll(listing)
        for index in range(self.count()):
            item = QListWidgetItem(self.itemText(index), listing)
            item.setToolTip(self.itemData(index, Qt.ItemDataRole.ToolTipRole) or self.itemText(index))
        listing.setCurrentRow(self.currentIndex())
        layout.addWidget(listing)

        def choose(item) -> None:
            self.setCurrentIndex(listing.row(item))
            self.hidePopup()

        listing.itemClicked.connect(choose)
        listing.itemActivated.connect(choose)
        available = self.screen().availableGeometry()
        width = min(max(240, self.width()), available.width() - 16)
        height = min(320, max(46, self.count() * 32 + 14), available.height() - 16)
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
        self.microphone_icon.setToolTip({"idle": "Dictate with Whisper · click to start", "starting": "Opening microphone…", "recording": "Recording · click to stop (5 minute maximum)", "transcribing": "Whisper is transcribing…"}[state])

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
        from PyQt6.QtWidgets import QToolTip
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


class DashedScrollBar(QScrollBar):
    """Keep native scroll interaction; render the track and thumb as short ticks."""
    def paintEvent(self, event) -> None:  # noqa: N802
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        thumb = self.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, option,
                                           QStyle.SubControl.SC_ScrollBarSlider, self)
        painter = QPainter(self)
        owner = self.parentWidget()
        while owner and not isinstance(owner, (QPlainTextEdit, QScrollArea)):
            owner = owner.parentWidget()
        prompt = owner is not None and owner.objectName() == "prompt"
        if prompt:
            painter.fillRect(self.rect(), QColor("#454545"))
        vertical = self.orientation() == Qt.Orientation.Vertical
        length = self.height() if vertical else self.width()
        for position in range(5, length - 3, 10):
            active = (thumb.top() <= position <= thumb.bottom()) if vertical else (thumb.left() <= position <= thumb.right())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(("#c1bba9" if active else "#696969") if prompt else ("#806a3d" if active else "#b6a580")))
            if vertical:
                painter.drawRect((self.width() - 6) // 2, position, 6, 2)
            else:
                painter.drawRect(position, (self.height() - 6) // 2, 2, 6)


class PromptEdit(QPlainTextEdit):
    """A prompt block with a fixed copy icon inside its upper-right corner."""

    def __init__(self, text: str, scroll_target, target: str | None = None) -> None:
        super().__init__()
        self.setObjectName("prompt")
        self.setPlainText(text)
        self.setReadOnly(True)
        self.setVerticalScrollBar(DashedScrollBar(Qt.Orientation.Vertical, self))
        self.setHorizontalScrollBar(DashedScrollBar(Qt.Orientation.Horizontal, self))
        self.chat_target = target
        self.setViewportMargins(0, 0, 90 if target in CHAT_URLS else 58, 0)
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
        if hasattr(self, "copy_button"):
            self.copy_button.move(self.width() - self.verticalScrollBar().sizeHint().width() - 36, 7)
            self.copy_button.raise_()
        if hasattr(self, "chat_button"):
            self.chat_button.move(self.width() - self.verticalScrollBar().sizeHint().width() - 68, 7)
            self.chat_button.raise_()


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
        layout.setContentsMargins(12, 10, 10, 10)
        layout.setSpacing(4)
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
            article.setIcon(QIcon(str(ROOT / "desktop" / "article.svg")))
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
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        for source in self.sources:
            label = QLabel(f'<a href="{escape(source["url"], quote=True)}">{escape(source["title"])}</a><br>'
                           f'<span style="color: #7b8799">{escape(source.get("reference", ""))}</span>')
            label.setWordWrap(True)
            label.setOpenExternalLinks(True)
            layout.addWidget(label)
        close = QPushButton("Done")
        close.setObjectName("ghost")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
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
        popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        popup.rounded_border = RoundedPopupBorder(popup)
        popup.setObjectName("techniquePopup")
        self._popup = popup

        outer = QVBoxLayout(popup)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(12)

        search: QLineEdit | None = None
        if self._searchable:
            search = QLineEdit()
            search.setPlaceholderText("Filter techniques…")
            search.setClearButtonEnabled(True)
            outer.addWidget(search)

        scroll = QScrollArea(popup)
        use_step_scroll(scroll)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: #fff8e7; border: none; }")

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
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(8)
            grid_items: list[TechniqueItem] = []
            for index, item in enumerate(items):
                label = item.get("label") or item.get("name") or item["key"]
                widget = TechniqueItem(item["key"], label, item.get("hint", ""), item.get("sources"))
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
            painter.fillRect(self.rect(), QColor(255, 248, 222, 205))
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
        self.setValue(3)

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
            app.setEffectEnabled(Qt.UIEffect.UI_AnimateCombo, False)
            app.setEffectEnabled(Qt.UIEffect.UI_FadeMenu, False)
            app.setEffectEnabled(Qt.UIEffect.UI_AnimateMenu, False)
        self.setWindowTitle("Prompta")
        available = self.screen().availableGeometry()
        self.resize(min(1160, available.width() - 48), min(820, available.height() - 80))
        self.worker: Worker | None = None
        self.history_store = HistoryStore()
        self._history_items: list[dict] = []
        self._active_thoughts = ""
        self._discard_result = False

        root = BackgroundWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 2, 12, 6)
        outer.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(20)
        title = QLabel("Prompta")
        title.setObjectName("title")
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
            "Thoughts\n\nWrite freely. The pipeline will turn your thoughts into a brief."
        )
        thoughts_palette = self.thoughts.palette()
        thoughts_palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9a8c6b"))
        self.thoughts.setPalette(thoughts_palette)
        self.thoughts.setMinimumHeight(150)
        box.addWidget(self.thoughts, 1)

        box.addSpacing(4)
        self.technique_label = self._mini_label("Technique")
        box.addWidget(self.technique_label)
        self.technique = Dropdown("— choose a technique —", columns=2, searchable=True, popup_width=820)
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
        self.model = Dropdown("Choose a model", searchable=True, popup_width=460)
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
        self.models_hint = QLabel("Loading Ollama models…")
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
        settings_title.setObjectName("goal")
        settings_outer.addWidget(settings_title)
        self.settings_tabs = QTabWidget()
        self.settings_tabs.setAccessibleName("Settings sections")
        model_page = QWidget()
        settings_layout = QVBoxLayout(model_page)
        settings_layout.setContentsMargins(0, 14, 0, 0)
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
            for model in manifest["models"]:
                self.prompt_model.addItem(model["name"], model["id"])
        except (OSError, ValueError, KeyError, TypeError):
            self.prompt_model.setEnabled(False)
        self.prompt_model.setToolTip("Build a prompt using the selected model's saved official documentation. The generator model stays the same.")
        self.prompt_model.currentIndexChanged.connect(self._on_prompt_model_changed)
        target_grid.addWidget(self.prompt_model, 2, 0, 1, 2)
        target_grid.setColumnStretch(0, 1)
        target_grid.setColumnStretch(1, 1)
        self.deterministic = QCheckBox(card)
        self.deterministic.hide()
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
        self.deterministic.setEnabled(selected is None)
        self.technique.setToolTip(
            f"{PROMPT_TARGETS[selected][0]} mode uses official rules instead of the technique catalog."
            if selected else "Choose a technique to build a prompt using its method"
        )

    def open_settings(self) -> None:
        self.settings_dialog.open()
        if self.settings_tabs.currentIndex() == 0:
            self.api_key.setFocus()
        else:
            self.library.reload()
            self.library.search.setFocus()

    def _settings_tab_changed(self, index: int) -> None:
        if index == 1:
            self.library.reload()

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
        card.setObjectName("mainColumn")
        box = card.vbox()
        box.setContentsMargins(16, 0, 0, 0)

        history_row = QHBoxLayout()
        history_row.setSpacing(8)
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Search requests and prompts…")
        self.history_search.setClearButtonEnabled(True)
        self.history_search.textChanged.connect(self._filter_history)
        history_row.addWidget(self.history_search, 1)
        self.history = HistoryComboBox()
        # Saved titles must not become the minimum width of the entire window.
        self.history.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.history.setMinimumContentsLength(12)
        self.history.addItem("— no history yet —", -1)
        self.history.currentIndexChanged.connect(self._on_history_selected)
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
        self.history.addItem("— choose a prompt —" if self._history_items else "— no history yet —", -1)
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

    def _show_placeholder(self) -> None:
        # Empty output area stays blank: no hint text.
        self._clear_output()
        self.output_layout.addStretch(1)

    # ── запуск ────────────────────────────────────────────────────
    def clear_workspace(self) -> None:
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
            "claudeOnly": self.claude_only.isChecked(),
            "chatgptOnly": self.chatgpt_only.isChecked(),
            "geminiOnly": self.gemini_only.isChecked(),
            "grokOnly": self.grok_only.isChecked(),
            "deterministic": self.deterministic.isChecked() and self._selected_target() is None,
            "variants": self.variants.value(),
        }
        if self.openModel_only.isChecked():
            payload["openModel"] = self.prompt_model.currentData()
        if technique_key and self._selected_target() is None:
            payload["manualTechnique"] = technique_key

        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.generation_progress.setValue(0)
        self.generation_progress.show()
        selected = self._selected_target()
        target_label = self.prompt_model.currentText() if selected == "openModel" else PROMPT_TARGETS[selected][0] if selected else ""
        self.status.setText(f"Building {target_label} prompt from official sources…" if selected else "Brief → technique selection → synthesis…")

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
QLabel#meta { color: #665d49; font-size: 12px; }
QTabWidget#variantTabs::pane { border: none; background: transparent; top: 6px; }
QTabWidget#variantTabs > QWidget { background: transparent; }
QTabWidget#variantTabs QTabBar { background: transparent; }
QTabWidget#variantTabs::tab-bar { alignment: left; }
"""

GENERAL_TARGET = "general"
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

    def __init__(self, title: str, expanded: bool = False) -> None:
        super().__init__()
        self._title = title
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.button = QToolButton()
        self.button.setObjectName("disclosure")
        self.button.setCheckable(True)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.button.toggled.connect(self._toggle)
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
        self.button.setText(f"{'▾' if expanded else '▸'}  {self._title}")
        self.body.setVisible(expanded)


def muted_label(text: str, name: str = "muted") -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
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
        super().__init__()
        self._restyle_input()
        self.run_button.setText("Build prompt   ⌘↵")
        self.run_button.setToolTip("⌘↵ builds the prompt")
        self.cancel_button.setText("Stop")
        self.history_search.setPlaceholderText("Search history…")
        self.status.setText("")

    # ── left column ───────────────────────────────────────────────
    def _restyle_input(self) -> None:
        card_layout = self.thoughts.parentWidget().layout()

        grid = find_layout(card_layout, self.prompt_model)
        for key, _ in TARGET_SEGMENTS[1:]:
            getattr(self, f"{key}_only").hide()
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
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
        self.prompt_model.setItemText(0, "Open-weight model…")
        for key in PROMPT_TARGETS:
            getattr(self, f"{key}_only").toggled.connect(self._sync_segments)

        variants_row = find_layout(card_layout, self.variants)
        variants_label = next(variants_row.itemAt(i).widget() for i in range(variants_row.count())
                              if isinstance(variants_row.itemAt(i).widget(), QLabel))
        self.advanced = Disclosure("Advanced")
        for widget in (self.technique_label, self.technique):
            card_layout.removeWidget(widget)
            self.advanced.body_layout.addWidget(widget)
        for widget in (variants_label, self.variants):
            variants_row.removeWidget(widget)
        moved = QHBoxLayout()
        moved.addWidget(variants_label)
        moved.addStretch(1)
        moved.addWidget(self.variants)
        self.advanced.body_layout.addLayout(moved)
        divider = self.findChild(QFrame, "inputDivider")
        if divider is not None:
            divider.hide()
        actions = find_layout(card_layout, self.run_button)
        index = next(i for i in range(card_layout.count()) if card_layout.itemAt(i).layout() is actions)
        card_layout.insertWidget(index, self.advanced)
        self.technique.changed.connect(self._update_advanced_title)
        self.variants.buttons.idClicked.connect(self._update_advanced_title)
        self._sync_segments()

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
        if self.technique.current_key() and self._selected_target() is None:
            extra.append(f"technique: {self.technique.text()}")
        if self.variants.value() != 3:
            extra.append(f"variants: {self.variants.value()}")
        self.advanced.set_title("Advanced" + (f" · {', '.join(extra)}" if extra else ""))

    def clear_workspace(self) -> None:
        super().clear_workspace()
        self.status.setText("")

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

    def _add_zero_shot_to(self, layout: QVBoxLayout, payload: dict) -> None:
        layout.addWidget(self._heading("Zero-shot · baseline without a technique", "section"))
        editor = PromptEdit(self._zero_shot_text(payload), self.output_scroll)
        editor.setAccessibleName("Zero-shot baseline prompt")
        editor.setFixedHeight(220)
        layout.addWidget(editor)

    def _prompt_view(self, prompts: list[tuple[str, str]], target: str | None) -> QWidget:
        def editor(text: str) -> PromptEdit:
            box = PromptEdit(text, self.output_scroll, target)
            box.setFixedHeight(420)
            return box

        self.prompt_edit = editor(prompts[0][1])
        if len(prompts) == 1:
            return self.prompt_edit
        tabs = QTabWidget()
        tabs.setObjectName("variantTabs")
        tabs.tabBar().setDrawBase(False)
        tabs.addTab(self.prompt_edit, "Variant 1")
        for index, (_, prompt) in enumerate(prompts[1:], 2):
            tabs.addTab(editor(prompt), f"Variant {index}")
        for index, (name, _) in enumerate(prompts):
            tabs.setTabToolTip(index, name)
        return tabs

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
        if guidance is not None:
            name = guidance.get("target") if source_target == "openModel" else PROMPT_TARGETS[source_target][0]
            meta = f"Official {name} guidance"
        else:
            meta = f"{choice['name']} · confidence {round(choice['confidence'] * 100)}%"
        layout.addWidget(muted_label(meta, "meta"))
        prompts = [(choice["name"], synthesis["prompt"])] + [(a["choice"]["name"], a["synthesis"]["prompt"]) for a in alternatives]
        layout.addWidget(self._prompt_view(prompts, source_target))
        if synthesis.get("missing"):
            layout.addWidget(muted_label("Missing information: " + ", ".join(synthesis["missing"]), "warn"))

        details = Disclosure("How this prompt was built")
        body = details.body_layout
        body.addWidget(muted_label(brief["goal"]))
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for text in (f"type: {brief['task_type']}", f"language: {brief['language']}", f"stakes: {brief['stakes']}"):
            chips.addWidget(self._heading(text, "chip"))
        chips.addStretch(1)
        body.addLayout(chips)
        body.addWidget(muted_label(f"Format: {brief['output_format']}"))
        if brief.get("assumptions"):
            body.addWidget(muted_label("Assumptions: " + "; ".join(brief["assumptions"])))
        body.addWidget(self._heading(choice["name"], "section"))
        body.addWidget(muted_label(f"Why: {choice['reason']}"))
        if guidance is None:
            body.addWidget(muted_label(f"Why not a cheaper method: {choice['whyNotCheaper']}"))
        for index, alt in enumerate(alternatives, 2):
            body.addWidget(muted_label(f"Variant {index} · {alt['choice']['name']}: {alt['choice']['reason']}"))
        config = synthesis["config"]
        body.addWidget(muted_label(
            f"temperature {config['temperature']} · top_p {config['top_p']} · max_tokens {config['max_tokens']}. {config['rationale']}"
        ))
        warnings = list(dict.fromkeys(w for item in [synthesis] + [a["synthesis"] for a in alternatives] for w in item["warnings"]))
        if warnings:
            body.addWidget(muted_label("\n".join(f"• {w}" for w in warnings), "warn"))
        self._add_zero_shot_to(body, result)

        if isinstance(guidance, dict) and source_target:
            body.addWidget(self._heading(
                f"Sources · {guidance.get('rule_set_version', 'unknown')} · checked {guidance.get('verified_at', 'unknown')}", "section"))
            for index, variant in enumerate(guidance.get("variants", []), 1):
                body.addWidget(muted_label(f"Variant {index} rules: {', '.join(variant.get('rule_ids', []))}"))
            for rule in guidance.get("rules", []):
                url = rule.get("source_url", "")
                parsed = urlparse(url)
                if parsed.scheme != "https" or parsed.hostname not in PROMPT_TARGETS[source_target][1] or parsed.username or parsed.password:
                    continue
                link = QLabel(f"<a href=\"{escape(url, quote=True)}\">{escape(rule.get('id', ''))} · {escape(rule.get('source_section', 'Source'))}</a>")
                link.setOpenExternalLinks(True)
                link.setWordWrap(True)
                link.setToolTip(rule.get("rule_text", ""))
                body.addWidget(link)
        if result.get("rejected"):
            body.addWidget(muted_label(f"Techniques filtered out: {len(result['rejected'])}"))

        layout.addWidget(details)
        layout.addStretch(1)

    def render_manual(self, manual: dict) -> None:
        self._clear_output()
        technique = manual["technique"]
        self.output_layout.addWidget(self._heading(manual.get("topic") or technique["name"], "goal"))
        self.output_layout.addWidget(muted_label(f"{technique['name']} · chosen manually", "meta"))
        self.output_layout.addWidget(self._prompt_view([(technique["name"], manual["prompt"])], None))
        details = Disclosure("How this prompt was built")
        config = manual["config"]
        details.body_layout.addWidget(muted_label(f"Method source: {manual['source_ref']}"))
        details.body_layout.addWidget(muted_label(f"temperature {config['temperature']} · top_p {config['top_p']} · {config['rationale']}"))
        self._add_zero_shot_to(details.body_layout, manual)
        self.output_layout.addWidget(details)
        self.output_layout.addStretch(1)


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
