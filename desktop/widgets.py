"""Prompta base widgets: tooltips, popup animation, the history combo box, scrolling and text editors.

Moved out of app.py so the main window is not a monolith; app.py re-exports these names."""

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


from PyQt6.QtCore import QModelIndex, QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QUrl, QProcess, QThread, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel, QColor, QCursor, QPainter, QPalette, QPen, QFont, QGuiApplication, QIcon, QPixmap, QKeySequence, QShortcut, QDesktopServices, QTextDocument, QTextCursor
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

try:
    from .theme import CHAT_URLS, DARK_SCROLL_QSS, PROMPT_TARGETS, ROOT
except ImportError:
    from theme import CHAT_URLS, DARK_SCROLL_QSS, PROMPT_TARGETS, ROOT


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
        # A hidden picker can open under another control (the Open target segment row).
        anchor = getattr(self, "popup_anchor", None) or self
        width = min(max(240, anchor.width()), available.width() - 16)
        height = min(460, max(46, self.count() * 32 + 14), available.height() - 16)
        popup.resize(width, height)
        position = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
        x = max(available.left() + 8, min(position.x(), available.right() - width - 8))
        y = position.y()
        if y + height > available.bottom() - 8:
            y = max(available.top() + 8, anchor.mapToGlobal(QPoint(0, -height - 4)).y())
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
        self.microphone_icon.raise_()
        # A press over the icon starts dictation even if a neighbour (the field's text area, an overlay
        # scrollbar) received it; presses near the icon are logged so a miss can be traced.
        self.installEventFilter(self)
        self.viewport().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt naming
        if event.type() == QEvent.Type.MouseButtonPress and watched in (self, self.viewport()):
            point = watched.mapTo(self, event.position().toPoint()) if watched is not self else event.position().toPoint()
            hit = self.microphone_icon.geometry().adjusted(-6, -6, 6, 6)
            if point.x() > self.width() - 90 and point.y() < 60:
                self._voice_log(f"press at {point.x()},{point.y()} on {type(watched).__name__} · icon {hit.getRect()}")
            if hit.contains(point) and self.microphone_icon.isEnabled():
                self._toggle_dictation()
                return True
        return super().eventFilter(watched, event)

    @staticmethod
    def _voice_log(message: str) -> None:
        """Dictation events and errors only (no audio, no recognised text), for diagnosing microphone problems."""
        try:
            folder = Path(os.environ.get("PROMPTA_LOG_DIR") or Path.home() / "Library" / "Logs" / "Prompta")
            folder.mkdir(parents=True, exist_ok=True)
            with open(folder / "voice.log", "a", encoding="utf-8") as log:
                log.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
        except OSError:
            pass

    def _toggle_dictation(self) -> None:
        if self.voice_process is not None:
            if self.voice_state == "recording":
                self.voice_process.write(b"stop\n")
                self._voice_state("transcribing")
            return
        interpreter = ROOT / ".venv-whisper/bin/python"
        self._voice_log(f"click: start · interpreter {'found' if interpreter.exists() else 'MISSING'}")
        if not interpreter.exists():
            self.setToolTip("Whisper is not installed. See desktop/README.md.")
            self._voice_failure("Whisper is not installed. See desktop/README.md.")
            return
        self.voice_process = QProcess(self)
        # Through prompta-mic when it is built: it carries the microphone usage text the system Python lacks,
        # so macOS asks for access instead of silently recording silence.
        helper = ROOT / "release/Prompta.app/Contents/MacOS/prompta-mic"
        script = str(ROOT / "desktop/voice_input.py")
        if helper.exists():
            self.voice_process.setProgram(str(helper))
            self.voice_process.setArguments([str(interpreter), script])
        else:
            self.voice_process.setProgram(str(interpreter))
            self.voice_process.setArguments([script])
        self._voice_log(f"worker via {'prompta-mic' if helper.exists() else 'python directly'}")
        self.voice_process.readyReadStandardOutput.connect(self._voice_output)
        self.voice_process.readyReadStandardError.connect(self._voice_stderr)
        self.voice_process.finished.connect(self._voice_finished)
        self.voice_process.errorOccurred.connect(self._voice_process_error)
        self.voice_buffer = ""
        self.setToolTip("")
        self._voice_state("starting")
        self.voice_process.start()

    def _voice_stderr(self) -> None:
        if self.voice_process is not None:
            text = bytes(self.voice_process.readAllStandardError()).decode("utf-8", errors="replace").strip()
            if text:
                self._voice_log("stderr: " + text[-600:].replace("\n", " | "))

    def _voice_state(self, state: str) -> None:
        self._voice_log(f"state: {state}")
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
                    if state == "recording":
                        self._begin_live_text()
                    self._voice_state(state)
                elif state == "partial":
                    text = event.get("text", "")
                    if isinstance(text, str):
                        self._show_live_text(text)  # what was said so far, refined as dictation goes on
                elif state == "done":
                    text = event.get("text", "")
                    self._voice_log(f"done: {len(text) if isinstance(text, str) else 0} characters recognised")
                    if isinstance(text, str) and text.strip():
                        self._show_live_text(text)
                        self._dictation_base = None  # the final text stays
                    else:
                        self._end_live_text()
                        self.setToolTip("No speech detected. Please try again.")
                elif state == "error":
                    self._voice_failure(str(event.get("message", "Voice input failed.")))
            except (ValueError, AttributeError):
                continue

    def _begin_live_text(self) -> None:
        """Dictated text goes after what is already typed; the field is read-only until dictation ends."""
        current = self.toPlainText()
        self._dictation_original = current
        self._dictation_base = current.rstrip("\n") + "\n" if current.strip() else ""
        self.setReadOnly(True)

    def _show_live_text(self, text: str) -> None:
        base = getattr(self, "_dictation_base", None)
        if base is None:
            self._begin_live_text()
            base = self._dictation_base
        self.setPlainText(base + text.strip())
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _end_live_text(self) -> None:
        """No final text (error, silence, nothing said): put the request back as it was."""
        if getattr(self, "_dictation_base", None) is not None:
            self.setPlainText(getattr(self, "_dictation_original", ""))
            self._dictation_base = None
        self.setReadOnly(False)

    def _voice_process_error(self, error) -> None:
        self._voice_log(f"process error: {error}")
        self._voice_failure("Whisper could not run. Check microphone access in macOS Privacy & Security.")
        if error == QProcess.ProcessError.FailedToStart:
            self._voice_finished()

    def _voice_failure(self, message: str) -> None:
        self._voice_log("error: " + message)
        self._end_live_text()
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
        self._end_live_text()  # keeps a final text; only undoes an unfinished live one
        self._voice_state("idle")
        if process:
            process.deleteLater()
        if code and not self.toolTip():
            self._voice_failure("Whisper stopped. Check microphone access in macOS Privacy & Security.")

    def stop_dictation(self) -> None:
        if self.voice_process:
            self.voice_process.terminate()  # prompta-mic passes this on to the worker; a kill would orphan it
            if not self.voice_process.waitForFinished(2000):
                self.voice_process.kill()
                self.voice_process.waitForFinished(1000)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "microphone_icon"):
            self.microphone_icon.move(self.width() - self.verticalScrollBar().sizeHint().width() - 19, 7)
            self.microphone_icon.raise_()


TICK_PITCH = 7      # px from one tick to the next
TICK_MAX = 15       # the indicator is a short group of ticks, not a full-height track


def dashed_ticks(bar: QScrollBar) -> list[int]:
    """Tick positions along the bar: at most TICK_MAX, centred on the bar."""
    length = bar.height() if bar.orientation() == Qt.Orientation.Vertical else bar.width()
    count = max(0, min(TICK_MAX, (length - 6) // TICK_PITCH + 1))
    start = (length - (count - 1) * TICK_PITCH - 2) // 2
    return [start + i * TICK_PITCH for i in range(count)]


def paint_dashed_scrollbar(bar: QScrollBar) -> None:
    """Draw any scroll bar as a short group of ticks; the bright, longer one is where the view is."""
    painter = QPainter(bar)
    owner = bar.parentWidget()
    while owner and not isinstance(owner, QAbstractScrollArea):
        owner = owner.parentWidget()
    prompt = owner is not None and owner.objectName() == "prompt"
    if prompt:
        painter.fillRect(bar.rect(), QColor("#454545"))
    ticks = dashed_ticks(bar)
    if not ticks or bar.maximum() <= bar.minimum():
        painter.end()
        return
    fraction = (bar.sliderPosition() - bar.minimum()) / (bar.maximum() - bar.minimum())
    if bar.invertedAppearance():
        fraction = 1 - fraction
    current = round(fraction * (len(ticks) - 1))
    vertical = bar.orientation() == Qt.Orientation.Vertical
    thickness = bar.width() if vertical else bar.height()
    painter.setPen(Qt.PenStyle.NoPen)
    for index, position in enumerate(ticks):
        active = index == current
        painter.setBrush(QColor(("#ededed" if active else "#5a5a5a") if prompt else ("#5c4a26" if active else "#d9cba6")))
        size = min(thickness - 2, 10 if active else 7)
        if vertical:
            painter.drawRect((bar.width() - size) // 2, position, size, 2)
        else:
            painter.drawRect(position, (bar.height() - size) // 2, 2, size)
    painter.end()


def drag_dashed_scrollbar(bar: QScrollBar, event) -> bool:
    """Click or drag along the tick group moves the view to that point; outside it clamps to the ends."""
    kind = event.type()
    if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
        bar.setSliderDown(True)
    elif kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
        bar.setSliderDown(False)
        return True
    elif not (kind == QEvent.Type.MouseMove and bar.isSliderDown()):
        return kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick)
    ticks = dashed_ticks(bar)
    if len(ticks) < 2:
        return True
    point = event.position()
    at = point.y() if bar.orientation() == Qt.Orientation.Vertical else point.x()
    fraction = min(1.0, max(0.0, (at - ticks[0] - 1) / (ticks[-1] - ticks[0])))
    if bar.invertedAppearance():
        fraction = 1 - fraction
    bar.setSliderPosition(round(bar.minimum() + fraction * (bar.maximum() - bar.minimum())))
    return True


class DashedScrollBar(QScrollBar):
    """Native wheel and keys; drawn and dragged as a short group of ticks."""
    def paintEvent(self, event) -> None:  # noqa: N802
        paint_dashed_scrollbar(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        drag_dashed_scrollbar(self, event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        drag_dashed_scrollbar(self, event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        drag_dashed_scrollbar(self, event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        drag_dashed_scrollbar(self, event)


_DASHED_MOUSE = (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                 QEvent.Type.MouseMove, QEvent.Type.MouseButtonDblClick)


class DashedScrollPainter(QObject):
    """App-wide: every other scroll bar (lists, menus, popups, dialogs) is drawn and dragged as ticks too."""
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if not isinstance(obj, QScrollBar) or isinstance(obj, DashedScrollBar):
            return False
        if event.type() == QEvent.Type.Paint:
            paint_dashed_scrollbar(obj)
            return True
        if event.type() in _DASHED_MOUSE:
            return drag_dashed_scrollbar(obj, event)
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
