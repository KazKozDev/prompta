"""Shared setup for the PromptaWindow tests (QT_QPA_PLATFORM=offscreen): temporary state, no real prefs or Keychain."""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile as _tempfile

os.environ['PROMPTA_STATE_FILE'] = os.path.join(_tempfile.mkdtemp(), 'generator.json')  # never the real app state
from PyQt6.QtCore import QSettings as _QSettings

_QSettings.setPath(
    _QSettings.Format.IniFormat, _QSettings.Scope.UserScope, _tempfile.mkdtemp()
)  # never touch real prefs
import os as _os

_os.environ['PROMPTA_LOG_DIR'] = _tempfile.mkdtemp()  # nor the real dictation log
_os.environ['PROMPTA_MODELS_DIR'] = _tempfile.mkdtemp()  # nor the downloaded Whisper model
import gc
import tempfile
from pathlib import Path
from history import HistoryStore
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QApplication
from app import PromptaWindow
from generator_settings import GeneratorSettings
from PyQt6.QtCore import Qt


def app_selectable():
    return Qt.ItemFlag.ItemIsSelectable


class WindowTestCase(unittest.TestCase):
    """Each test starts from a first launch with a temporary history and no real Keychain or network."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from mcp_settings import prefs

        prefs().remove(GeneratorSettings.GENERATOR_PREFS)  # each test starts from a first launch
        self.temp = tempfile.TemporaryDirectory()
        self.store = HistoryStore(Path(self.temp.name) / 'history.sqlite3')
        self.store_patch = patch('app.HistoryStore', return_value=self.store)
        self.store_patch.start()
        self.local_patch = patch(
            'app.load_local_providers', return_value={}
        )  # the real personal file stays out of tests
        self.local_patch.start()
        # The real macOS Keychain stays out of tests too: no read, no write, no delete.
        self.keychain_patch = patch.multiple(
            'keychain', load=Mock(return_value=''), save=Mock(return_value=True), forget=Mock()
        )
        self.keychain_patch.start()
        # Nor the network: a provider switch would start a real model-list fetch that outlives the test.
        self.loader_patch = patch('generator_settings.ModelsLoader')
        self.loader_patch.start()

    def tearDown(self):
        self.loader_patch.stop()
        self.keychain_patch.stop()
        GeneratorSettings._running_loaders.clear()
        # Collect and deliver what the test left behind now, so a late callback into a deleted widget fails here.
        gc.collect()
        self.app.processEvents()
        self.local_patch.stop()
        self.store_patch.stop()
        self.temp.cleanup()

    def _prompta_window(self):
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            return PromptaWindow()

    def cls_app_process(self):
        for _ in range(2):
            self.app.processEvents()
