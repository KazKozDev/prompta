"""The graphite title bar must leave non-Cocoa platforms alone: offscreen, winId() is no NSView and
messaging it crashed screenshots.py and the CI screenshot step."""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QWidget

import mac_titlebar


class TitleBarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_offscreen_windows_are_not_painted_and_objc_is_not_touched(self):
        self.assertNotEqual(QApplication.platformName(), 'cocoa')
        with patch.object(mac_titlebar, '_runtime', side_effect=AssertionError('Objective-C called offscreen')):
            mac_titlebar.paint_all_title_bars(self.app)
            window = QWidget()
            window.show()
            self.app.processEvents()
            self.assertFalse(window.property('graphiteTitleBar'))
            self.assertFalse(mac_titlebar.paint_title_bar(window))
            window.close()
        self.app.removeEventFilter(self.app.title_bar_painter)


if __name__ == '__main__':
    unittest.main()
