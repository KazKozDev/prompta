"""Фоновые потоки Prompta: мост к TS-пайплайну, загрузка моделей и техник."""

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



def node_binary() -> str:
    for candidate in (shutil.which("node"), "/opt/homebrew/bin/node", "/usr/local/bin/node"):
        if candidate and Path(candidate).exists():
            return candidate
    return "node"


class TechniquesLoader(QThread):
    loaded = pyqtSignal(list)
    prompt_version = ""  # version of the pipeline's prompts, to spot history built under older rules

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
            self.prompt_version = str(data.get("promptVersion") or "")
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
