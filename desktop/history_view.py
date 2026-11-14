"""Request history in the Prompta window: moved out of PromptaWindow and mixed back into it."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

try:
    from .history import history_topic
    from .settings_ui import LABEL_GAP, LIST_GAP, add_section, field_label, muted, settings_page, text_link
except ImportError:
    from history import history_topic
    from settings_ui import LABEL_GAP, LIST_GAP, add_section, field_label, muted, settings_page, text_link

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QCursor, QPainter, QFont
from PyQt6.QtWidgets import (
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

try:
    from .theme import PROMPT_TARGETS
    from .widgets import *  # noqa: F401,F403 — base widgets moved out of this file
except ImportError:
    from theme import PROMPT_TARGETS
    from widgets import *  # noqa: F401,F403
try:
    from .result_view import *  # noqa: F401,F403
    from .controls import Dropdown
except ImportError:
    from result_view import *  # noqa: F401,F403
    from controls import Dropdown


DAY_ROLE = Qt.ItemDataRole.UserRole + 42   # a day header row in Settings → History
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
            painter.drawText(rect.adjusted(self.PAD, 0, -self.PAD, -6),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, str(index.data()).upper())
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
            painter.drawText(rect.adjusted(0, 0, -self.PAD, 0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             str(index.data(TIME_ROLE) or ""))
        painter.restore()


class HistoryMixin:
    """History in the main window: search, pick, delete, clear and retention settings."""

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
        if hasattr(self, "_sync_history_row"):
            self._sync_history_row()

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
        self._filter_history(selected=current)
        if not self.history.isVisible():
            return  # PromptaWindow deletes from its history picker, which reopens itself
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
        """Retention on top (two short choices), then the requests themselves: searchable, grouped by day."""
        self._load_history_prefs()
        page, layout = settings_page("Every request you build is kept on this Mac, readable only by your account.")

        # The app's own pickers, as on Model & API, not system combo boxes.
        limits_items = [{"key": str(value), "label": label} for value, label in self.HISTORY_LIMITS]
        if not any(int(item["key"]) == self.history_store.max_entries for item in limits_items):
            limits_items.append({"key": str(self.history_store.max_entries),
                                 "label": f"Keep the newest {self.history_store.max_entries}"})
        self.history_limit = Dropdown(popup_width=260)
        self.history_limit.setAccessibleName("How many requests to keep")
        self.history_limit.set_items(limits_items)
        self.history_limit.set_current(str(self.history_store.max_entries))
        ages = [{"key": str(value), "label": label} for value, label in self.HISTORY_AGES]
        self.history_age = Dropdown(popup_width=260)
        self.history_age.setAccessibleName("Delete requests older than")
        self.history_age.set_items(ages)
        known_age = any(int(item["key"]) == self.history_store.max_age_days for item in ages)
        self.history_age.set_current(str(self.history_store.max_age_days) if known_age else ages[0]["key"])
        limits = QHBoxLayout()  # two short choices side by side, each under its own label
        limits.setSpacing(16)
        for title, combo in (("How many to keep", self.history_limit), ("Delete older than", self.history_age)):
            column = QVBoxLayout()
            column.setSpacing(LABEL_GAP)
            column.addWidget(field_label(title))
            column.addWidget(combo)
            limits.addLayout(column, 1)
        add_section(layout, None, limits, hint="Older entries are removed when a new result is saved.")

        self.history_settings_search = QLineEdit()
        self.history_settings_search.setPlaceholderText("Search requests and prompts")
        self.history_settings_search.setClearButtonEnabled(True)
        self.history_settings_search.setAccessibleName("Search history")
        self.history_settings_search.textChanged.connect(lambda _text: self._fill_history_settings_list())
        listing = QListWidget()
        listing.setObjectName("settingsList")
        listing.setAccessibleName("Saved requests")
        listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        listing.setMouseTracking(True)
        listing.setItemDelegate(HistorySettingsDelegate(listing))
        listing.setMinimumHeight(160)
        use_step_scroll(listing)
        self.history_settings_list = listing
        self._history_settings_clicks = HistoryDeleteClicks(listing, self._delete_from_settings_list)
        listing.itemClicked.connect(self._open_from_settings_list)
        listing.itemActivated.connect(self._open_from_settings_list)
        self.history_settings_empty = muted("No saved requests yet.")
        self.history_settings_title = field_label("Requests")
        add_section(layout, self.history_settings_title, self.history_settings_search)
        layout.addSpacing(LIST_GAP - 6)  # day headers carry their own air above
        layout.addWidget(listing)
        layout.addWidget(self.history_settings_empty)
        layout.setStretchFactor(listing, 1)
        self._fill_history_settings_list()

        delete_all = text_link("Delete all history…", danger=True)
        self.delete_all_history_button = delete_all
        delete_all.setAccessibleName("Delete all history")
        delete_all.clicked.connect(self.clear_history)
        # The Settings dialog puts this link on its bottom row, next to Done, while History is open.
        self.history_limit.changed.connect(self._history_prefs_changed)
        self.history_age.changed.connect(self._history_prefs_changed)
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

    def _fill_history_settings_list(self) -> None:
        """Settings → History: every saved request, newest first, under day headers; a click opens it, the cross deletes it."""
        listing = getattr(self, "history_settings_list", None)
        if listing is None:
            return
        needle = self.history_settings_search.text().casefold().strip()
        listing.clear()
        items = getattr(self, "_history_items", [])
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
        self.history_settings_title.setText(f"REQUESTS · {shown}" if shown else "REQUESTS")
        self.history_settings_empty.setText("No matches." if needle else "No saved requests yet.")
        self.history_settings_empty.setVisible(shown == 0)
        listing.setVisible(shown > 0)

    def _open_from_settings_list(self, item) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(index, int):
            self.settings_dialog.accept()
            self._on_history_picked(str(index))

    def _delete_from_settings_list(self, row: int) -> None:
        item = self.history_settings_list.item(row)
        index = item.data(Qt.ItemDataRole.UserRole) if item else None
        row_in_combo = self.history.findData(index) if isinstance(index, int) else -1
        if row_in_combo > 0:
            self._delete_history(row_in_combo)  # not the picker's delete: that reopens the picker panel
        self._fill_history_settings_list()

    def _history_prefs_changed(self, *_: object) -> None:
        self.history_store.max_entries = int(self.history_limit.current_key())
        self.history_store.max_age_days = int(self.history_age.current_key())
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
        self._filter_history(selected=len(self._history_items) - 1)

    def _flag_outdated(self, payload: dict) -> None:
        """A saved result built under earlier pipeline rules says so, and how to get a current one."""
        current = getattr(self, "prompt_version", "")
        if not current or payload.get("promptVersion") == current:
            return
        note = QLabel("Built with earlier Prompta rules. Build prompt makes it again with the current ones.")
        note.setObjectName("warn")
        note.setWordWrap(True)
        self.output_layout.insertWidget(0, note)

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
        self._flag_outdated(payload)
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
        self._open_mode = selected == "openModel"
        for key in PROMPT_TARGETS:
            getattr(self, f"{key}_only").setChecked(key == selected)
        if hasattr(self, "_sync_segments"):
            self._sync_segments()
