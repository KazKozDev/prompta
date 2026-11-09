"""MCP settings tab: parsing Claude Code output, building commands and configs (no real CLI calls)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile as _tempfile
from PyQt6.QtCore import QSettings as _QSettings
_QSettings.setPath(_QSettings.Format.IniFormat, _QSettings.Scope.UserScope, _tempfile.mkdtemp())  # never touch real prefs
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QLabel

import mcp_settings
from mcp_settings import (McpSettingsWidget, client_config, file_clients, install_commands, parse_mcp_get,
                          read_entry, server_entry, server_env, write_entry)
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
        env = server_env('ollama', ' qwen3:30b ', api_key='ignored-for-ollama-by-widget')
        self.assertEqual(env['PROMPTA_MODEL'], 'qwen3:30b')
        self.assertNotIn('PROMPTA_PROVIDER', env)
        remove, add = install_commands('/bin/claude', '/bin/node', Path('/repo/mcp/server.ts'), {'PROMPTA_MODEL': 'm'})
        self.assertEqual(remove, ['/bin/claude', 'mcp', 'remove', 'prompta', '-s', 'user'])
        self.assertEqual(add, ['/bin/claude', 'mcp', 'add', 'prompta', '-s', 'user', '-e', 'PROMPTA_MODEL=m', '--', '/bin/node', '/repo/mcp/server.ts'])
        config = json.loads(client_config('/bin/node', Path('/repo/mcp/server.ts'), {'PROMPTA_MODEL': 'm'}))
        self.assertEqual(config['mcpServers']['prompta'], {'command': '/bin/node', 'args': ['/repo/mcp/server.ts'], 'env': {'PROMPTA_MODEL': 'm'}})

    def test_widget_shows_status_and_hides_key_for_ollama(self):
        widget = McpSettingsWidget(Path('/repo'), lambda: '/bin/node', QLabel)
        self.assertFalse(widget.api_key.isVisibleTo(widget))
        widget.provider.setCurrentIndex(widget.provider.findData('gemini'))
        self.assertTrue(widget.api_key.isVisibleTo(widget))
        widget._show_status(0, GET_OUTPUT)
        self.assertIn('connected · all projects · Prompta writes with kimi-k3:cloud', widget.claude_state.text())
        self.assertEqual(widget.provider.currentData(), 'ollama')
        self.assertEqual(widget.model.currentText(), 'kimi-k3:cloud')
        self.assertEqual(widget.install_button.text(), 'Update')
        widget._show_status(1, 'No MCP server found with name: prompta')
        self.assertIn('not installed', widget.claude_state.text())
        widget._show_status(1, 'file:///opt/homebrew/lib/node_modules/cli.js:277\nTypeError: boom')
        self.assertIn('Could not check Claude Code', widget.status.text())
        self.assertIn('TypeError: boom', widget.status.text())
        self.assertFalse(widget.remove_button.isEnabled())

    def test_prefers_native_claude_over_stale_homebrew_copy(self):
        native = Path.home() / '.local/bin/claude'
        with patch.object(mcp_settings.shutil, 'which', return_value='/opt/homebrew/bin/claude'), \
             patch.object(mcp_settings.Path, 'exists', lambda self: str(self) in (str(native), '/opt/homebrew/bin/claude')):
            self.assertEqual(mcp_settings.find_claude_cli(), str(native))

    def test_install_runs_remove_then_add_with_env(self):
        widget = McpSettingsWidget(Path('/repo'), lambda: '/bin/node', QLabel)
        widget.model.setEditText('qwen3:30b')
        with patch.object(mcp_settings, 'find_claude_cli', return_value='/bin/claude'), patch.object(widget, '_run') as run:
            widget.install()
        commands = run.call_args.args[0]
        self.assertEqual(commands[0][:3], ['/bin/claude', 'mcp', 'remove'])
        self.assertIn('PROMPTA_MODEL=qwen3:30b', commands[1])
        self.assertTrue(run.call_args.kwargs['tolerate_first_failure'])
        widget.copy_config()
        self.assertIn('"PROMPTA_MODEL": "qwen3:30b"', QApplication.clipboard().text())

    def test_claude_status_survives_restart_and_dot_is_green(self):
        widget = McpSettingsWidget(Path('/repo'), lambda: '/bin/node', QLabel)
        widget._show_status(0, GET_OUTPUT)
        self.assertIn('#3fa34d', widget.claude_state.text())
        reopened = McpSettingsWidget(Path('/repo'), lambda: '/bin/node', QLabel)
        self.assertIn('connected · all projects · Prompta writes with kimi-k3:cloud', reopened.claude_state.text())
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
            original = 'model = "gpt"\n\n[mcp_servers.other]\ncommand = "o"\n\n[mcp_servers.prompta]\ncommand = "old"\n\n[mcp_servers.prompta.env]\nA = "1"\n\n[tui]\ntheme = "dark"\n'
            codex.path.write_text(original)
            write_entry(codex, server_entry(codex, '/bin/node', Path('/s.ts'), {'PROMPTA_MODEL': 'qwen3:30b'}))
            data = tomllib.loads(codex.path.read_text())
            self.assertEqual(data['model'], 'gpt')
            self.assertEqual(data['tui'], {'theme': 'dark'})
            self.assertEqual(data['mcp_servers']['other'], {'command': 'o'})
            self.assertEqual(data['mcp_servers']['prompta'], {'command': '/bin/node', 'args': ['/s.ts'], 'env': {'PROMPTA_MODEL': 'qwen3:30b'}})
            write_entry(codex, None)
            data = tomllib.loads(codex.path.read_text())
            self.assertNotIn('prompta', data['mcp_servers'])
            self.assertEqual(data['tui'], {'theme': 'dark'})
            self.assertIn('/bin/node', codex.path.with_name('config.toml.bak').read_text(), '.bak holds the state before the last change')

    def test_hermes_yaml_edit_touches_only_prompta_block(self):
        with tempfile.TemporaryDirectory() as home:
            hermes = self._clients(home)['hermes']
            hermes.path.parent.mkdir(parents=True)
            original = '# my agent\nmodel: deepseek  # keep this comment\nmcp_servers:\n  other:\n    command: o\n    enabled: true\n\ntoolsets:\n- web\n'
            hermes.path.write_text(original)
            write_entry(hermes, server_entry(hermes, '/bin/node', Path('/s.ts'), {'PROMPTA_MODEL': 'm'}))
            text = hermes.path.read_text()
            self.assertIn('# keep this comment', text)
            self.assertEqual(read_entry(hermes), {'command': '/bin/node', 'args': ['/s.ts'], 'enabled': True, 'env': {'PROMPTA_MODEL': 'm'}})
            write_entry(hermes, server_entry(hermes, '/bin/node', Path('/s.ts'), {'PROMPTA_MODEL': 'n'}))
            self.assertEqual(text.count('prompta:'), hermes.path.read_text().count('prompta:'), 'update replaces, not duplicates')
            write_entry(hermes, None)
            self.assertEqual(hermes.path.read_text(), original)

    def test_hermes_without_mcp_section_gets_one(self):
        with tempfile.TemporaryDirectory() as home:
            hermes = self._clients(home)['hermes']
            hermes.path.parent.mkdir(parents=True)
            hermes.path.write_text('model: x\n')
            write_entry(hermes, server_entry(hermes, '/bin/node', Path('/s.ts'), {}))
            self.assertEqual(read_entry(hermes)['command'], '/bin/node')

    def test_openclaw_goes_through_its_cli(self):
        entry = {'command': '/bin/node', 'args': ['/s.ts']}
        self.assertEqual(mcp_settings.openclaw_commands('/bin/openclaw', entry),
                         [['/bin/openclaw', 'mcp', 'set', 'prompta', json.dumps(entry)]])
        self.assertEqual(mcp_settings.openclaw_commands('/bin/openclaw', None), [['/bin/openclaw', 'mcp', 'unset', 'prompta']])
        with tempfile.TemporaryDirectory() as home:
            openclaw = self._clients(home)['openclaw']
            openclaw.path.parent.mkdir(parents=True)
            openclaw.path.write_text(json.dumps({'mcp': {'servers': {'prompta': entry}}}))
            self.assertEqual(read_entry(openclaw), entry)
            with self.assertRaises(ValueError):
                write_entry(openclaw, entry)

    def test_widget_rows_install_into_present_clients_only(self):
        with tempfile.TemporaryDirectory() as home, \
             patch.object(mcp_settings, 'file_clients', lambda: file_clients(Path(home))), \
             patch.object(mcp_settings, 'client_present', lambda c: c.key == 'cursor'):
            widget = McpSettingsWidget(Path('/repo'), lambda: '/bin/node', QLabel)
            widget.refresh_files()
            install, remove, state = widget.client_rows['cursor']
            self.assertTrue(install.isEnabled() and not remove.isEnabled())
            self.assertFalse(widget.client_rows['gemini'][0].isEnabled())
            widget.model.setEditText('qwen3:30b')
            install.click()
            self.assertEqual(read_entry(widget.clients[1])['env'], {'PROMPTA_MODEL': 'qwen3:30b'})
            self.assertIn('installed · Prompta writes with qwen3:30b', state.text())
            self.assertEqual(install.text(), 'Update')
            remove.click()
            self.assertIn('not installed', state.text())


if __name__ == '__main__':
    unittest.main()
