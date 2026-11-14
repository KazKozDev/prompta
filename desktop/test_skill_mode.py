"""Skill mode: the Prompt / Skill switch, the skill request, its result, history and saving."""

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
from skill_mode import SKILL_MODE
from skill_view import save_skill

SKILL = {
    'skill': (
        '---\nname: summarizing-notes\ndescription: Summarizes notes. Use when notes are shared.\n---\n\n# Notes\n'
    ),
    'name': 'summarizing-notes',
    'description': 'Summarizes notes. Use when notes are shared.',
    'surface': 'portable',
    'check': {'valid': True, 'errors': [], 'warnings': ['a warning']},
    'repaired': False,
    'rules': [
        {
            'id': 'r',
            'rule_text': 'Rule text.',
            'source_url': 'https://agentskills.io/specification',
            'source_title': 'Spec',
        }
    ],
    'verifiedAt': '2026-11-14',
    'usage': {'calls': 1, 'inputTokens': 10, 'outputTokens': 20},
}


class SkillModeTest(unittest.TestCase):
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

    def test_switch_swaps_prompt_controls_for_skill_ones_and_back(self):
        w = self.window
        w.show()
        self.assertFalse(w.surface_selector.isVisible())
        w.mode_switch.set_mode(SKILL_MODE)
        self.assertTrue(w.surface_selector.isVisible() and w.skill_view.isVisible())
        for widget in (w.target_selector, w.execution_profile, w.technique_panel, w.result_column):
            self.assertFalse(widget.isVisible())
        self.assertTrue(w.run_button.text().startswith('Build skill'))
        w.mode_switch.set_mode('prompt')
        self.assertTrue(w.target_selector.isVisible() and w.result_column.isVisible())
        self.assertTrue(w.run_button.text().startswith('Build prompt'))

    def test_skill_request_carries_only_the_skill_fields(self):
        w = self.window
        w.mode_switch.set_mode(SKILL_MODE)
        w.surface_selector.set_surface('claudeCode')
        w.thoughts.setPlainText('a skill for meeting notes')
        with (
            patch.object(w.generator, 'request', return_value=({'provider': 'ollama', 'model': 'm'}, '')),
            patch('app.Worker') as worker,
        ):
            w.run_pipeline()
        payload = worker.call_args.args[0]
        self.assertEqual(
            payload,
            {'thoughts': 'a skill for meeting notes', 'provider': 'ollama', 'model': 'm', 'skill': 'claudeCode'},
        )

    def test_result_renders_saves_to_history_and_restores(self):
        w = self.window
        w.mode_switch.set_mode(SKILL_MODE)
        w.thoughts.setPlainText('notes skill')
        w._active_thoughts = 'notes skill'
        w.on_finished({'ok': True, 'skill': dict(SKILL)})
        self.assertEqual(w.skill_view.editor.toPlainText(), SKILL['skill'])
        self.assertIn('summarizing-notes', w.status.text())
        saved = self.store.load()[0]
        self.assertEqual((saved['kind'], saved['payload']['name']), ('skill', 'summarizing-notes'))
        w.mode_switch.set_mode('prompt')
        w._render_history_entry({'kind': 'skill', 'thoughts': 'notes skill', 'payload': dict(SKILL)})
        self.assertEqual(w.mode_switch.mode(), SKILL_MODE)
        self.assertEqual(w.skill_view.editor.toPlainText(), SKILL['skill'])

    def test_a_long_skill_grows_the_block_instead_of_scrolling_inside_it(self):
        w = self.window
        w.resize(1200, 800)
        w.show()
        w.mode_switch.set_mode(SKILL_MODE)
        long_skill = SKILL['skill'] + ''.join(f'- step {n}: a line of the workflow\n' for n in range(120))
        w.on_finished({'ok': True, 'skill': dict(SKILL, skill=long_skill)})
        for _ in range(3):
            self.app.processEvents()
        editor = w.skill_view.editor
        self.assertGreater(editor.height(), 460)  # taller than the old cap
        self.assertEqual(editor.verticalScrollBar().maximum(), 0)

    def test_opening_a_skill_leaves_the_prompt_side_alone(self):
        w = self.window
        w.prompt_version = 'v2'
        w.target_selector.set_target('claude', '')
        warns_before = len(w.result_column.findChildren(QLabel, 'warn'))
        w._on_history_opened({'kind': 'skill', 'thoughts': 'notes skill', 'payload': dict(SKILL)})
        self.assertEqual(w.target_selector.target(), 'claude')
        self.assertEqual(len(w.result_column.findChildren(QLabel, 'warn')), warns_before)

    def test_skill_button_ignores_prompt_card_edits(self):
        w = self.window
        card = Mock(change_count=Mock(return_value=2))
        w.assumptions_card = card
        w.mode_switch.set_mode(SKILL_MODE)
        self.assertEqual(w.run_button.text(), 'Build skill   ⌘↵')
        w.assumptions_card = None

    def test_edits_go_into_the_skill_text_not_the_zero_shot_field(self):
        payload = dict(SKILL)
        HistoryView._apply_prompt_edit('skill', payload, 0, 'edited')
        self.assertEqual(payload['skill'], 'edited')
        self.assertNotIn('zeroShotPrompt', payload)
        self.assertEqual(payload['originalPrompts'], {'0': SKILL['skill']})

    def test_save_creates_a_folder_named_like_the_skill(self):
        path = save_skill(Path(self.temp.name), 'summarizing-notes', SKILL['skill'])
        self.assertEqual(path, Path(self.temp.name) / 'summarizing-notes' / 'SKILL.md')
        self.assertEqual(path.read_text(encoding='utf-8'), SKILL['skill'])


if __name__ == '__main__':
    unittest.main()
