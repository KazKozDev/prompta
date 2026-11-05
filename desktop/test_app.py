"""Native UI and subprocess lifecycle smoke tests (run with QT_QPA_PLATFORM=offscreen)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import subprocess
import tempfile
from pathlib import Path
from history import HistoryStore
import unittest
from unittest.mock import Mock, patch

from app import QApplication, MainWindow, Worker, QPushButton


class DesktopSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = HistoryStore(Path(self.temp.name) / 'history.sqlite3')
        self.store_patch = patch('app.HistoryStore', return_value=self.store)
        self.store_patch.start()

    def tearDown(self):
        self.store_patch.stop()
        self.temp.cleanup()

    def test_history_survives_restart_and_search_restores_correct_query(self):
        def window():
            with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
                return MainWindow()
        first = window()
        for query, prompt in [('Чётные числа', 'Первый промпт'), ('Письмо', 'Уникальный второй промпт')]:
            first.thoughts.setPlainText(query)
            first.on_finished({'ok': True, 'manual': {
                'technique': {'key': 'test', 'name': 'Same technique', 'category': 'test'},
                'prompt': prompt,
                'config': {'temperature': 0.2, 'top_p': 0.95, 'rationale': 'test'},
                'source_ref': 'test',
            }})
        first.close()
        reopened = window()
        self.assertEqual(reopened.history.count(), 3)
        reopened.history_search.setText('УНИКАЛЬНЫЙ')
        self.assertEqual(reopened.history.count(), 2)
        reopened.history.setCurrentIndex(1)
        self.assertEqual(reopened.prompt_edit.toPlainText(), 'Уникальный второй промпт')
        self.assertEqual(reopened.thoughts.toPlainText(), 'Письмо')
        reopened.history_search.setText('чётные')
        self.assertEqual(reopened.history.count(), 2)
        reopened.history.setCurrentIndex(1)
        self.assertEqual(reopened.prompt_edit.toPlainText(), 'Первый промпт')
        reopened.history_search.setText('нет совпадений')
        self.assertEqual(reopened.history.count(), 1)
        self.assertEqual(len(self.store.load()), 2)
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        reopened.close()

    def test_corrupt_history_is_not_overwritten(self):
        self.store.path.write_bytes(b'broken database')
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
        self.assertFalse(window.history_notice.isHidden())
        self.assertEqual(self.store.path.read_bytes(), b'broken database')
        window.close()

    def test_api_settings_and_thoughts_label(self):
        from app import QLabel, QLineEdit
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
        labels = {label.text(): label for label in window.findChildren(QLabel)}
        self.assertEqual(labels['THOUGHTS'].objectName(), labels['TECHNIQUE'].objectName())
        self.assertFalse(window.settings_button.icon().isNull())
        self.assertTrue(window.settings_dialog.isAncestorOf(window.api_key))
        self.assertFalse(window.settings_dialog.isAncestorOf(window.model))
        self.assertEqual(window.api_key.echoMode(), QLineEdit.EchoMode.Password)
        window.settings_button.click()
        self.assertTrue(window.settings_dialog.isVisible())
        window.api_key.setText('synthetic-test-key')
        window.settings_dialog.accept()
        self.assertFalse(window.settings_dialog.isVisible())
        window.thoughts.setPlainText('Synthetic test')
        window.provider.set_current('openai')
        window.model.set_current('synthetic-model')
        with patch('app.Worker') as worker_type:
            window.run_pipeline()
            payload = worker_type.call_args.args[0]
            self.assertEqual(payload['apiKey'], 'synthetic-test-key')
            self.assertEqual(payload['model'], 'synthetic-model')
            self.assertEqual(payload['provider'], 'openai')
        self.assertFalse(self.store.path.exists())
        window.close()

    def test_cancel_before_launch_does_not_spawn(self):
        worker = Worker({})
        responses = []
        worker.finished_ok.connect(responses.append)
        worker.cancel()
        with patch('app.subprocess.Popen') as spawn:
            worker.run()
        spawn.assert_not_called()
        self.assertEqual(responses, [{'ok': False, 'error': 'Cancelled'}])

    def test_timeout_kills_and_reaps_process(self):
        proc = Mock()
        proc.communicate.side_effect = [subprocess.TimeoutExpired('node', 900), ('', '')]
        proc.poll.return_value = None
        worker = Worker({})
        responses = []
        worker.finished_ok.connect(responses.append)
        with patch('app.subprocess.Popen', return_value=proc):
            worker.run()
        proc.kill.assert_called_once()
        self.assertEqual(proc.communicate.call_count, 2)
        self.assertFalse(responses[0]['ok'])

    def test_each_variant_copies_its_own_prompt(self):
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
        config = {'temperature': 0.2, 'top_p': 0.95, 'max_tokens': '1024', 'rationale': 'test'}
        choice = {'name': 'Test', 'key': 'test', 'confidence': 1, 'reason': 'test', 'whyNotCheaper': 'test'}
        def synthesis(text):
            return {'prompt': text, 'config': config, 'warnings': []}
        window.render({
            'brief': {'goal': 'test', 'task_type': 'classification', 'language': 'ru',
                      'stakes': 'low', 'output_format': 'JSON', 'assumptions': []},
            'choice': choice, 'synthesis': synthesis('First prompt'), 'rejected': [],
            'alternatives': [
                {'choice': choice, 'synthesis': synthesis('Second prompt')},
                {'choice': choice, 'synthesis': synthesis('Third prompt')},
            ],
        })
        buttons = [b for b in window.output_holder.findChildren(QPushButton) if b.text() == 'Copy']
        self.assertEqual(len(buttons), 3)
        clipboard = Mock()
        with patch('app.QGuiApplication.clipboard', return_value=clipboard):
            for index in (2, 0, 1, 2):
                buttons[index].click()
                clipboard.setText.assert_called_with(['First prompt', 'Second prompt', 'Third prompt'][index])
        window.close()

    def test_manual_history_error_and_input_validation(self):
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
        window.run_pipeline()
        self.assertIsNone(window.worker)
        self.assertEqual(window.status.text(), 'Enter your thoughts')
        manual = {
            'technique': {'key': 'test', 'name': 'Test', 'category': 'test'},
            'prompt': 'Синтетический промпт для классификации чётных и нечётных чисел.',
            'config': {'temperature': 0.2, 'top_p': 0.95, 'rationale': 'test'},
            'source_ref': 'test',
        }
        window.on_finished({'ok': True, 'manual': manual})
        self.assertEqual(window.history.count(), 2)
        self.assertEqual(window.prompt_edit.toPlainText(), manual['prompt'])
        window.on_finished({'ok': False, 'error': 'synthetic error'})
        self.assertTrue(window.run_button.isEnabled())
        self.assertFalse(window.cancel_button.isEnabled())
        window._on_history_selected(1)
        self.assertEqual(window.prompt_edit.toPlainText(), manual['prompt'])
        window.close()


if __name__ == '__main__':
    unittest.main()
