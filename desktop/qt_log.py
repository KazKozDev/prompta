"""Фильтр сообщений Qt: глушит известный безвредный шум моста доступности macOS, остальное печатает.

Когда macOS (специальные возможности, системные подсказки ввода, диктовка) опрашивает текстовое поле,
Qt 6 на Cocoa может спросить у QTextCursor позицию за концом текста и напечатать
«QTextCursor::setPosition: Position 'N' out of range», а у списков — «qt.accessibility.table:
Cell requested for row N is out of bounds». Наш код setPosition не вызывает, на работу окна это не
влияет, но засоряет вывод сотнями строк и прячет настоящие ошибки.

PROMPTA_QT_DEBUG=1 возвращает полный вывод Qt.
"""
from __future__ import annotations

import os
import re
import sys

from PyQt6.QtCore import QtMsgType, qInstallMessageHandler

KNOWN_NOISE = (
    re.compile(r"^QTextCursor::setPosition: Position '\d+' out of range$"),
    re.compile(r"^Cell requested for row \d+ is out of bounds for table with \d+ rows! Resizing table model\.$"),
)

suppressed = 0


def is_known_noise(message: str, category: str = "") -> bool:
    text = message.strip()
    if category and category not in ("default", "qt.accessibility.table"):
        return False
    return any(pattern.match(text) for pattern in KNOWN_NOISE)


def _handler(mode: QtMsgType, context, message: str) -> None:
    global suppressed
    category = getattr(context, "category", "") or ""
    if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtDebugMsg) and is_known_noise(message, category):
        suppressed += 1
        return
    prefix = f"{category}: " if category and category != "default" else ""
    print(f"{prefix}{message}", file=sys.stderr)


def install() -> bool:
    """Ставит фильтр, если не включён полный вывод; возвращает, поставлен ли он."""
    if os.environ.get("PROMPTA_QT_DEBUG") == "1":
        return False
    qInstallMessageHandler(_handler)
    return True
