"""Generator settings: providers, model lists, API keys and their persistence."""

from test_support import WindowTestCase
from pathlib import Path
import json
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QLabel
from app import PromptaWindow
import generator_settings
from generator_settings import GeneratorSettings


class ProviderTest(WindowTestCase):
    def test_personal_provider_from_gitignored_file(self):
        self.local_patch.stop()  # the real loader, reading a temp file
        from app import load_local_providers

        path = Path(self.temp.name) / 'providers.local.json'
        path.write_text(
            json.dumps(
                {
                    'providers': [
                        {
                            'key': 'meta',
                            'label': 'Meta (Muse Spark)',
                            'base_url': 'https://api.meta.ai/v1',
                            'models': ['muse-spark-1.3'],
                            'key_env': 'PROMPTA_TEST_NO_SUCH_ENV',
                            'api_key': 'file-key',
                        },
                        {'key': 'openai', 'base_url': 'https://x.test/v1'},  # cannot replace a built-in provider
                        {'key': 'broken'},
                    ]
                }
            )
        )
        local = load_local_providers(path)
        self.assertEqual(list(local), ['meta'])
        # Meta is built in: without a file it is still there, with its own URL and Muse Spark models.
        bare = load_local_providers(Path(self.temp.name) / 'missing.json')
        self.assertEqual(list(bare), ['meta'])
        self.assertEqual(bare['meta']['base_url'], 'https://api.meta.ai/v1')
        self.assertIn('muse-spark-1.3-contributor', bare['meta']['models'])
        # A file entry for a built-in name only adds fields: no URL or models needed, the key is kept.
        path.write_text(json.dumps({'providers': [{'key': 'meta', 'api_key': 'file-key'}]}))
        merged = load_local_providers(path)['meta']
        self.assertEqual(
            (merged['api_key'], merged['base_url'], merged['models']),
            ('file-key', 'https://api.meta.ai/v1', bare['meta']['models']),
        )
        with (
            patch('app.load_local_providers', return_value=local),
            patch('keychain.load', return_value=''),
            patch.object(GeneratorSettings, 'load_models'),
            patch.object(PromptaWindow, 'load_techniques'),
        ):
            window = PromptaWindow()
            window.generator.provider.set_current('meta', emit=True)
        self.local_patch.start()
        self.assertEqual(window.generator.model.current_key(), 'muse-spark-1.3')
        self.assertEqual(window.generator.api_key.text(), 'file-key')
        provider, model, key, url, label = window.generator.for_mcp()
        self.assertEqual(
            (provider, model, url, label), ('openai', 'muse-spark-1.3', 'https://api.meta.ai/v1', 'Meta (Muse Spark)')
        )
        window.thoughts.setPlainText('Напиши письмо')
        with patch('app.Worker') as worker:
            window.run_pipeline()
        payload = worker.call_args.args[0] if worker.call_args.args else worker.call_args.kwargs
        self.assertIn('"provider": "openai"', json.dumps(payload))
        self.assertIn('https://api.meta.ai/v1', json.dumps(payload))
        window.close()

    def test_api_settings_and_thoughts_label(self):
        from PyQt6.QtWidgets import QLineEdit

        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        labels = {label.text(): label for label in window.findChildren(QLabel)}
        self.assertNotIn('THOUGHTS', labels)
        self.assertEqual(
            window.thoughts.placeholderText(),
            "Describe the task in your own words, rough is fine. "
            "You'll get a prompt for this one task: paste it into any chat.",
        )
        self.assertEqual(window.thoughts.accessibleName(), 'Thoughts')
        self.assertFalse(window.settings_button.icon().isNull())
        self.assertTrue(window.settings_dialog.isAncestorOf(window.generator.api_key))
        for control in (
            window.generator.provider,
            window.generator.model,
            window.generator.refresh_button,
            window.generator.models_hint,
        ):
            self.assertTrue(window.settings_dialog.isAncestorOf(control))
            self.assertFalse(control.isVisibleTo(window))
        self.assertEqual(window.generator.api_key.echoMode(), QLineEdit.EchoMode.Password)
        window.settings_button.click()
        self.assertTrue(window.settings_dialog.isVisible())
        self.assertTrue(window.generator.provider.isVisible())
        self.assertTrue(window.generator.model.isVisible())

        window.generator.api_key.setText('synthetic-test-key')
        window.settings_dialog.accept()
        self.assertFalse(window.settings_dialog.isVisible())
        window.thoughts.setPlainText('Synthetic test')
        no_keychain = Mock(load=lambda provider: '', save=Mock(return_value=True), forget=Mock())
        with patch.object(generator_settings, 'keychain', no_keychain), patch('app.Worker') as worker_type:
            window.generator.provider.set_current('openai', emit=True)  # loads this provider's own (empty) key
            window.generator.api_key.setText('synthetic-test-key')
            window.generator.model.set_current('synthetic-model')
            window.run_pipeline()
            payload = worker_type.call_args.args[0]
            self.assertEqual(payload['apiKey'], 'synthetic-test-key')
            self.assertEqual(payload['model'], 'synthetic-model')
            self.assertEqual(payload['provider'], 'openai')
        self.assertFalse(self.store.path.exists())
        window.close()

    def test_api_key_is_remembered_per_provider_only_when_asked(self):
        saved = {}
        fake = Mock(
            load=lambda provider: saved.get(provider, ''),
            save=lambda provider, key: saved.__setitem__(provider, key) or True,
            forget=lambda provider: saved.pop(provider, None),
        )
        with patch.object(generator_settings, 'keychain', fake):
            window = self._prompta_window()
            try:
                window.generator.provider.set_current('gemini', emit=True)
                self.assertEqual(window.generator.api_key.text(), '')
                self.assertFalse(window.generator.remember_key.isChecked(), 'off until the user asks')
                window.generator.api_key.setText('gemini-key')
                window.generator.remember_key.setChecked(True)
                self.assertEqual(saved, {'gemini': 'gemini-key'})
                window.generator.provider.set_current('openai', emit=True)
                self.assertEqual(window.generator.api_key.text(), '', 'each provider has its own key')
                window.generator.provider.set_current('gemini', emit=True)
                self.assertEqual(window.generator.api_key.text(), 'gemini-key')
                self.assertTrue(window.generator.remember_key.isChecked())
                window.generator.remember_key.setChecked(False)
                self.assertEqual(saved, {}, 'unchecking removes the saved key')
            finally:
                window.close()

    def test_openai_compatible_provider_keeps_its_own_url_and_key(self):
        saved = {'openai_compatible': 'compat-key'}
        fake = Mock(
            load=lambda provider: saved.get(provider, ''),
            save=lambda provider, key: saved.__setitem__(provider, key) or True,
            forget=lambda provider: saved.pop(provider, None),
        )
        with patch.object(generator_settings, 'keychain', fake), patch.object(GeneratorSettings, 'load_models'):
            window = self._prompta_window()
            try:
                window.generator.provider.set_current('openai_compatible', emit=True)
                self.assertEqual(window.generator.api_key.text(), 'compat-key')
                window.thoughts.setPlainText('Synthetic test')
                window.generator.model_name.setText('local-model')
                window.generator.api_key.setText('')
                with patch('app.Worker') as worker_type:
                    window.run_pipeline()
                    worker_type.assert_not_called()
                self.assertEqual(window.status.text(), 'Add the server URL in Settings')
                window.generator.model_base_url.setText('http://127.0.0.1:8080/v1')
                window.generator.provider.set_current('openai', emit=True)
                self.assertEqual(window.generator.model_base_url.text(), '', 'OpenAI has its own URL')
                window.generator.provider.set_current('openai_compatible', emit=True)
                self.assertEqual(window.generator.model_base_url.text(), 'http://127.0.0.1:8080/v1')
                window.generator.api_key.setText('')
                with patch('app.Worker') as worker_type:
                    window.run_pipeline()
                    payload = worker_type.call_args.args[0]
                self.assertEqual(payload['provider'], 'openai', 'the pipeline speaks the same OpenAI API')
                self.assertEqual(payload['baseUrl'], 'http://127.0.0.1:8080/v1')
                self.assertEqual(payload['apiKey'], '')
            finally:
                window.close()

    def test_each_provider_lists_its_own_models_and_compatible_types_one(self):
        no_keychain = Mock(load=lambda provider: '', save=Mock(return_value=True), forget=Mock())
        with patch.object(GeneratorSettings, 'load_models'), patch.object(generator_settings, 'keychain', no_keychain):
            window = self._prompta_window()
            try:
                window.generator._on_models_loaded(['qwen3:30b', 'glm-5.3:cloud'], 'ollama')
                window.generator.model.set_current('qwen3:30b')
                window.generator.provider.set_current('gemini', emit=True)
                self.assertEqual(window.generator.model._items, [], 'no Ollama models under Gemini')
                window.generator._on_models_loaded(['gemini-3-pro', 'gemini-3-flash'], 'gemini')
                self.assertEqual(window.generator.current_model(), 'gemini-3-pro')
                window.generator._on_models_loaded(['late-ollama-model'], 'ollama')  # a fetch that ends after a switch
                self.assertEqual([i['key'] for i in window.generator.model._items], ['gemini-3-pro', 'gemini-3-flash'])

                window.generator.provider.set_current('openai_compatible', emit=True)
                self.assertTrue(window.generator.model.isHidden(), 'a custom server has no list: the name is typed')
                self.assertTrue(window.generator.refresh_button.isHidden())
                self.assertFalse(window.generator.model_name.isHidden())
                window.generator.model_name.setText('mlx-community/Qwen3-8B')
                self.assertEqual(window.generator.current_model(), 'mlx-community/Qwen3-8B')

                window.generator.provider.set_current('ollama', emit=True)
                self.assertTrue(window.generator.model_name.isHidden())
                self.assertEqual([i['key'] for i in window.generator.model._items], ['late-ollama-model'])
                window.generator.provider.set_current('gemini', emit=True)
                self.assertEqual(window.generator.current_model(), 'gemini-3-pro', 'each provider keeps its choice')
            finally:
                window.close()

    def test_cloud_model_lists_come_from_each_providers_api(self):
        import json
        from workers import fetch_cloud_models

        bodies = {
            'https://api.openai.com/v1/models': {'data': [{'id': 'gpt-b'}, {'id': 'gpt-a'}]},
            'https://api.anthropic.com/v1/models?limit=1000': {'data': [{'id': 'claude-x'}]},
            'https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000': {
                'models': [
                    {'name': 'models/gemini-pro', 'supportedGenerationMethods': ['generateContent']},
                    {'name': 'models/embedding', 'supportedGenerationMethods': ['embedContent']},
                ]
            },
        }
        seen = []

        class Response:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(self.body).encode()

        def fake_open(request, timeout=0):
            seen.append((request.full_url, dict(request.header_items())))
            return Response(bodies[request.full_url])

        with patch('urllib.request.urlopen', fake_open):
            self.assertEqual(fetch_cloud_models('openai', 'k1'), ['gpt-a', 'gpt-b'])
            self.assertEqual(fetch_cloud_models('anthropic', 'k2'), ['claude-x'])
            self.assertEqual(fetch_cloud_models('gemini', 'k3'), ['gemini-pro'], 'only text models, without the prefix')
            self.assertEqual(fetch_cloud_models('openai', ''), [], 'no key, no request')
        self.assertEqual(seen[0][1].get('Authorization'), 'Bearer k1')
        self.assertEqual(seen[1][1].get('X-api-key'), 'k2')
        self.assertEqual(seen[2][1].get('X-goog-api-key'), 'k3')
        self.assertNotIn('k3', seen[2][0], 'the key never goes into the URL')

    def test_generator_settings_survive_a_restart(self):
        no_keychain = Mock(load=lambda provider: '', save=Mock(return_value=True), forget=Mock())
        with patch.object(generator_settings, 'keychain', no_keychain):
            window = self._prompta_window()
            window.generator.provider.set_current('openai_compatible', emit=True)
            window.generator.model_base_url.setText('http://127.0.0.1:8080/v1')
            window.generator.model_name.setText('mlx-community/Qwen3-8B')
            window.generator.model_name.editingFinished.emit()
            window.generator.provider.set_current('gemini', emit=True)
            window.generator.model.set_current('gemini-3-pro', emit=True)
            window.close()

            again = self._prompta_window()
            try:
                self.assertEqual(again.generator.provider.current_key(), 'gemini', 'the last provider comes back')
                self.assertEqual(again.generator.current_model(), 'gemini-3-pro')
                again.generator.provider.set_current('openai_compatible', emit=True)
                self.assertEqual(again.generator.model_base_url.text(), 'http://127.0.0.1:8080/v1')
                self.assertEqual(again.generator.current_model(), 'mlx-community/Qwen3-8B')
            finally:
                again.close()

    def test_keyless_lists_come_from_a_daily_cached_catalog(self):
        import json
        import time
        from workers import catalog_models, reduce_catalog

        data = {
            'openai': {
                'models': {
                    'gpt-old': {'id': 'gpt-old', 'release_date': '2024-01-01', 'modalities': {'output': ['text']}},
                    'gpt-new': {'id': 'gpt-new', 'release_date': '2026-05-01', 'modalities': {'output': ['text']}},
                    'gpt-image': {'id': 'gpt-image', 'release_date': '2026-06-01', 'modalities': {'output': ['image']}},
                    'gpt-gone': {'id': 'gpt-gone', 'status': 'deprecated', 'modalities': {'output': ['text']}},
                }
            },
            'google': {'models': {'gemini-x': {'id': 'gemini-x', 'modalities': {'output': ['text']}}}},
        }
        self.assertEqual(reduce_catalog(data)['openai'], ['gpt-new', 'gpt-old'], 'text models only, newest first')
        self.assertEqual(reduce_catalog(data)['gemini'], ['gemini-x'], 'our gemini is their google')
        calls = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(data).encode()

        def fake_open(request, timeout=0):
            calls.append(request.full_url)
            return Response()

        cache = Path(self.temp.name) / 'catalog.json'
        with patch('urllib.request.urlopen', fake_open):
            self.assertEqual(catalog_models('openai', cache), ['gpt-new', 'gpt-old'])
            self.assertEqual(catalog_models('gemini', cache), ['gemini-x'])
        self.assertEqual(calls, ['https://models.dev/api.json'], 'fetched once, then read from the copy')
        self.assertLess(cache.stat().st_size, 1000, 'only the ids are kept, not the 6 MB file')
        saved = json.loads(cache.read_text())
        saved['fetched'] = time.time() - 2 * 24 * 3600
        cache.write_text(json.dumps(saved))
        with patch('urllib.request.urlopen', side_effect=OSError('offline')):
            self.assertEqual(catalog_models('openai', cache), ['gpt-new', 'gpt-old'], 'a stale copy beats nothing')

    def test_catalog_list_says_where_it_came_from(self):
        no_keychain = Mock(load=lambda provider: '', save=Mock(return_value=True), forget=Mock())
        with patch.object(GeneratorSettings, 'load_models'), patch.object(generator_settings, 'keychain', no_keychain):
            window = self._prompta_window()
            try:
                window.generator.provider.set_current('anthropic', emit=True)
                window.generator._on_models_loaded(['claude-a', 'claude-b'], 'anthropic', 'catalog')
                self.assertIn('models.dev', window.generator.models_hint.text())
                window.generator.provider.set_current('ollama', emit=True)
                window.generator.provider.set_current('anthropic', emit=True)
                self.assertIn('models.dev', window.generator.models_hint.text(), 'the hint survives a switch back')
            finally:
                window.close()


if __name__ == '__main__':
    unittest.main()
