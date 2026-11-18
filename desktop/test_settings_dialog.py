"""The Settings dialog and the About page on their own: footers per tab, what runs on open, the backdrop."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QVBoxLayout, QWidget  # noqa: E402

from about_page import AboutPage  # noqa: E402
from result_view import CONTROL_HEIGHT  # noqa: E402
from settings_dialog import SettingsDialog  # noqa: E402


def page_with_field() -> tuple[QWidget, QLineEdit]:
    page = QWidget()
    field = QLineEdit()
    QVBoxLayout(page).addWidget(field)
    return page, field


class SettingsDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = SettingsDialog()
        self.first, self.first_field = page_with_field()
        self.second, _ = page_with_field()
        self.footer = QLabel("2 entries")
        self.shown = Mock()
        self.dialog.add_page(self.first, "First", focus=self.first_field)
        self.dialog.add_page(self.second, "Second", footer=self.footer, on_show=self.shown, backdrop=True)

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()

    def test_fields_get_one_control_height(self):
        self.assertEqual(self.first_field.minimumHeight(), CONTROL_HEIGHT)
        self.assertEqual(self.first_field.maximumHeight(), CONTROL_HEIGHT)
        self.assertEqual(self.dialog.done_button.height(), CONTROL_HEIGHT)

    def test_footer_and_backdrop_follow_the_open_tab(self):
        self.assertTrue(self.footer.isHidden())
        self.assertTrue(self.dialog.backdrop.isHidden())
        self.dialog.tabs.setCurrentIndex(1)
        self.assertFalse(self.footer.isHidden())
        self.assertFalse(self.dialog.backdrop.isHidden())
        self.shown.assert_called_once()
        self.dialog.tabs.setCurrentIndex(0)
        self.assertTrue(self.footer.isHidden())

    def test_open_runs_the_tab_refresh_and_focus(self):
        self.dialog.tabs.setCurrentIndex(1)
        self.shown.reset_mock()
        self.dialog.open()
        self.shown.assert_called_once()
        self.dialog.accept()
        self.assertFalse(self.dialog.isVisible())

    def test_backdrop_covers_the_dialog_after_a_resize(self):
        self.dialog.resize(900, 700)
        self.dialog.show()
        self.app.processEvents()
        self.assertEqual(self.dialog.backdrop.geometry(), self.dialog.rect())


class AboutPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = AboutPage("9.9.9", "Someone", "https://example.test/someone")

    def tearDown(self):
        self.page.deleteLater()

    def test_credits_and_source_link(self):
        self.assertIn("Someone", self.page.author.text())
        self.assertNotIn("License", self.page.author.text())
        self.assertIs(self.page.footer, self.page.author)


if __name__ == "__main__":
    unittest.main()
