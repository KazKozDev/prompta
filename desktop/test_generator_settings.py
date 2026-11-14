"""Settings → Model & API on its own: keys, per-provider state, saved choice. No window, no real Keychain,
no network, no real preferences."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTA_STATE_FILE"] = os.path.join(tempfile.mkdtemp(), "generator.json")  # never the real app state
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtCore import QSettings  # noqa: E402

QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())  # never real prefs

from PyQt6.QtWidgets import QApplication  # noqa: E402

from generator_settings import GeneratorSettings  # noqa: E402
from mcp_settings import prefs  # noqa: E402
from theme import COMPATIBLE  # noqa: E402

PERSONAL = {
    "meta": {
        "key": "meta",
        "label": "Meta (Muse Spark)",
        "base_url": "https://api.meta.ai/v1",
        "models": ["muse-spark-1.3"],
        "api_key": "file-key",
    }
}


class GeneratorSettingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        prefs().remove(GeneratorSettings.GENERATOR_PREFS)
        self.saved_keys: dict[str, str] = {}
        self.keychain = patch.multiple(
            "keychain",
            load=Mock(side_effect=lambda provider: self.saved_keys.get(provider, "")),
            save=Mock(side_effect=lambda provider, key: self.saved_keys.__setitem__(provider, key) or True),
            forget=Mock(side_effect=lambda provider: self.saved_keys.pop(provider, None)),
        )
        self.keychain.start()
        self.loader = patch("generator_settings.ModelsLoader")  # no network
        self.loader.start()
        self.page = GeneratorSettings(PERSONAL)
        self.notices: list[str] = []
        self.page.notice.connect(self.notices.append)

    def tearDown(self):
        self.page.deleteLater()
        self.loader.stop()
        self.keychain.stop()
        GeneratorSettings._running_loaders.clear()

    def test_ollama_needs_no_key(self):
        fields, missing = self.page.request()
        self.assertEqual(missing, "")
        self.assertEqual(fields["provider"], "ollama")
        self.assertEqual(fields["apiKey"], "")
        self.assertIn("Generator model:", self.page.model_line())

    def test_cloud_provider_asks_for_a_key_and_remembers_it_only_when_asked(self):
        self.page.provider.set_current("openai", emit=True)
        self.page.model.set_current("gpt-x")
        self.assertEqual(self.page.request(), ({}, "Add an API key in Settings"))
        self.page.api_key.setText("k-1")
        self.assertEqual(self.page.request()[0]["apiKey"], "k-1")
        self.assertEqual(self.saved_keys, {}, "not remembered unless the box is ticked")
        self.page.remember_key.setChecked(True)
        self.assertEqual(self.saved_keys, {"openai": "k-1"})
        self.page.remember_key.setChecked(False)
        self.assertEqual(self.saved_keys, {}, "unticking forgets the saved key")

    def test_compatible_server_needs_its_url_and_a_typed_model(self):
        self.page.provider.set_current(COMPATIBLE, emit=True)
        self.assertTrue(self.page.model_name.isVisibleTo(self.page))
        self.assertFalse(self.page.model.isVisibleTo(self.page))
        self.page.model_name.setText("qwen3")
        self.assertEqual(self.page.request(), ({}, "Add the server URL in Settings"))
        self.page.model_base_url.setText("http://127.0.0.1:8080/v1")
        fields, missing = self.page.request()
        self.assertEqual((fields["provider"], fields["model"], missing), ("openai", "qwen3", ""))

    def test_personal_provider_brings_its_models_url_and_key(self):
        self.page.provider.set_current("meta", emit=True)
        self.assertEqual(self.page.model.current_key(), "muse-spark-1.3")
        self.assertEqual(self.page.api_key.text(), "file-key")
        self.assertFalse(self.page.remember_key.isChecked(), "a key from the file is not a Keychain key")
        self.assertEqual(self.page.for_mcp()[0], "openai")
        self.assertEqual(self.page.key_missing_for_mcp(), "", "the MCP server reads the same file")

    def test_each_provider_keeps_its_own_model_and_url(self):
        self.page.provider.set_current("openai", emit=True)
        self.page._on_models_loaded(["gpt-a", "gpt-b"], "openai", "provider")
        self.page.model.set_current("gpt-b")
        self.page.model_base_url.setText("https://proxy.test/v1")
        self.page.provider.set_current("ollama", emit=True)
        self.assertEqual(self.page.model_base_url.text(), "")
        self.page.provider.set_current("openai", emit=True)
        self.assertEqual(self.page.model.current_key(), "gpt-b")
        self.assertEqual(self.page.model_base_url.text(), "https://proxy.test/v1")

    def test_a_late_model_list_for_another_provider_is_kept_for_later(self):
        self.page.provider.set_current("gemini", emit=True)
        self.page._on_models_loaded(["gpt-late"], "openai", "provider")
        self.assertNotIn("gpt-late", [item["key"] for item in self.page.model._items])
        self.page.provider.set_current("openai", emit=True)
        self.assertEqual(self.page.model.current_key(), "gpt-late")

    def test_the_choice_survives_a_restart_without_saving_while_restoring(self):
        self.page.provider.set_current("anthropic", emit=True)
        self.page._on_models_loaded(["claude-a"], "anthropic", "provider")
        self.page.save()
        again = GeneratorSettings(PERSONAL)
        try:
            with patch.object(QSettings, "setValue") as written:
                again.restore()
            written.assert_not_called()  # replaying the last choice writes nothing back
            self.assertEqual(again.provider.current_key(), "anthropic")
        finally:
            again.deleteLater()

    def test_keychain_failure_is_reported(self):
        self.page.provider.set_current("openai", emit=True)
        self.page.api_key.setText("k-2")
        with patch("keychain.save", return_value=False):
            self.page.remember_key.setChecked(True)
        self.assertEqual(self.notices, ["Could not save the key to Keychain"])


if __name__ == "__main__":
    unittest.main()
