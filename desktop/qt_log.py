"""Qt message filter: silences the known harmless noise of the macOS accessibility bridge and prints the rest.

When macOS (accessibility, system text input suggestions, dictation) queries a text field,
Qt 6 on Cocoa may ask QTextCursor for a position past the end of the text and print
"QTextCursor::setPosition: Position 'N' out of range", and for lists "qt.accessibility.table:
Cell requested for row N is out of bounds". Our code never calls setPosition and the window works
fine, but the output fills with hundreds of lines that hide real errors.

PROMPTA_QT_DEBUG=1 brings back the full Qt output.
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
    """Installs the filter unless full output is on; returns whether it was installed."""
    if os.environ.get("PROMPTA_QT_DEBUG") == "1":
        return False
    qInstallMessageHandler(_handler)
    return True
