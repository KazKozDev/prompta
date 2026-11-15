"""Agent mode: the fourth switch segment, the agent request, its result, history and saving."""

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
from agent_view import agent_file_name
from skill_mode import AGENT_MODE, INSTRUCTIONS_MODE, PROMPT_MODE

AGENT = {
    'text': '---\nname: code-reviewer\ndescription: Reviews code\nreadonly: true\n---\nYou review code.\n',
    'target': 'cursor',
    'name': 'code-reviewer',
    'fileName': '.cursor/agents/code-reviewer.md',
    'check': {'valid': True, 'errors': [], 'warnings': ['a warning'], 'name': 'code-reviewer'},
    'repaired': False,
    'rules': [
        {'id': 'r', 'rule_text': 'Rule text.', 'source_url': 'https://cursor.com/docs/subagents', 'source_title': 'S'}
    ],
    'verifiedAt': '2026-11-15',
    'usage': {'calls': 1, 'inputTokens': 10, 'outputTokens': 20},
}


class AgentModeTest(unittest.TestCase):
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

    def test_switch_shows_the_agent_picker_and_view_only_in_agent_mode(self):
        w = self.window
        w.mode_switch.set_mode(AGENT_MODE)
        self.assertEqual(w.mode_switch.mode(), AGENT_MODE)
        self.assertFalse(w.agent_target.isHidden())
        self.assertFalse(w.agent_view.isHidden())
        self.assertTrue(w.instruction_target.isHidden())
        self.assertTrue(w.target_selector.isHidden())
        self.assertTrue(w.result_column.isHidden())
        self.assertEqual(w.run_button.text(), 'Build subagent   ⌘↵')
        w.mode_switch.set_mode(INSTRUCTIONS_MODE)
        self.assertTrue(w.agent_target.isHidden())
        self.assertTrue(w.agent_view.isHidden())
        w.mode_switch.set_mode(PROMPT_MODE)
        self.assertFalse(w.target_selector.isHidden())

    def test_request_carries_only_the_agent_target(self):
        w = self.window
        w.mode_switch.set_mode(AGENT_MODE)
        w.agent_target.set_target('codex')
        w.thoughts.setPlainText('a reviewer')
        with (
            patch.object(w.generator, 'request', return_value=({'provider': 'ollama', 'model': 'm'}, '')),
            patch('app.Worker') as worker,
        ):
            w.run_pipeline()
        payload = worker.call_args.args[0]
        self.assertEqual(payload, {'thoughts': 'a reviewer', 'provider': 'ollama', 'model': 'm', 'agent': 'codex'})

    def test_result_renders_saves_to_history_and_restores(self):
        w = self.window
        w.mode_switch.set_mode(AGENT_MODE)
        w._active_thoughts = 'a reviewer'
        w.on_finished({'ok': True, 'agent': dict(AGENT)})
        self.assertEqual(w.agent_view.editor.toPlainText(), AGENT['text'])
        self.assertIn('.cursor/agents/code-reviewer.md · ready', w.status.text())
        saved = self.store.load()[0]
        self.assertEqual((saved['kind'], saved['payload']['fileName']), ('agent', '.cursor/agents/code-reviewer.md'))
        w.mode_switch.set_mode(PROMPT_MODE)
        w.agent_target.set_target('claudeCode')
        w._render_history_entry({'kind': 'agent', 'thoughts': 'a reviewer', 'payload': dict(AGENT)})
        self.assertEqual(w.mode_switch.mode(), AGENT_MODE)
        self.assertEqual(w.agent_target.target(), 'cursor')
        self.assertEqual(w.agent_view.editor.toPlainText(), AGENT['text'])

    def test_an_error_shows_in_the_agent_view(self):
        w = self.window
        w.mode_switch.set_mode(AGENT_MODE)
        w.on_finished({'ok': False, 'error': 'model gone'})
        errors = [label.text() for label in w.agent_view.findChildren(QLabel, 'error')]
        self.assertIn('Error: model gone', errors)

    def test_edits_go_into_the_file_text(self):
        payload = dict(AGENT)
        HistoryView._apply_prompt_edit('agent', payload, 0, 'edited')
        self.assertEqual(payload['text'], 'edited')

    def test_file_name_follows_the_name_in_the_text(self):
        renamed = AGENT['text'].replace('name: code-reviewer', 'name: test-runner')
        self.assertEqual(agent_file_name('cursor', renamed, 'x'), '.cursor/agents/test-runner.md')
        self.assertEqual(agent_file_name('codex', 'name = "doc-writer"\n', 'x'), '.codex/agents/doc-writer.toml')
        self.assertEqual(agent_file_name('copilot', '---\nname: Bad Name\n---\n', 'kept'), 'kept')


if __name__ == '__main__':
    unittest.main()
