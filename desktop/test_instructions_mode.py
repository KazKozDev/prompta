"""Project mode: the third switch segment, the instructions request, its result, history and saving."""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile

os.environ['PROMPTA_STATE_FILE'] = os.path.join(tempfile.mkdtemp(), 'generator.json')  # never the real app state
from PyQt6.QtCore import QSettings

QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())  # never real prefs
os.environ['PROMPTA_LOG_DIR'] = tempfile.mkdtemp()
os.environ['PROMPTA_MODELS_DIR'] = tempfile.mkdtemp()

import gc
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QApplication, QLabel

from app import PromptaWindow
from generator_settings import GeneratorSettings
from history import HistoryStore
from history_view import HistoryView
from instructions_view import save_instructions
from skill_mode import INSTRUCTIONS_MODE, PROMPT_MODE, SKILL_MODE

INSTRUCTIONS = {
    'text': '---\nalwaysApply: true\n---\n# Shop\n\n- Test: `pnpm test`\n',
    'target': 'cursor',
    'fileName': '.cursor/rules/project.mdc',
    'check': {'valid': True, 'errors': [], 'warnings': ['a warning'], 'lines': 3},
    'repaired': False,
    'rules': [
        {'id': 'r', 'rule_text': 'Rule text.', 'source_url': 'https://cursor.com/docs/rules', 'source_title': 'Rules'}
    ],
    'verifiedAt': '2026-11-15',
    'usage': {'calls': 1, 'inputTokens': 10, 'outputTokens': 20},
}


class InstructionsModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = HistoryStore(Path(self.temp.name) / 'history.sqlite3')
        self.patches = [
            patch('app.HistoryStore', return_value=self.store),
            patch('app.load_local_providers', return_value={}),
            patch.multiple('keychain', load=Mock(return_value=''), save=Mock(return_value=True), forget=Mock()),
            patch('generator_settings.ModelsLoader'),
            patch.object(GeneratorSettings, 'load_models'),
            patch.object(PromptaWindow, 'load_techniques'),
        ]
        for p in self.patches:
            p.start()
        self.window = PromptaWindow()

    def tearDown(self):
        self.window.close()
        for p in reversed(self.patches):
            p.stop()
        GeneratorSettings._running_loaders.clear()
        gc.collect()
        self.app.processEvents()
        self.temp.cleanup()

    def test_switch_shows_the_file_picker_and_view_only_in_project_mode(self):
        w = self.window
        w.mode_switch.set_mode(INSTRUCTIONS_MODE)
        self.assertEqual(w.mode_switch.mode(), INSTRUCTIONS_MODE)
        self.assertFalse(w.instruction_target.isHidden())
        self.assertFalse(w.instructions_view.isHidden())
        self.assertTrue(w.surface_selector.isHidden())
        self.assertTrue(w.target_selector.isHidden())
        self.assertTrue(w.result_column.isHidden())
        self.assertEqual(w.run_button.text(), 'Build file   ⌘↵')
        w.mode_switch.set_mode(SKILL_MODE)
        self.assertTrue(w.instruction_target.isHidden())
        self.assertFalse(w.surface_selector.isHidden())
        w.mode_switch.set_mode(PROMPT_MODE)
        self.assertFalse(w.target_selector.isHidden())
        self.assertTrue(w.instructions_view.isHidden())

    def test_request_carries_only_the_instructions_target(self):
        w = self.window
        w.mode_switch.set_mode(INSTRUCTIONS_MODE)
        w.instruction_target.set_target('claudeMd')
        w.thoughts.setPlainText('pnpm shop')
        with (
            patch.object(w.generator, 'request', return_value=({'provider': 'ollama', 'model': 'm'}, '')),
            patch('app.Worker') as worker,
        ):
            w.run_pipeline()
        payload = worker.call_args.args[0]
        self.assertEqual(
            payload, {'thoughts': 'pnpm shop', 'provider': 'ollama', 'model': 'm', 'instructions': 'claudeMd'}
        )

    def test_result_renders_saves_to_history_and_restores(self):
        w = self.window
        w.mode_switch.set_mode(INSTRUCTIONS_MODE)
        w._active_thoughts = 'shop rules'
        w.on_finished({'ok': True, 'instructions': dict(INSTRUCTIONS)})
        self.assertEqual(w.instructions_view.editor.toPlainText(), INSTRUCTIONS['text'])
        self.assertIn('.cursor/rules/project.mdc · ready', w.status.text())
        saved = self.store.load()[0]
        self.assertEqual((saved['kind'], saved['payload']['fileName']), ('instructions', '.cursor/rules/project.mdc'))
        w.mode_switch.set_mode(PROMPT_MODE)
        w.instruction_target.set_target('agentsMd')
        w._render_history_entry({'kind': 'instructions', 'thoughts': 'shop rules', 'payload': dict(INSTRUCTIONS)})
        self.assertEqual(w.mode_switch.mode(), INSTRUCTIONS_MODE)
        self.assertEqual(w.instruction_target.target(), 'cursor')
        self.assertEqual(w.instructions_view.editor.toPlainText(), INSTRUCTIONS['text'])

    def test_an_error_shows_in_the_project_view(self):
        w = self.window
        w.mode_switch.set_mode(INSTRUCTIONS_MODE)
        w.on_finished({'ok': False, 'error': 'model gone'})
        errors = [label.text() for label in w.instructions_view.findChildren(QLabel, 'error')]
        self.assertIn('Error: model gone', errors)

    def test_edits_go_into_the_file_text(self):
        payload = dict(INSTRUCTIONS)
        HistoryView._apply_prompt_edit('instructions', payload, 0, 'edited')
        self.assertEqual(payload['text'], 'edited')
        self.assertEqual(payload['originalPrompts'], {'0': INSTRUCTIONS['text']})

    def test_save_writes_the_file_at_its_project_path(self):
        path = save_instructions(Path(self.temp.name), '.cursor/rules/project.mdc', INSTRUCTIONS['text'])
        self.assertEqual(path, Path(self.temp.name) / '.cursor' / 'rules' / 'project.mdc')
        self.assertEqual(path.read_text(encoding='utf-8'), INSTRUCTIONS['text'])


if __name__ == '__main__':
    unittest.main()
