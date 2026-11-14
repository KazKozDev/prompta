"""Dictation on demand: what counts as an installed model, the download's last step, Settings → Dictation,
the microphone without a model, and the standalone app's worker entry point. No network, no microphone."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTA_LOG_DIR"] = tempfile.mkdtemp()  # never the real dictation log
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtWidgets import QApplication

import dictation
from dictation import FILES, DictationPage, ModelDownload, installed_model, is_complete, model_dir


def fill(folder: Path, sizes: dict[str, int]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, size in sizes.items():
        with open(folder / name, "wb") as handle:
            handle.truncate(size)  # sparse: the right size without writing half a gigabyte


class DictationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"PROMPTA_MODELS_DIR": self.home.name})
        self.env.start()
        self.legacy = patch.object(dictation, "LEGACY_MODEL", Path(self.home.name) / "no-legacy")
        self.legacy.start()

    def tearDown(self):
        self.legacy.stop()
        self.env.stop()
        self.home.cleanup()

    def test_only_a_complete_download_counts_as_installed(self):
        self.assertIsNone(installed_model())
        fill(model_dir(), {**FILES, "model.bin": FILES["model.bin"] - 1})  # cut off
        self.assertFalse(is_complete(model_dir()))
        self.assertIsNone(installed_model())
        fill(model_dir(), {name: size for name, size in FILES.items() if name != "tokenizer.json"})
        (model_dir() / "tokenizer.json").unlink()
        self.assertIsNone(installed_model(), "a missing file is not a model")
        fill(model_dir(), FILES)
        self.assertEqual(installed_model(), model_dir())

    def test_repository_model_still_works_from_the_sources(self):
        legacy = Path(self.home.name) / "legacy"
        fill(legacy, {name: 1 for name in FILES})
        with patch.object(dictation, "LEGACY_MODEL", legacy):
            self.assertEqual(installed_model(), legacy)
            with patch.object(dictation, "FROZEN", True):
                self.assertIsNone(installed_model(), "the standalone app has no repository")

    def test_download_renames_into_place_only_at_the_end_and_cancel_cleans_up(self):
        download = ModelDownload()
        download.partial = Path(self.home.name) / "whisper-small.part"
        fill(download.partial, FILES)
        finished = []
        download.finished.connect(lambda: finished.append(True))
        download.queue = []
        download._next()  # nothing left to fetch: install
        self.assertEqual(finished, [True])
        self.assertEqual(installed_model(), model_dir())
        self.assertFalse(download.partial.exists())
        fill(download.partial, {"config.json": 10})
        download.cancel()
        self.assertFalse(download.partial.exists(), "a cancelled download leaves no .part folder")

    def test_page_offers_download_then_remove(self):
        dictating = [False]
        page = DictationPage(lambda: dictating[0])
        self.assertEqual(page.status.text(), "Not downloaded")
        self.assertFalse(page.download_button.isHidden())
        self.assertTrue(page.remove_button.isHidden())
        fill(model_dir(), FILES)
        page.refresh()
        self.assertEqual(page.status.text(), "Whisper small · ready")
        self.assertTrue(page.download_button.isHidden())
        self.assertFalse(page.remove_button.isHidden())
        dictating[0] = True
        page.remove_button.click()
        self.assertEqual(page.hint.text(), "Stop dictation first.")
        self.assertEqual(installed_model(), model_dir())
        dictating[0] = False
        page.remove_button.click()
        self.assertIsNone(installed_model())
        self.assertEqual(page.status.text(), "Not downloaded")
        page.close()

    def test_page_shows_progress_and_failures(self):
        page = DictationPage(lambda: False)
        page._progress(dictation.TOTAL // 2)
        self.assertRegex(page.status.text(), r"^Downloading… 50 % of \d+ MB$")
        page._failed("Download failed: offline")
        self.assertEqual(page.hint.text(), "Download failed: offline")
        self.assertFalse(page.download_button.isHidden(), "it can be tried again")
        page.close()

    def test_microphone_without_a_model_asks_for_the_download(self):
        from widgets import ThoughtsEdit

        editor = ThoughtsEdit()
        requested = []
        editor.dictationSetupRequested.connect(lambda: requested.append(True))
        with patch("widgets.worker_command", return_value=("python", ["voice_input.py"])):
            editor._toggle_dictation()
        self.assertEqual(requested, [True])
        self.assertIsNone(editor.voice_process, "no worker starts without a model")
        self.assertIn("Settings → Dictation", editor.toolTip())
        editor.close()

    def test_microphone_passes_the_model_to_the_worker(self):
        from widgets import ThoughtsEdit

        fill(model_dir(), FILES)
        editor = ThoughtsEdit()
        with (
            patch("widgets.worker_command", return_value=("/bin/cat", [])),
            patch("widgets.QProcess.start"),
        ):
            editor._toggle_dictation()
        process = editor.voice_process
        self.assertIsNotNone(process)
        self.assertEqual(process.processEnvironment().value("PROMPTA_WHISPER_MODEL"), str(model_dir()))
        editor.voice_process = None
        editor.close()

    def test_standalone_worker_runs_before_any_window(self):
        import app

        with (
            patch.object(sys, "argv", ["Prompta", "--voice-worker"]),
            patch("voice_input.run", return_value=0) as run,
            patch.object(app, "make_app", side_effect=AssertionError("no QApplication in the worker")),
            patch.object(app, "SingleInstance", side_effect=AssertionError("no single-instance check")),
        ):
            self.assertEqual(app.main(), 0)
        run.assert_called_once()

    def test_frozen_worker_is_the_app_itself(self):
        with patch.object(dictation, "FROZEN", True), patch.object(dictation, "runtime_bundled", return_value=True):
            self.assertEqual(dictation.worker_command(), (sys.executable, ["--voice-worker"]))
        with patch.object(dictation, "FROZEN", True), patch.object(dictation, "runtime_bundled", return_value=False):
            self.assertIsNone(dictation.worker_command())


if __name__ == "__main__":
    unittest.main()
