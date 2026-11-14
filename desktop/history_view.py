"""Request history: the saved requests, the header's search picker, Settings → History and prompt edits.

HistoryView owns its widgets and the store it is given; the window places the widgets and renders entries
through the `render` callable it passes in. Nothing here reaches into the window.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from history import history_topic
from settings_ui import LABEL_GAP, LIST_GAP, add_section, field_label, muted, settings_page, text_link

from collections.abc import Callable

from PyQt6.QtCore import QObject, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QPainter, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from controls import Dropdown, IconDropdown
from history import HistoryStore
from result_view import CONTROL_HEIGHT

from widgets import (
    DELETABLE_ROLE,
    HistoryComboBox,
    HistoryDeleteClicks,
    HistoryDeleteDelegate,
    history_delete_rect,
    use_step_scroll,
)


DAY_ROLE = Qt.ItemDataRole.UserRole + 42  # a day header row in Settings → History
TIME_ROLE = Qt.ItemDataRole.UserRole + 43  # HH:MM shown at the right of a request row


class HistorySettingsDelegate(HistoryDeleteDelegate):
    """Settings → History rows: small caps day headers; requests with the title on the left and the time on
    the right, the time giving way to the delete cross while the row is under the pointer."""

    ROW, HEADER, PAD = 30, 34, 8

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), self.HEADER if index.data(DAY_ROLE) else self.ROW)

    def paint(self, painter, option, index) -> None:  # noqa: D401
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.view.font())
        if index.data(DAY_ROLE):
            font.setPixelSize(10)
            font.setWeight(QFont.Weight.Medium)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
            painter.setFont(font)
            painter.setPen(QColor("#74694f"))
            painter.drawText(
                rect.adjusted(self.PAD, 0, -self.PAD, -6),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                str(index.data()).upper(),
            )
            painter.restore()
            return
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#f6e5b3") if selected else QColor(120, 96, 30, 26))
            painter.drawRoundedRect(QRectF(rect), 6, 6)
        font.setPixelSize(13)
        painter.setFont(font)
        title_rect = rect.adjusted(self.PAD, 0, -(self.PAD + 52), 0)
        title = painter.fontMetrics().elidedText(str(index.data()), Qt.TextElideMode.ElideRight, title_rect.width())
        painter.setPen(QColor("#4a4232"))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        if hovered:
            cross = history_delete_rect(rect)
            cursor = self.view.viewport().mapFromGlobal(QCursor.pos())
            if cross.contains(cursor):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(128, 106, 61, 40))
                painter.drawEllipse(cross)
            self.icon.paint(painter, cross.adjusted(5, 5, -5, -5))
        else:
            font.setPixelSize(12)
            painter.setFont(font)
            painter.setPen(QColor("#8a7f66"))
            painter.drawText(
                rect.adjusted(0, 0, -self.PAD, 0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                str(index.data(TIME_ROLE) or ""),
            )
        painter.restore()


class HistoryView(QObject):
    """Search, pick, delete, clear and retention settings. Widgets for the window to place: `picker` (header),
    `combo` (hidden, still drives restore) and `notice` (result column), `page` and `delete_all_button`
    (Settings → History). `opened(entry)` follows a successful `render`; `leaveSettings` asks to close Settings
    when an entry is opened from there."""

    opened = pyqtSignal(dict)
    leaveSettings = pyqtSignal()

    def __init__(self, store: HistoryStore, render: Callable[[dict], None], dialog_parent: QWidget) -> None:
        super().__init__(dialog_parent)
        self.store = store
        self._render = render  # raises KeyError, TypeError or ValueError for an entry it cannot show
        self._dialog_parent = dialog_parent
        self.items: list[dict] = []
        self.shown_entry: int | None = None  # index in items of the result on screen
        self._pending_edits: dict[tuple[int, int], str] = {}
        self._edit_timer = QTimer(self)
        self._edit_timer.setSingleShot(True)
        self._edit_timer.timeout.connect(self.save_edits)

        self.combo = HistoryComboBox()
        self.combo.deletable = True
        # Saved titles must not become the minimum width of the entire window.
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(12)
        self.combo.ensurePolished()
        self.combo.setFixedHeight(CONTROL_HEIGHT)
        self.combo.addItem("— no history yet —", -1)
        self.combo.currentIndexChanged.connect(self._on_selected)
        self.combo.deleteRequested.connect(self._delete_row)
        self.notice = QLabel()
        self.notice.setObjectName("error")
        self.notice.setWordWrap(True)
        self.notice.hide()
        # History is a picker like every other: the same button, chevron and panel with search inside.
        self.picker = IconDropdown(
            "search.svg",
            "Search history",
            searchable=True,
            popup_width=480,
            search_placeholder="Search requests and prompts",
        )
        self.picker.setCursor(Qt.CursorShape.PointingHandCursor)
        self.picker.changed.connect(self._on_picked)
        self.picker.deleteRequested.connect(self._on_picker_delete)
        self.page = self._build_settings_page()

    def show_notice(self, text: str) -> None:
        self.notice.setText(text)
        self.notice.show()

    def deselect(self) -> None:
        """The workspace was cleared: no entry is on screen any more."""
        self.shown_entry = None
        previous = self.combo.blockSignals(True)
        self.combo.setCurrentIndex(0)
        self.combo.blockSignals(previous)
        self.notice.hide()

    def flush_edits(self) -> None:
        """Save prompt edits still waiting for the typing pause (on quit)."""
        if self._edit_timer.isActive():
            self._edit_timer.stop()
            self.save_edits()

    def load(self) -> None:
        try:
            self.items = self.store.load()
        except (OSError, ValueError, sqlite3.Error):
            self.notice.setText("Could not load history. The existing file has been preserved.")
            self.notice.show()
        self.filter()

    def filter(self, text: str = "", selected: int | None = None) -> None:
        needle = text.strip().casefold()
        current = self.combo.currentData() if selected is None else selected
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("— history —" if self.items else "— no history yet —", -1)
        for index, entry in enumerate(self.items):
            searchable = (
                entry['thoughts'] + ' ' + entry['label'] + ' ' + json.dumps(entry['payload'], ensure_ascii=False)
            )
            if needle and needle not in searchable.casefold():
                continue
            label = history_topic(entry['thoughts'], entry['payload'], entry['label'])
            self.combo.addItem(label, index)
            date = entry['created_at'][:16].replace('T', ' ')
            self.combo.setItemData(
                self.combo.count() - 1, f"{label}\n{date}\n{entry['thoughts']}", Qt.ItemDataRole.ToolTipRole
            )
        if self.combo.count() == 1 and needle:
            self.combo.setItemText(0, "— no matches —")
        target = self.combo.findData(current)
        self.combo.setCurrentIndex(max(0, target))
        self.combo.blockSignals(False)
        self._sync_picker()

    def _delete_row(self, row: int) -> None:
        removed = self.combo.itemData(row)
        if not isinstance(removed, int) or not 0 <= removed < len(self.items):
            return
        entry = self.items[removed]
        if entry.get('id') is not None:
            try:
                self.store.delete(entry['id'])
            except (OSError, sqlite3.Error):
                self.notice.setText("Could not delete this entry from disk.")
                self.notice.show()
                return
        del self.items[removed]
        current = self.combo.currentData()
        if isinstance(current, int) and current >= 0:
            current = -1 if current == removed else current - (current > removed)
        self.filter(selected=current)
        if not self.combo.isVisible():
            return  # the header picker deletes through here too, and reopens itself
        if self.combo.count() > 1:
            self.combo.showPopup()  # rebuild the open list without the deleted row
        else:
            self.combo.hidePopup()

    HISTORY_LIMITS = [
        (100, "Keep the newest 100"),
        (500, "Keep the newest 500"),
        (2000, "Keep the newest 2,000"),
        (0, "Keep everything"),
        (-1, "Don't save history"),
    ]
    HISTORY_AGES = [(0, "Forever"), (30, "30 days"), (90, "90 days"), (365, "1 year")]

    def _prefs_path(self) -> Path:
        return self.store.path.with_name("settings.json")

    def _load_prefs(self) -> None:
        """Saved choice applies unless an environment variable already set the limit."""
        try:
            prefs = json.loads(self._prefs_path().read_text())
        except (OSError, ValueError):
            return
        if "PROMPTA_HISTORY_MAX" not in os.environ and isinstance(prefs.get("history_max"), int):
            self.store.max_entries = prefs["history_max"]
        if "PROMPTA_HISTORY_DAYS" not in os.environ and isinstance(prefs.get("history_days"), int):
            self.store.max_age_days = max(0, prefs["history_days"])

    def _build_settings_page(self) -> QWidget:
        """Retention on top (two short choices), then the requests themselves: searchable, grouped by day."""
        self._load_prefs()
        page, layout = settings_page("Every request you build is kept on this Mac, readable only by your account.")

        # The app's own pickers, as on Model & API, not system combo boxes.
        limits_items = [{"key": str(value), "label": label} for value, label in self.HISTORY_LIMITS]
        if not any(int(item["key"]) == self.store.max_entries for item in limits_items):
            limits_items.append(
                {
                    "key": str(self.store.max_entries),
                    "label": f"Keep the newest {self.store.max_entries}",
                }
            )
        self.limit = Dropdown(popup_width=260)
        self.limit.setAccessibleName("How many requests to keep")
        self.limit.set_items(limits_items)
        self.limit.set_current(str(self.store.max_entries))
        ages = [{"key": str(value), "label": label} for value, label in self.HISTORY_AGES]
        self.age = Dropdown(popup_width=260)
        self.age.setAccessibleName("Delete requests older than")
        self.age.set_items(ages)
        known_age = any(int(item["key"]) == self.store.max_age_days for item in ages)
        self.age.set_current(str(self.store.max_age_days) if known_age else ages[0]["key"])
        limits = QHBoxLayout()  # two short choices side by side, each under its own label
        limits.setSpacing(16)
        for title, combo in (("How many to keep", self.limit), ("Delete older than", self.age)):
            column = QVBoxLayout()
            column.setSpacing(LABEL_GAP)
            column.addWidget(field_label(title))
            column.addWidget(combo)
            limits.addLayout(column, 1)
        add_section(layout, None, limits, hint="Older entries are removed when a new result is saved.")

        self.settings_search = QLineEdit()
        self.settings_search.setPlaceholderText("Search requests and prompts")
        self.settings_search.setClearButtonEnabled(True)
        self.settings_search.setAccessibleName("Search history")
        self.settings_search.textChanged.connect(self._fill_settings_list)
        listing = QListWidget()
        listing.setObjectName("settingsList")
        listing.setAccessibleName("Saved requests")
        listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        listing.setMouseTracking(True)
        listing.setItemDelegate(HistorySettingsDelegate(listing))
        listing.setMinimumHeight(160)
        use_step_scroll(listing)
        self.settings_list = listing
        self._settings_clicks = HistoryDeleteClicks(listing, self._delete_from_settings_list)
        listing.itemClicked.connect(self._open_from_settings_list)
        listing.itemActivated.connect(self._open_from_settings_list)
        self.settings_empty = muted("No saved requests yet.")
        self.settings_title = field_label("Requests")
        add_section(layout, self.settings_title, self.settings_search)
        layout.addSpacing(LIST_GAP - 6)  # day headers carry their own air above
        layout.addWidget(listing)
        layout.addWidget(self.settings_empty)
        layout.setStretchFactor(listing, 1)
        self._fill_settings_list()

        delete_all = text_link("Delete all history…", danger=True)
        self.delete_all_button = delete_all
        delete_all.setAccessibleName("Delete all history")
        delete_all.clicked.connect(self.clear_all)
        # The Settings dialog puts this link on its bottom row, next to Done, while History is open.
        self.limit.changed.connect(self._prefs_changed)
        self.age.changed.connect(self._prefs_changed)
        return page

    @staticmethod
    def _history_day(stamp: str, today) -> str:
        """Today, Yesterday, 12 November (the year only when it is not this one)."""
        try:
            day = datetime.fromisoformat(stamp[:10]).date()
        except ValueError:
            return "Earlier"
        delta = (today - day).days
        if delta == 0:
            return "Today"
        if delta == 1:
            return "Yesterday"
        return f"{day.day} {day:%B}" + ("" if day.year == today.year else f" {day.year}")

    def _fill_settings_list(self, *_: object) -> None:
        """Settings → History: every saved request, newest first, under day headers;
        a click opens it, the cross deletes it."""
        listing = self.settings_list
        needle = self.settings_search.text().casefold().strip()
        listing.clear()
        items = self.items
        today = datetime.now().date()
        last_day, shown = None, 0
        for index in range(len(items) - 1, -1, -1):
            entry = items[index]
            label = history_topic(entry['thoughts'], entry['payload'], entry['label'])
            searchable = f"{label} {entry['thoughts']} {json.dumps(entry['payload'], ensure_ascii=False)}"
            if needle and needle not in searchable.casefold():
                continue
            day = self._history_day(entry['created_at'], today)
            if day != last_day:
                header = QListWidgetItem(day, listing)
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                header.setData(DAY_ROLE, True)
                last_day = day
            item = QListWidgetItem(label, listing)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setData(DELETABLE_ROLE, True)
            item.setData(TIME_ROLE, entry['created_at'][11:16])
            item.setToolTip(f"{label}\n{entry['created_at'][:16].replace('T', ' ')}\n{entry['thoughts'][:300]}")
            shown += 1
        self.settings_title.setText(f"REQUESTS · {shown}" if shown else "REQUESTS")
        self.settings_empty.setText("No matches." if needle else "No saved requests yet.")
        self.settings_empty.setVisible(shown == 0)
        listing.setVisible(shown > 0)

    def _open_from_settings_list(self, item) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(index, int):
            self.leaveSettings.emit()
            self._on_picked(str(index))

    def _delete_from_settings_list(self, row: int) -> None:
        item = self.settings_list.item(row)
        index = item.data(Qt.ItemDataRole.UserRole) if item else None
        row_in_combo = self.combo.findData(index) if isinstance(index, int) else -1
        if row_in_combo > 0:
            self._delete_row(row_in_combo)  # not the picker's delete: that reopens the picker panel
        self._fill_settings_list()

    def _prefs_changed(self, *_: object) -> None:
        self.store.max_entries = int(self.limit.current_key())
        self.store.max_age_days = int(self.age.current_key())
        path = self._prefs_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_text(
                json.dumps({"history_max": self.store.max_entries, "history_days": self.store.max_age_days})
            )
            removed = self.store.prune()
        except (OSError, sqlite3.Error):
            self.notice.setText("Could not save the history setting.")
            self.notice.show()
            return
        if removed:
            self.items = self.store.load()
            self.shown_entry = None
            self.filter()

    def clear_all(self) -> None:
        """Delete every saved entry after an explicit confirmation: the database file is removed."""
        if not self.items:
            return
        answer = QMessageBox.question(
            self._dialog_parent,
            "Delete all history?",
            f"Delete all {len(self.items)} saved requests and prompts? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.clear()
        except OSError:
            self.notice.setText("Could not delete the history file.")
            self.notice.show()
            return
        self.items = []
        self.shown_entry = None
        self.filter()
        self.notice.setText("History deleted.")
        self.notice.show()

    def push(self, label: str, kind: str, thoughts: str, payload: dict) -> None:
        """Save a new result; it becomes the entry on screen, so prompt edits go into it."""
        label = history_topic(thoughts, payload, label)
        try:
            entry = self.store.add(label, kind, thoughts, payload)
        except (OSError, ValueError, sqlite3.Error):
            self.notice.setText("Could not save history to disk. This result is still available in this window.")
            self.notice.show()
            entry = {
                'label': label,
                'kind': kind,
                'thoughts': thoughts,
                'payload': payload,
                'created_at': datetime.now().isoformat(),
            }
        self.items.append(entry)
        self.shown_entry = len(self.items) - 1  # prompt edits are saved into this entry
        self.filter(selected=len(self.items) - 1)

    def prompt_edited(self, variant: int, text: str) -> None:
        """Remember the edit and save it shortly after typing stops."""
        if self.shown_entry is None:
            return
        self._pending_edits[(self.shown_entry, variant)] = text
        self._edit_timer.start(700)

    @staticmethod
    def _prompt_at(kind: str, payload: dict, variant: int) -> str:
        if variant == 0:
            return payload.get("zeroShotPrompt", "")
        if kind == "manual":
            return payload["variants"][variant - 1]["prompt"] if payload.get("variants") else payload["prompt"]
        return (
            payload["synthesis"]["prompt"]
            if variant == 1
            else payload["alternatives"][variant - 2]["synthesis"]["prompt"]
        )

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

    def save_edits(self) -> None:
        pending, self._pending_edits = self._pending_edits, {}
        touched: set[int] = set()
        for (entry_index, variant), text in pending.items():
            if not 0 <= entry_index < len(self.items):
                continue
            entry = self.items[entry_index]
            try:
                self._apply_prompt_edit(entry["kind"], entry["payload"], variant, text)
            except (KeyError, IndexError, TypeError):
                continue
            touched.add(entry_index)
        for entry_index in touched:
            entry = self.items[entry_index]
            if entry.get("id") is None:
                continue  # never reached the disk: the edit lives in this window only
            try:
                self.store.update_payload(entry["id"], entry["payload"])
            except (OSError, sqlite3.Error):
                self.notice.setText("Could not save your prompt edit to disk. It stays in this window.")
                self.notice.show()

    def _on_selected(self, index: int) -> None:
        item_index = self.combo.itemData(index)
        if not isinstance(item_index, int) or not 0 <= item_index < len(self.items):
            return
        entry = self.items[item_index]
        try:
            self._render(entry)
        except (KeyError, TypeError, ValueError):
            self.show_notice("Could not open this history entry: invalid data.")
            return
        self.shown_entry = item_index
        self.opened.emit(entry)

    # ── the header picker ─────────────────────────────────────────
    def _sync_picker(self) -> None:
        """Fill the history picker, newest first; searchable by topic, request and prompt text."""
        self.combo.hide()  # still drives restore
        items = []
        for index in range(len(self.items) - 1, -1, -1):
            entry = self.items[index]
            label = history_topic(entry['thoughts'], entry['payload'], entry['label'])
            request = ' '.join(entry['thoughts'].split())
            items.append(
                {
                    "key": str(index),
                    "label": label,
                    # The date, and the request when the topic does not already say it.
                    "hint": entry['created_at'][:10]
                    + ("" if request.casefold() == label.casefold() else f" · {request[:90]}"),
                    "search": json.dumps(entry['payload'], ensure_ascii=False),
                    "deletable": True,
                }
            )
        picker = self.picker
        picker.set_items(items)
        shown = self.shown_entry
        previous = picker.blockSignals(True)
        picker.set_current(str(shown) if isinstance(shown, int) and 0 <= shown < len(self.items) else "")
        picker.blockSignals(previous)
        if picker.parentWidget() is not None:  # without a parent, setVisible would open it as a window
            picker.setVisible(bool(self.items))
        self._fill_settings_list()  # Settings → History shows the same entries

    def _on_picker_delete(self, key: str) -> None:
        if not key.isdigit():
            return
        row = self.combo.findData(int(key))
        if row > 0:
            self._delete_row(row)
        # Keys are list positions, so the open panel is stale: reopen it with the remaining entries.
        picker = self.picker
        if picker._popup is not None:
            picker._popup.close()
        if self.items:
            QTimer.singleShot(0, picker._open)

    def _on_picked(self, key: str) -> None:
        if key.isdigit():
            self._open_index(int(key))
            self._sync_picker()  # the button names the entry now on screen

    def _open_index(self, item_index: int) -> None:
        self.filter("", selected=item_index)
        combo_index = self.combo.findData(item_index)
        if combo_index > 0:
            self.combo.setCurrentIndex(combo_index)
            self._on_selected(combo_index)
