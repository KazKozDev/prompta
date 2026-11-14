"""History on its own: a real store in a temp folder, a fake renderer, no window."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

from history import HistoryStore  # noqa: E402
from history_view import HistoryView  # noqa: E402

PAYLOAD = {"synthesis": {"prompt": "Original prompt"}, "zeroShotPrompt": "Task"}


class HistoryViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = HistoryStore(Path(self.temp.name) / "history.sqlite3")
        self.host = QWidget()
        self.rendered: list[dict] = []
        self.opened: list[dict] = []
        self.history = HistoryView(self.store, self.render, self.host)
        self.history.opened.connect(self.opened.append)
        self.history.load()

    def tearDown(self):
        self.host.deleteLater()
        self.temp.cleanup()

    def render(self, entry: dict) -> None:
        if entry["payload"].get("broken"):
            raise KeyError("synthesis")
        self.rendered.append(entry)

    def test_push_lists_newest_first_and_marks_the_shown_entry(self):
        self.history.push("first", "pipeline", "Write a haiku", dict(PAYLOAD))
        self.history.push("second", "pipeline", "Summarise notes", dict(PAYLOAD))
        self.assertEqual(len(self.history.items), 2)
        self.assertEqual(self.history.shown_entry, 1)
        self.assertEqual([item["key"] for item in self.history.picker._items], ["1", "0"])
        self.assertEqual(self.history.settings_title.text(), "REQUESTS · 2")
        self.assertEqual(len(self.store.load()), 2, "saved to disk")

    def test_picking_renders_then_announces(self):
        self.history.push("first", "pipeline", "Write a haiku", dict(PAYLOAD))
        self.history.deselect()
        self.history.picker._choose("0")
        self.assertEqual([e["thoughts"] for e in self.rendered], ["Write a haiku"])
        self.assertEqual([e["thoughts"] for e in self.opened], ["Write a haiku"])
        self.assertEqual(self.history.shown_entry, 0)

    def test_an_entry_that_cannot_render_says_so_and_is_not_shown(self):
        self.history.push("bad", "pipeline", "Broken entry", {"broken": True})
        self.history.deselect()
        self.history.picker._choose("0")
        self.assertEqual(self.opened, [])
        self.assertIsNone(self.history.shown_entry)
        self.assertEqual(self.history.notice.text(), "Could not open this history entry: invalid data.")

    def test_prompt_edits_are_saved_after_the_pause_and_on_flush(self):
        self.history.push("first", "pipeline", "Write a haiku", dict(PAYLOAD, synthesis={"prompt": "Original"}))
        self.history.prompt_edited(1, "Edited prompt")
        self.assertTrue(self.history._edit_timer.isActive())
        self.history.flush_edits()
        payload = self.store.load()[0]["payload"]
        self.assertEqual(payload["synthesis"]["prompt"], "Edited prompt")
        self.assertEqual(payload["originalPrompts"], {"1": "Original"}, "the model's text can be restored")

    def test_delete_from_settings_and_clear_all(self):
        for name in ("one", "two"):
            self.history.push(name, "pipeline", f"Request {name}", dict(PAYLOAD))
        row = next(
            i
            for i in range(self.history.settings_list.count())
            if self.history.settings_list.item(i).data(Qt.ItemDataRole.UserRole) == 0
        )
        self.history._delete_from_settings_list(row)
        self.assertEqual([e["thoughts"] for e in self.history.items], ["Request two"])
        with patch("PyQt6.QtWidgets.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
            self.history.clear_all()
        self.assertEqual(len(self.history.items), 1, "nothing goes without a yes")
        with patch("PyQt6.QtWidgets.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            self.history.clear_all()
        self.assertEqual(self.history.items, [])
        self.assertEqual(self.history.notice.text(), "History deleted.")

    def test_retention_choice_is_saved_next_to_the_store(self):
        self.history.limit.set_current("100", emit=True)
        self.assertEqual(self.store.max_entries, 100)
        self.assertIn('"history_max": 100', (Path(self.temp.name) / "settings.json").read_text())


if __name__ == "__main__":
    unittest.main()
