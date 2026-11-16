"""MCP settings tab: parsing Claude Code output, building commands and configs (no real CLI calls)."""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile as _tempfile

os.environ['PROMPTA_STATE_FILE'] = os.path.join(_tempfile.mkdtemp(), 'generator.json')  # never the real app state
from PyQt6.QtCore import QSettings as _QSettings

_QSettings.setPath(
    _QSettings.Format.IniFormat, _QSettings.Scope.UserScope, _tempfile.mkdtemp()
)  # never touch real prefs
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QLabel

import mcp_settings
from mcp_settings import (
    McpSettingsWidget,
    client_config,
    file_clients,
    install_commands,
    parse_mcp_get,
    read_entry,
    server_entry,
    write_entry,
)
import tempfile
import tomllib

GET_OUTPUT = """prompta:
  Scope: User config (available in all your projects)
  Status: ✔ Connected
  Type: stdio
  Command: node
  Args: /repo/mcp/server.ts
  Environment:
    PROMPTA_MODEL=kimi-k3:cloud

To remove this server, run: claude mcp remove prompta -s user
"""


class McpSettingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_parse_installed_and_missing(self):
        info = parse_mcp_get(GET_OUTPUT)
        self.assertTrue(info['installed'] and info['connected'])
        self.assertTrue(info['scope'].startswith('User'))
        self.assertEqual(info['env'], {'PROMPTA_MODEL': 'kimi-k3:cloud'})
        self.assertFalse(parse_mcp_get('No MCP server found with name: prompta')['installed'])
        self.assertFalse(parse_mcp_get('')['installed'])

    def test_commands_and_config(self):
        remove, add = install_commands('/bin/claude', '/bin/node', Path('/repo/mcp/server.ts'), {'PROMPTA_MODEL': 'm'})
        self.assertEqual(remove, ['/bin/claude', 'mcp', 'remove', 'prompta', '-s', 'user'])
        self.assertEqual(
            add,
            [
                '/bin/claude',
                'mcp',
                'add',
                'prompta',
                '-s',
                'user',
                '-e',
                'PROMPTA_MODEL=m',
                '--',
                '/bin/node',
                '/repo/mcp/server.ts',
            ],
        )
        config = json.loads(client_config('/bin/node', Path('/repo/mcp/server.ts'), {'PROMPTA_MODEL': 'm'}))
        self.assertEqual(
            config['mcpServers']['prompta'],
            {'command': '/bin/node', 'args': ['/repo/mcp/server.ts'], 'env': {'PROMPTA_MODEL': 'm'}},
        )

    def test_widget_uses_the_apps_generator_and_shows_status(self):
        chosen = ['gemini', 'gemini-3-pro', 'g-key', '', 'Gemini']
        widget = McpSettingsWidget(Path('/repo'), lambda: '/bin/node', QLabel, lambda: tuple(chosen))
        self.assertEqual(widget.model_summary.text(), 'gemini-3-pro · Gemini — change it in Model & API')
        # Installs carry no model and no key: the server follows Model & API through generator.json.
        self.assertEqual(widget._env(), {'PROMPTA_FOLLOW_APP': '1'})
        chosen[:] = ['openai', 'mlx-model', '', 'http://127.0.0.1:8080/v1', 'OpenAI-compatible']
        widget.sync_generator()
        self.assertIn('custom URL', widget.model_summary.text())
        widget._show_status(0, GET_OUTPUT)  # an old install with a pinned model
        self.assertIn(
            'connected · all projects · pinned to kimi-k3:cloud · Update to follow Model &amp; API',
            widget.claude_state.text(),
        )
        widget._show_status(0, GET_OUTPUT.replace('PROMPTA_MODEL=kimi-k3:cloud', 'PROMPTA_FOLLOW_APP=1'))
        self.assertIn('connected · all projects · follows Model &amp; API', widget.claude_state.text())
        self.assertEqual(widget.install_button.text(), 'Update')
        widget._show_status(1, 'No MCP server found with name: prompta')
        self.assertIn('not installed', widget.claude_state.text())
        widget._show_status(1, 'file:///opt/homebrew/lib/node_modules/cli.js:277\nTypeError: boom')
        self.assertIn('Could not check Claude Code', widget.status.text())
        self.assertIn('TypeError: boom', widget.status.text())
        self.assertFalse(widget.remove_button.isEnabled())

    def test_install_waits_for_a_model(self):
        widget = McpSettingsWidget(Path('/repo'), lambda: '/bin/node', QLabel, lambda: ('ollama', '', '', '', 'Ollama'))
        self.assertIn('No model chosen', widget.model_summary.text())
        with (
            patch.object(mcp_settings, 'find_claude_cli', return_value='/bin/claude'),
            patch.object(widget, '_run') as run,
        ):
            widget.install()
        run.assert_not_called()
        self.assertEqual(widget.status.text(), 'Choose a model in Model & API first')

    def test_prefers_native_claude_over_stale_homebrew_copy(self):
        native = Path.home() / '.local/bin/claude'
        with (
            patch.object(mcp_settings.shutil, 'which', return_value='/opt/homebrew/bin/claude'),
            patch.object(
                mcp_settings.Path, 'exists', lambda self: str(self) in (str(native), '/opt/homebrew/bin/claude')
            ),
        ):
            self.assertEqual(mcp_settings.find_claude_cli(), str(native))

    def test_install_runs_remove_then_add_with_env(self):
        widget = McpSettingsWidget(
            Path('/repo'), lambda: '/bin/node', QLabel, lambda: ('ollama', 'qwen3:30b', '', '', 'Ollama')
        )
        with (
            patch.object(mcp_settings, 'find_claude_cli', return_value='/bin/claude'),
            patch.object(widget, '_run') as run,
        ):
            widget.install()
        commands = run.call_args.args[0]
        self.assertEqual(commands[0][:3], ['/bin/claude', 'mcp', 'remove'])
        self.assertIn('PROMPTA_FOLLOW_APP=1', commands[1])
        self.assertFalse(any('PROMPTA_MODEL' in part or 'PROMPTA_API_KEY' in part for part in commands[1]))
        self.assertTrue(run.call_args.kwargs['tolerate_first_failure'])
        widget.copy_config()
        self.assertIn('"PROMPTA_FOLLOW_APP": "1"', QApplication.clipboard().text())

    def test_generator_state_file_is_private_and_holds_no_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'Prompta' / 'generator.json'
            state = mcp_settings.generator_state('openai', 'meta', ' muse-spark-1.3 ', 'https://api.meta.ai/v1')
            self.assertTrue(mcp_settings.write_generator_state(state, path))
            self.assertFalse(mcp_settings.write_generator_state(state, path), 'unchanged state is not rewritten')
            self.assertEqual(
                json.loads(path.read_text()),
                {
                    'provider': 'openai',
                    'keychain_account': 'meta',
                    'model': 'muse-spark-1.3',
                    'base_url': 'https://api.meta.ai/v1',
                },
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_key_warning_shows_when_the_server_cannot_read_the_key(self):
        missing = ['Anthropic (Claude)']
        widget = McpSettingsWidget(
            Path('/repo'),
            lambda: '/bin/node',
            QLabel,
            lambda: ('anthropic', 'claude-opus-5-5', 'k', '', 'Anthropic (Claude)'),
            lambda: missing[0],
        )
        self.assertFalse(widget.key_warning.isHidden())
        missing[0] = ''
        widget.sync_generator()
        self.assertTrue(widget.key_warning.isHidden())

    def test_claude_status_survives_restart_and_dot_is_green(self):
        widget = McpSettingsWidget(Path('/repo'), lambda: '/bin/node', QLabel)
        widget._show_status(0, GET_OUTPUT)
        self.assertIn('#3fa34d', widget.claude_state.text())
        reopened = McpSettingsWidget(Path('/repo'), lambda: '/bin/node', QLabel)
        self.assertIn('connected · all projects · pinned to kimi-k3:cloud', reopened.claude_state.text())
        self.assertEqual(reopened.install_button.text(), 'Update')
        self.assertTrue(reopened.remove_button.isEnabled())
        reopened._show_status(1, 'No MCP server found with name: prompta')
        self.assertIn('#a99c7c', McpSettingsWidget(Path('/repo'), lambda: '/bin/node', QLabel).claude_state.text())

    def _clients(self, home):
        return {c.key: c for c in file_clients(Path(home))}

    def test_json_clients_merge_and_remove_without_touching_other_servers(self):
        with tempfile.TemporaryDirectory() as home:
            clients = self._clients(home)
            cursor, vscode = clients['cursor'], clients['vscode']
            cursor.path.parent.mkdir(parents=True)
            cursor.path.write_text(json.dumps({'mcpServers': {'other': {'command': 'x'}}, 'theme': 1}))
            write_entry(cursor, server_entry(cursor, '/bin/node', Path('/s.ts'), {'PROMPTA_MODEL': 'm'}))
            data = json.loads(cursor.path.read_text())
            self.assertEqual(data['mcpServers']['other'], {'command': 'x'})
            self.assertEqual(data['theme'], 1)
            self.assertEqual(read_entry(cursor)['env'], {'PROMPTA_MODEL': 'm'})
            self.assertTrue(cursor.path.with_name('mcp.json.bak').exists())
            write_entry(cursor, None)
            self.assertIsNone(read_entry(cursor))
            self.assertIn('other', json.loads(cursor.path.read_text())['mcpServers'])
            write_entry(vscode, server_entry(vscode, '/bin/node', Path('/s.ts'), {}))
            self.assertEqual(json.loads(vscode.path.read_text())['servers']['prompta']['type'], 'stdio')

    def test_unparsable_config_is_never_rewritten(self):
        with tempfile.TemporaryDirectory() as home:
            vscode = self._clients(home)['vscode']
            vscode.path.parent.mkdir(parents=True)
            vscode.path.write_text('{ // comment\n "servers": {} }')
            with self.assertRaises(ValueError):
                write_entry(vscode, server_entry(vscode, '/bin/node', Path('/s.ts'), {}))
            self.assertEqual(vscode.path.read_text(), '{ // comment\n "servers": {} }')

    def test_codex_toml_section_is_replaced_and_rest_kept(self):
        with tempfile.TemporaryDirectory() as home:
            codex = self._clients(home)['codex']
            codex.path.parent.mkdir(parents=True)
            original = (
                'model = "gpt"\n\n[mcp_servers.other]\ncommand = "o"\n\n'
                '[mcp_servers.prompta]\ncommand = "old"\n\n[mcp_servers.prompta.env]\nA = "1"\n\n'
                '[tui]\ntheme = "dark"\n'
            )
            codex.path.write_text(original)
            write_entry(codex, server_entry(codex, '/bin/node', Path('/s.ts'), {'PROMPTA_MODEL': 'qwen3:30b'}))
            data = tomllib.loads(codex.path.read_text())
            self.assertEqual(data['model'], 'gpt')
            self.assertEqual(data['tui'], {'theme': 'dark'})
            self.assertEqual(data['mcp_servers']['other'], {'command': 'o'})
            self.assertEqual(
                data['mcp_servers']['prompta'],
                {'command': '/bin/node', 'args': ['/s.ts'], 'env': {'PROMPTA_MODEL': 'qwen3:30b'}},
            )
            write_entry(codex, None)
            data = tomllib.loads(codex.path.read_text())
            self.assertNotIn('prompta', data['mcp_servers'])
            self.assertEqual(data['tui'], {'theme': 'dark'})
            self.assertIn(
                '/bin/node',
                codex.path.with_name('config.toml.bak').read_text(),
                '.bak holds the state before the last change',
            )

    def test_hermes_yaml_edit_touches_only_prompta_block(self):
        with tempfile.TemporaryDirectory() as home:
            hermes = self._clients(home)['hermes']
            hermes.path.parent.mkdir(parents=True)
            original = (
                '# my agent\nmodel: deepseek  # keep this comment\n'
                'mcp_servers:\n  other:\n    command: o\n    enabled: true\n\ntoolsets:\n- web\n'
            )
            hermes.path.write_text(original)
            write_entry(hermes, server_entry(hermes, '/bin/node', Path('/s.ts'), {'PROMPTA_MODEL': 'm'}))
            text = hermes.path.read_text()
            self.assertIn('# keep this comment', text)
            self.assertEqual(
                read_entry(hermes),
                {'command': '/bin/node', 'args': ['/s.ts'], 'enabled': True, 'env': {'PROMPTA_MODEL': 'm'}},
            )
            write_entry(hermes, server_entry(hermes, '/bin/node', Path('/s.ts'), {'PROMPTA_MODEL': 'n'}))
            self.assertEqual(
                text.count('prompta:'), hermes.path.read_text().count('prompta:'), 'update replaces, not duplicates'
            )
            write_entry(hermes, None)
            self.assertEqual(hermes.path.read_text(), original)

    def test_hermes_without_mcp_section_gets_one(self):
        with tempfile.TemporaryDirectory() as home:
            hermes = self._clients(home)['hermes']
            hermes.path.parent.mkdir(parents=True)
            hermes.path.write_text('model: x\n')
            write_entry(hermes, server_entry(hermes, '/bin/node', Path('/s.ts'), {}))
            self.assertEqual(read_entry(hermes)['command'], '/bin/node')

    def test_widget_rows_install_into_present_clients_only(self):
        with (
            tempfile.TemporaryDirectory() as home,
            patch.object(mcp_settings, 'file_clients', lambda: file_clients(Path(home))),
            patch.object(mcp_settings, 'client_present', lambda c: c.key == 'cursor'),
        ):
            widget = McpSettingsWidget(
                Path('/repo'), lambda: '/bin/node', QLabel, lambda: ('ollama', 'qwen3:30b', '', '', 'Ollama')
            )
            widget.refresh_files()
            install, remove, state = widget.client_rows['cursor']
            self.assertTrue(install.isEnabled() and not remove.isEnabled())
            self.assertFalse(widget.client_rows['gemini'][0].isEnabled())
            install.click()
            self.assertEqual(read_entry(widget.clients[1])['env'], {'PROMPTA_FOLLOW_APP': '1'})
            self.assertIn('installed · follows Model &amp; API', state.text())
            self.assertEqual(install.text(), 'Update')
            remove.click()
            self.assertIn('not installed', state.text())


if __name__ == '__main__':
    unittest.main()
