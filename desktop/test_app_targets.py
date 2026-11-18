"""The "Written for" picker: official and open-weight targets, their requests and history."""

from test_support import WindowTestCase
import json
import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QPushButton, QLabel
from app import PromptaWindow
from generator_settings import GeneratorSettings


class TargetTest(WindowTestCase):
    def test_browser_button_matches_prompt_target(self):
        from widgets import PromptEdit

        for target, expected in (
            (None, None),
            ("openModel", None),
            ("claude", "https://claude.ai/new"),
            ("gemini", "https://gemini.google.com/app"),
            ("grok", "https://grok.com/"),
        ):
            with self.subTest(target=target):
                editor = PromptEdit("Prompt text", None, target)
                if expected is None:
                    self.assertFalse(hasattr(editor, "chat_button"))
                else:
                    with (
                        patch('PyQt6.QtGui.QGuiApplication.clipboard') as clipboard,
                        patch('PyQt6.QtGui.QDesktopServices.openUrl', return_value=True) as browser,
                    ):
                        editor.chat_button.click()
                        clipboard.return_value.setText.assert_called_once_with("Prompt text")
                        self.assertEqual(browser.call_args.args[0].toString(), expected)
                editor.close()

    def test_open_model_dropdown_excludes_other_targets_and_routes_request(self):
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        try:
            picker = window.target_picker
            self.assertEqual(sum(1 for item in picker._items if item['key'].startswith('open:')), 15)
            picker._choose('chatgpt')
            picker._choose('open:kimi-k3-1-pro')
            self.assertEqual(window.target_selector.target(), 'openModel')
            self.assertFalse(window.technique.isEnabled())
            window.thoughts.setPlainText('Build a small snake game')
            window.generator.model.set_current('test-model')
            with patch('app.Worker') as worker:
                window.run_pipeline()
                payload = worker.call_args.args[0]
                self.assertEqual(payload['target'], 'open:kimi-k3-1-pro')
                self.assertNotIn('manualTechnique', payload)
            window.worker = None
            picker._choose('grok')
            self.assertEqual(window.target_selector.target(), 'grok')
            picker._choose('general')
            self.assertIsNone(window.target_selector.target())
            self.assertTrue(window.technique.isEnabled())
        finally:
            window.close()

    def test_open_model_history_entry_restores_target_model(self):
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        try:
            name = next(item['label'] for item in window.target_picker._items if item['key'] == 'open:glm-5-3')
            payload = {
                'brief': {
                    'goal': 'g',
                    'task_type': 'generation',
                    'input': '',
                    'output_format': '',
                    'constraints': [],
                    'language': 'en',
                    'modality': 'text',
                    'stakes': 'low',
                    'assumptions': [],
                    'budget_calls': None,
                },
                'choice': {
                    'key': 'openModel_official',
                    'name': 'n',
                    'reason': 'r',
                    'confidence': 0.5,
                    'whyNotCheaper': 'w',
                },
                'synthesis': {
                    'techniqueKey': 'k',
                    'prompt': 'p' * 50,
                    'missing': [],
                    'warnings': [],
                    'config': {'temperature': None, 'top_p': None, 'max_tokens': 'm', 'rationale': 'r'},
                },
                'rejected': [],
                'trace': [],
                'openModelGuidance': {
                    'target': name,
                    'rule_set_version': 'v',
                    'verified_at': '2026-01-01',
                    'evidence_status': 'model-reported',
                    'variants': [],
                    'rules': [],
                },
            }
            entry = {
                'label': 'x',
                'kind': 'pipeline',
                'thoughts': 't',
                'created_at': '2026-01-01T00:00',
                'payload': payload,
            }
            window.history.items = [entry]
            window.history.filter()
            window.history.combo.setCurrentIndex(1)
            self.assertEqual(window.target_selector.target(), 'openModel')
            self.assertEqual(window.target_picker.current_key(), 'open:glm-5-3')
            # An unknown model falls back to any LLM rather than an open-model target without a model.
            payload['openModelGuidance']['target'] = 'No such model'
            window.history.combo.setCurrentIndex(0)
            window.history.combo.setCurrentIndex(1)
            self.assertIsNone(window.target_selector.target())
            self.assertEqual(window.target_picker.current_key(), 'general')
            self.assertTrue(window.technique.isEnabled())
        finally:
            window.close()

    def test_open_weight_library_has_fifteen_traceable_models(self):
        from theme import ROOT
        from library import library_entries
        import hashlib

        root = ROOT / 'open_model_prompt_guides'
        models = json.loads((root / 'manifest.json').read_text())['models']
        self.assertEqual(len(models), 15)
        self.assertEqual(len({m['id'] for m in models}), 15)
        paths = {e['path'] for e in library_entries(ROOT)}
        for model in models:
            self.assertTrue(model['weight_files_present'])
            self.assertEqual(len(model['revision']), 40)
            self.assertIn(f"open_model_prompt_guides/{model['id']}/README.md", paths, 'the model card the prompt uses')
            for source in model['files']:
                path = root / source['snapshot']
                self.assertTrue(path.resolve().is_relative_to(root.resolve()))
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source['sha256'])
                self.assertTrue(source['url'].startswith('https://'))
                self.assertNotIn(path.suffix, ('.safetensors', '.bin', '.gguf'))

    def test_claude_toggle_preserves_generator_and_excludes_generic_techniques(self):
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        self.assertIsNone(window.target_selector.target())
        model = window.generator.model.current_key()
        provider = window.generator.provider.current_key()
        window.technique.set_current('zero_shot')
        window.target_picker._choose('claude')
        self.assertFalse(window.technique.isEnabled())
        self.assertEqual(window.generator.model.current_key(), model)
        self.assertEqual(window.generator.provider.current_key(), provider)
        window.thoughts.setPlainText('Synthetic parity test')
        with patch('app.Worker') as worker_type:
            window.run_pipeline()
            payload = worker_type.call_args.args[0]
            self.assertEqual(payload['target'], 'claude')
            self.assertNotIn('deterministic', payload, 'the app never builds without the model')
            self.assertNotIn('manualTechnique', payload)
        window.target_picker._choose('general')
        self.assertTrue(window.technique.isEnabled())
        self.assertEqual(window.technique.current_key(), 'zero_shot')
        window.close()

    def test_claude_sources_and_mode_survive_history_restart_without_api_key(self):
        config = {'temperature': None, 'top_p': None, 'max_tokens': 'Model-dependent', 'rationale': 'Target-specific'}
        choice = {
            'key': 'claude_official',
            'name': 'Claude guidance',
            'reason': 'Official rules',
            'confidence': 0.5,
            'whyNotCheaper': 'Separate mode',
        }
        result = {
            'brief': {
                'goal': 'Parity',
                'task_type': 'classification',
                'language': 'en',
                'stakes': 'low',
                'output_format': 'JSON',
                'assumptions': [],
            },
            'choice': choice,
            'synthesis': {
                'prompt': 'Classify 2, 3, 4 by parity. Return JSON and acknowledge missing inputs.',
                'config': config,
                'warnings': [],
            },
            'rejected': [],
            'claudeGuidance': {
                'rule_set_version': 'test-version',
                'verified_at': '2026-11-05',
                'variants': [{'rule_ids': ['clear']}],
                'rules': [
                    {
                        'id': 'clear',
                        'source_section': 'Be clear and direct',
                        'rule_text': 'Be clear',
                        'source_url': 'https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#be-clear-and-direct',
                    }
                ],
            },
        }
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            first = PromptaWindow()
        first.thoughts.setPlainText('Synthetic parity request')
        first.generator.api_key.setText('synthetic-secret-not-for-history')
        first.on_finished({'ok': True, 'result': result})
        self.assertTrue(any('href=' in label.text() for label in first.findChildren(QLabel)))
        first.close()
        self.assertNotIn(b'synthetic-secret-not-for-history', self.store.path.read_bytes())
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            reopened = PromptaWindow()
        reopened.history.filter('test-version')
        reopened.history.combo.setCurrentIndex(1)
        self.assertEqual(reopened.target_selector.target(), 'claude')
        self.assertFalse(reopened.technique.isEnabled())
        self.assertEqual(reopened.thoughts.toPlainText(), 'Synthetic parity request')
        self.assertEqual(reopened.history.items[0]['payload']['claudeGuidance']['rule_set_version'], 'test-version')
        reopened.close()

    def test_targets_are_exclusive_and_keep_generator_model(self):
        for target in ('chatgpt', 'gemini', 'grok'):
            with self.subTest(target=target):
                with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
                    window = PromptaWindow()
                model, provider = window.generator.model.current_key(), window.generator.provider.current_key()
                self.assertIsNone(window.target_selector.target())
                window.technique.set_current('zero_shot')
                window.target_picker._choose('claude')
                window.target_picker._choose(target)
                self.assertEqual(window.target_selector.target(), target)
                self.assertFalse(window.technique.isEnabled())
                self.assertEqual(window.generator.model.current_key(), model)
                self.assertEqual(window.generator.provider.current_key(), provider)
                window.thoughts.setPlainText('Synthetic parity task')
                with patch('app.Worker') as worker_type:
                    window.run_pipeline()
                    payload = worker_type.call_args.args[0]
                    self.assertEqual(payload['target'], target)
                    self.assertNotIn('deterministic', payload, 'the app never builds without the model')
                    self.assertNotIn('manualTechnique', payload)
                    self.assertEqual(payload['model'], model)
                window.target_picker._choose('general')
                self.assertTrue(window.technique.isEnabled())
                self.assertEqual(window.technique.current_key(), 'zero_shot')
                window.close()

    def test_chatgpt_and_gemini_history_restore_their_own_sources_and_target(self):
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        for target, source in (
            ('chatgpt', 'https://learn.chatgpt.com/docs/prompting#prompts'),
            ('gemini', 'https://aistudio.google.com/docs/prompting-strategies#clear-and-specific-instructions'),
            ('grok', 'https://docs.x.ai/developers/model-capabilities/text/best-practices#design-the-eval'),
        ):
            window.thoughts.setPlainText(f'{target} synthetic parity task')
            window.generator.api_key.setText('synthetic-key-not-for-storage')
            window.on_finished(
                {
                    'ok': True,
                    'result': {
                        'brief': {
                            'goal': f'{target} parity classification',
                            'task_type': 'classification',
                            'language': 'en',
                            'stakes': 'low',
                            'output_format': 'JSON',
                            'assumptions': [],
                        },
                        'choice': {
                            'key': target + '_official',
                            'name': target,
                            'confidence': 0.5,
                            'reason': 'Official rules',
                            'whyNotCheaper': 'Target mode',
                        },
                        'synthesis': {
                            'prompt': 'Classify the supplied integers and return JSON; flag missing data.',
                            'config': {
                                'temperature': None,
                                'top_p': None,
                                'max_tokens': 'Model-dependent',
                                'rationale': 'Target settings',
                            },
                            'warnings': [],
                        },
                        'rejected': [],
                        f'{target}Guidance': {
                            'target': target,
                            'rule_set_version': 'test-version',
                            'verified_at': '2026-11-05',
                            'variants': [{'rule_ids': ['clear']}],
                            'rules': [
                                {
                                    'id': 'clear',
                                    'rule_text': 'Be clear',
                                    'source_url': source,
                                    'source_section': 'Prompting',
                                }
                            ],
                        },
                    },
                }
            )
        window.close()
        self.assertNotIn(b'synthetic-key-not-for-storage', self.store.path.read_bytes())
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            reopened = PromptaWindow()
        for target in ('chatgpt', 'gemini', 'grok'):
            reopened.history.filter(target)
            self.assertEqual(reopened.history.combo.count(), 2)
            self.assertLessEqual(len(reopened.history.combo.itemText(1).split()), 4)
            reopened.history.combo.setCurrentIndex(1)
            self.assertEqual(reopened.target_selector.target(), target)
            self.assertEqual(reopened.thoughts.toPlainText(), f'{target} synthetic parity task')
            self.assertTrue(
                any(
                    'href=' in label.text()
                    for label in reopened.result_column.output_holder.findChildren(QLabel)
                    if label.isVisibleTo(reopened.result_column.output_holder)
                )
            )
        reopened.close()

    def test_target_picker_drives_the_request(self):
        window = self._prompta_window()
        try:
            window.thoughts.setPlainText('Build a snake game')
            window.generator.model.set_current('test-model')
            picker = window.target_picker
            keys = [i['key'] for i in picker._items]
            self.assertEqual(keys[:6], ['general', 'claude', 'chatgpt', 'gemini', 'grok', 'hermes'])
            self.assertIn('open:glm-5-3', keys, 'every open-weight model is in the same list')
            self.assertEqual(picker.text(), '— any LLM —')

            def payload():
                with patch('app.Worker') as worker:
                    window.worker = None
                    window.run_pipeline()
                    return worker.call_args.args[0]

            request = payload()
            self.assertEqual(request['executionProfile'], 'universal')
            self.assertNotIn('agentCapabilities', request)
            window.execution_profile.set_current('agent')
            self.assertEqual(
                payload()['agentCapabilities'], ['code', 'files', 'integrations', 'web'], 'an agent has every tool'
            )
            window.execution_profile.set_current('universal')
            picker._choose('claude')
            self.assertEqual(payload()['target'], 'claude')
            self.assertFalse(window.technique.isEnabled())
            picker._choose('grok')
            request = payload()
            self.assertEqual(request['target'], 'grok')
            picker._choose('hermes')
            request = payload()
            self.assertEqual(request['target'], 'hermes')
            self.assertFalse(window.technique.isEnabled())
            picker._choose('open:glm-5-3')
            request = payload()
            self.assertEqual(request['target'], 'open:glm-5-3')
            self.assertEqual(window.target_selector.target(), 'openModel')
            self.assertFalse(window.technique_panel.isVisibleTo(window), 'techniques are for Any only')
            glm = next(item['label'] for item in picker._items if item['key'] == 'open:glm-5-3')
            self.assertEqual(picker.text(), glm, 'the dropdown names the chosen model')
            picker._choose('general')
            request = payload()
            self.assertNotIn('target', request)
            self.assertTrue(window.technique.isEnabled())
        finally:
            window.close()

    def test_one_build_button_and_open_models_hide_techniques(self):
        window = self._prompta_window()
        try:
            self.assertFalse(
                [b for b in window.findChildren(QPushButton) if b.objectName() == 'example'], 'no empty-state examples'
            )
            self.assertTrue(window.model_line.text())
            self.assertFalse(
                [b for b in window.findChildren(QPushButton) if b.text() == 'Cancel'],
                'one button: Build turns into Stop',
            )
            window.target_picker._choose('open:glm-5-3')
            self.assertFalse(window.technique_panel.isVisibleTo(window), 'techniques are for Any only')
        finally:
            window.close()

    def test_open_weight_models_are_grouped_by_family(self):
        window = self._prompta_window()
        try:
            picker = window.target_picker
            open_items = [item for item in picker._items if item['key'].startswith('open:')]
            families = list(dict.fromkeys(item['category'].removesuffix(' · open-weight') for item in open_items))
            self.assertEqual(families, sorted(families, key=str.casefold))
            qwen = [item['label'] for item in open_items if item['category'] == 'QWEN · ALIBABA · open-weight']
            self.assertEqual(qwen[:3], ['Qwen3-Coder-Next', 'Qwen3.8 2.4T A95B', 'Qwen3.8 Flash Next'])
            picker._choose('open:qwen3-coder-next')
            self.assertEqual(window.target_selector.target(), 'openModel')
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
