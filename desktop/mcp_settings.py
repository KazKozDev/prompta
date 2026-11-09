"""Settings tab for the Prompta MCP server: install it into the major MCP clients, pick its model, copy configs."""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    import yaml  # Hermes keeps its config in YAML
except ImportError:  # pragma: no cover - the app then simply cannot edit Hermes
    yaml = None

from PyQt6.QtCore import QSettings, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

SERVER_NAME = "prompta"
COPY_LABEL = "Copy JSON for other apps"
PROVIDERS = [("ollama", "Ollama (local or :cloud)"), ("openai", "OpenAI-compatible"), ("gemini", "Gemini")]


def find_claude_cli() -> str | None:
    """Prefer the native installer's `claude` (~/.local/bin): a Finder-launched app puts Homebrew first
    in PATH, where an old npm copy of Claude Code may still live and fail to run."""
    for candidate in (str(Path.home() / ".local/bin/claude"), shutil.which("claude"),
                      "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def parse_mcp_get(output: str) -> dict:
    """Parse `claude mcp get prompta`: scope, health and environment (API keys never shown)."""
    info: dict = {"installed": False, "scope": "", "connected": False, "env": {}}
    if f"{SERVER_NAME}:" not in output or "No MCP server" in output:
        return info
    info["installed"] = True
    in_env = False
    for line in output.splitlines():
        text = line.strip()
        if text.startswith("Scope:"):
            info["scope"] = text.removeprefix("Scope:").strip()
        elif text.startswith("Status:"):
            info["connected"] = "Connected" in text
        elif text.startswith("Environment:"):
            in_env = True
            continue
        elif in_env and "=" in text and not text.startswith("To remove"):
            key, _, value = text.partition("=")
            info["env"][key.strip()] = value.strip()
        elif in_env and not text:
            in_env = False
    return info


def server_env(provider: str, model: str, api_key: str = "", base_url: str = "") -> dict[str, str]:
    env = {"PROMPTA_PROVIDER": provider} if provider != "ollama" else {}
    if model.strip():
        env["PROMPTA_MODEL"] = model.strip()
    if api_key.strip():
        env["PROMPTA_API_KEY"] = api_key.strip()
    if base_url.strip():
        env["PROMPTA_BASE_URL"] = base_url.strip()
    return env


def install_commands(claude: str, node: str, server: Path, env: dict[str, str]) -> list[list[str]]:
    """Remove any previous registration, then add it for all projects (user scope)."""
    add = [claude, "mcp", "add", SERVER_NAME, "-s", "user"]
    for key, value in env.items():
        add += ["-e", f"{key}={value}"]
    return [[claude, "mcp", "remove", SERVER_NAME, "-s", "user"], add + ["--", node, str(server)]]


def client_config(node: str, server: Path, env: dict[str, str]) -> str:
    """JSON for Cursor, Claude Desktop and other clients that use the mcpServers format."""
    entry: dict = {"command": node, "args": [str(server)]}
    if env:
        entry["env"] = env
    return json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2)


@dataclass(frozen=True)
class FileClient:
    """An MCP client configured by editing its own config file (everything except Claude Code)."""
    key: str
    name: str
    path: Path          # config file
    fmt: str  # "json" (mcpServers), "vscode" (servers + type), "codex" (TOML), "hermes" (YAML), "openclaw" (its CLI)
    present: tuple[Path, ...]  # any of these existing means the app is on this Mac


def file_clients(home: Path | None = None) -> list[FileClient]:
    home = home or Path.home()
    support = home / "Library" / "Application Support"
    apps = Path("/Applications")
    return [
        FileClient("claude-desktop", "Claude Desktop", support / "Claude" / "claude_desktop_config.json", "json",
                   (support / "Claude", apps / "Claude.app")),
        FileClient("cursor", "Cursor", home / ".cursor" / "mcp.json", "json", (home / ".cursor", apps / "Cursor.app")),
        FileClient("vscode", "VS Code", support / "Code" / "User" / "mcp.json", "vscode",
                   (support / "Code" / "User", apps / "Visual Studio Code.app")),
        FileClient("windsurf", "Windsurf", home / ".codeium" / "windsurf" / "mcp_config.json", "json",
                   (home / ".codeium" / "windsurf", apps / "Windsurf.app")),
        FileClient("gemini", "Gemini CLI", home / ".gemini" / "settings.json", "json", (home / ".gemini",)),
        FileClient("codex", "Codex", home / ".codex" / "config.toml", "codex", (home / ".codex",)),
        FileClient("hermes", "Hermes Agent", home / ".hermes" / "config.yaml", "hermes", (home / ".hermes",)),
        FileClient("openclaw", "OpenClaw (Clawdbot)", home / ".openclaw" / "openclaw.json", "openclaw",
                   (home / ".openclaw",)),
    ]


def find_openclaw_cli() -> str | None:
    for candidate in (str(Path.home() / ".local/bin/openclaw"), shutil.which("openclaw"), shutil.which("clawdbot")):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def openclaw_commands(cli: str, entry: dict | None) -> list[list[str]]:
    """OpenClaw guards its config with a journal, so changes go through its own CLI."""
    if entry is None:
        return [[cli, "mcp", "unset", SERVER_NAME]]
    return [[cli, "mcp", "set", SERVER_NAME, json.dumps(entry)]]


def client_present(client: FileClient) -> bool:
    return any(path.exists() for path in client.present)


def server_entry(client: FileClient, node: str, server: Path, env: dict[str, str]) -> dict:
    entry: dict = {"command": node, "args": [str(server)]}
    if client.fmt == "vscode":
        entry = {"type": "stdio", **entry}
    if client.fmt == "hermes":
        entry["enabled"] = True
    if env:
        entry["env"] = dict(env)
    return entry


def _json_section(client: FileClient) -> str:
    return "servers" if client.fmt == "vscode" else "mcpServers"


def read_entry(client: FileClient) -> dict | None:
    """Prompta's entry in the client's config, None when absent. ValueError when the file is unreadable."""
    if not client.path.exists():
        return None
    text = client.path.read_text(encoding="utf-8")
    try:
        if client.fmt == "codex":
            data = tomllib.loads(text)
            section = data.get("mcp_servers", {})
        elif client.fmt == "hermes":
            if yaml is None:
                raise ValueError("PyYAML is not installed")
            data = yaml.safe_load(text) or {}
            section = (data.get("mcp_servers") or {}) if isinstance(data, dict) else None
        elif client.fmt == "openclaw":
            data = json.loads(text) if text.strip() else {}
            section = ((data.get("mcp") or {}).get("servers") or {}) if isinstance(data, dict) else None
        else:
            data = json.loads(text) if text.strip() else {}
            section = data.get(_json_section(client), {}) if isinstance(data, dict) else None
    except (json.JSONDecodeError, tomllib.TOMLDecodeError, *((yaml.YAMLError,) if yaml else ())) as exc:
        raise ValueError(f"{client.path.name} could not be parsed ({exc})") from exc
    if not isinstance(section, dict):
        raise ValueError(f"{client.path.name} has an unexpected layout")
    entry = section.get(SERVER_NAME)
    return entry if isinstance(entry, dict) else None


def _hermes_text(old: str, entry: dict | None) -> str:
    """Replace only the `prompta:` block under top-level `mcp_servers:`; every other line stays as written."""
    lines = old.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    start = next((i for i, line in enumerate(lines) if re.match(r"^mcp_servers:\s*(#.*)?$", line)), None)
    if start is None:
        if entry is None:
            return old
        lines += (["\n"] if lines and lines[-1].strip() else []) + ["mcp_servers:\n"]
        start = len(lines) - 1
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end][0] in " \t#"):
        end += 1
    block = lines[start + 1:end]
    indents = [len(l) - len(l.lstrip(" ")) for l in block if l.strip() and not l.lstrip().startswith("#")]
    child = min(indents) if indents else 2
    kept, skipping = [], False
    for line in block:
        indent = len(line) - len(line.lstrip(" "))
        if line.strip() and indent == child and not line.lstrip().startswith("#"):
            skipping = re.match(rf"^\s*{SERVER_NAME}:\s*(#.*)?$", line) is not None
        if not skipping:
            kept.append(line)
    added = []
    if entry is not None:
        dumped = yaml.safe_dump({SERVER_NAME: entry}, sort_keys=False, default_flow_style=False, allow_unicode=True)
        added = [" " * child + line + "\n" for line in dumped.splitlines()]
    return "".join(lines[:start + 1] + added + kept + lines[end:])


def _hermes_checked(old: str, new: str, entry: dict | None) -> str:
    """The edit must change nothing in the YAML except Prompta's own entry."""
    before, after = yaml.safe_load(old) or {}, yaml.safe_load(new) or {}
    for data in (before, after):
        if isinstance(data.get("mcp_servers"), dict):
            data["mcp_servers"].pop(SERVER_NAME, None)
            if not data["mcp_servers"]:
                data.pop("mcp_servers")
    if before != after or (yaml.safe_load(new) or {}).get("mcp_servers", {}).get(SERVER_NAME) != entry:
        raise ValueError("config.yaml layout is unusual; edit it by hand")
    return new


_CODEX_HEADER = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")


def _codex_without_prompta(text: str) -> str:
    """Drop [mcp_servers.prompta] and its sub-tables, leaving every other line untouched."""
    kept, skipping = [], False
    for line in text.splitlines(keepends=True):
        header = _CODEX_HEADER.match(line)
        if header:
            name = header.group(1).replace('"', "").replace(" ", "")
            skipping = name == f"mcp_servers.{SERVER_NAME}" or name.startswith(f"mcp_servers.{SERVER_NAME}.")
        if not skipping:
            kept.append(line)
    return "".join(kept).rstrip("\n") + "\n" if "".join(kept).strip() else ""


def _codex_block(entry: dict) -> str:
    lines = [f"[mcp_servers.{SERVER_NAME}]", f"command = {json.dumps(entry['command'])}",
             f"args = {json.dumps(entry['args'])}"]
    if entry.get("env"):
        pairs = ", ".join(f"{json.dumps(k)} = {json.dumps(v)}" for k, v in entry["env"].items())
        lines.append(f"env = {{ {pairs} }}")
    return "\n".join(lines) + "\n"


def write_entry(client: FileClient, entry: dict | None) -> None:
    """Install (entry) or remove (None) Prompta. Keeps a .bak copy and never rewrites a file it cannot parse."""
    read_entry(client)  # raises on an unparsable file before anything is touched
    old = client.path.read_text(encoding="utf-8") if client.path.exists() else ""
    if client.fmt == "openclaw":
        raise ValueError("OpenClaw is changed through its CLI")
    if client.fmt == "hermes":
        new = _hermes_checked(old, _hermes_text(old, entry), entry)
    elif client.fmt == "codex":
        new = _codex_without_prompta(old)
        if entry is not None:
            new = (new + "\n" if new else "") + _codex_block(entry)
        tomllib.loads(new)  # the result must still be valid TOML
    else:
        data = json.loads(old) if old.strip() else {}
        section = data.setdefault(_json_section(client), {})
        if entry is None:
            section.pop(SERVER_NAME, None)
        else:
            section[SERVER_NAME] = entry
        new = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if new == old:
        return
    client.path.parent.mkdir(parents=True, exist_ok=True)
    if old:
        client.path.with_name(client.path.name + ".bak").write_text(old, encoding="utf-8")
    client.path.write_text(new, encoding="utf-8")


def model_note(env: dict) -> str:
    """The model Prompta itself writes prompts with; the agent keeps its own model."""
    return f"Prompta writes with {env.get('PROMPTA_MODEL') or 'auto model'}"


def prefs() -> QSettings:
    """Ini file in the user's config dir; tests redirect it with QSettings.setPath."""
    return QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "Prompta", "Prompta")


class StateLabel(QLabel):
    """Status text whose leading ● is green (installed) and ○ grey (not installed)."""
    DOTS = {"●": "#3fa34d", "○": "#a99c7c"}

    def setText(self, text: str) -> None:  # noqa: N802
        dot = text[:1]
        if dot in self.DOTS:
            text = f'<span style="color:{self.DOTS[dot]}">{dot}</span>{html.escape(text[1:])}'
        else:
            text = html.escape(text)
        super().setText(text)


class CommandRunner(QThread):
    """Run CLI commands off the UI thread; emits (returncode, combined output) of the last command."""
    done = pyqtSignal(int, str)

    def __init__(self, commands: list[list[str]], tolerate_first_failure: bool = False) -> None:
        super().__init__()
        self.commands = commands
        self.tolerate_first_failure = tolerate_first_failure

    def run(self) -> None:
        code, output = 0, ""
        for index, command in enumerate(self.commands):
            try:
                proc = subprocess.run(command, capture_output=True, text=True, timeout=90)
                code, output = proc.returncode, (proc.stdout + proc.stderr)
            except (OSError, subprocess.TimeoutExpired) as exc:
                code, output = 1, str(exc)
            if code != 0 and not (index == 0 and self.tolerate_first_failure):
                break
        self.done.emit(code, output)


class McpSettingsWidget(QWidget):
    def __init__(self, root: Path, node_binary: Callable[[], str], mini_label: Callable[[str], QLabel],
                 combo: Callable[[], QComboBox] = QComboBox) -> None:
        super().__init__()
        self.server = root / "mcp" / "server.ts"
        self.node_binary = node_binary
        self.runner: CommandRunner | None = None
        self.installed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 18, 12, 0)  # right gap keeps buttons off the scroll bar
        layout.setSpacing(12)
        intro = QLabel("Lets coding agents and chat apps that support MCP (Claude Code, Codex, Cursor, VS Code, "
                       "Claude Desktop, Gemini CLI, Windsurf, Hermes, OpenClaw) call Prompta with their conversation as context: improve a prompt or suggest what to ask next.")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addSpacing(6)  # air between the intro and the fields

        self.status = QLabel("")
        self.status.hide()  # shown only while it has something to say
        self.status.setObjectName("section")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        layout.addWidget(mini_label("Provider"))
        self.provider = combo()  # the app passes its own list dropdown for a uniform look
        for key, label in PROVIDERS:
            self.provider.addItem(label, key)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        layout.addWidget(self.provider)

        layout.addWidget(mini_label("Model"))
        self.model = combo()
        self.model.setEditable(True)
        self.model.lineEdit().setPlaceholderText("e.g. kimi-k3:cloud or qwen3:30b")
        layout.addWidget(self.model)

        self.key_label = mini_label("API key")
        layout.addWidget(self.key_label)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Only for OpenAI-compatible or Gemini")
        layout.addWidget(self.api_key)

        layout.addWidget(mini_label("Apps"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        self.install_button, self.remove_button, self.claude_state = self._client_row(grid, 0, "Claude Code")
        self.install_button.clicked.connect(self.install)
        self.remove_button.clicked.connect(self.remove)
        self._restore_claude_state()
        self.clients = file_clients()
        self.client_rows: dict[str, tuple[QPushButton, QPushButton, QLabel]] = {}
        for row, client in enumerate(self.clients, start=1):
            install, remove, state = self._client_row(grid, row, client.name)
            install.clicked.connect(lambda _=False, c=client: self.install_file(c))
            remove.clicked.connect(lambda _=False, c=client: self.remove_file(c))
            self.client_rows[client.key] = (install, remove, state)
        layout.addLayout(grid)

        actions = QHBoxLayout()
        self.copy_button = QPushButton(COPY_LABEL)  # plain text link: one click copies the JSON
        self.copy_button.setObjectName("textLink")
        self.copy_button.setFlat(True)
        self.copy_button.setStyleSheet(
            "QPushButton#textLink { background: transparent; border: none; padding: 0; color: #806a3d; font-weight: 500; }"
            "QPushButton#textLink:hover { color: #4a3d1d; text-decoration: underline; }")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.setToolTip("Copy the mcpServers JSON for any other MCP app")
        self.copy_button.clicked.connect(self.copy_config)
        actions.addWidget(self.copy_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        note = QLabel("The model above is the one Prompta writes prompts with; each agent keeps its own model for its "
                      "work. Agents send their conversation to Prompta's model. Models ending in :cloud run on ollama.com; "
                      "local Ollama models keep everything on this Mac. API keys and tokens are redacted from the "
                      "conversation first. An API key entered here is saved in each app's MCP config. A .bak copy of "
                      "a config is kept before each change. Restart the app or agent session after changes.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self._provider_changed()

    @staticmethod
    def _client_row(grid: QGridLayout, row: int, name: str) -> tuple[QPushButton, QPushButton, QLabel]:
        title = QLabel(name)
        title.setObjectName("techName")
        state = StateLabel("…")
        state.setObjectName("muted")
        state.setTextFormat(Qt.TextFormat.RichText)
        install = QPushButton("Install")
        install.setObjectName("primary")
        remove = QPushButton("Remove")
        remove.setObjectName("ghost")
        for button in (install, remove):
            button.setProperty("compact", True)  # smaller than the dialog's main buttons (QSS in app.py)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(f"{button.text()} · {name}")
        grid.addWidget(title, row, 0)
        grid.addWidget(state, row, 1)
        grid.addWidget(install, row, 2)
        grid.addWidget(remove, row, 3)
        return install, remove, state

    def showEvent(self, event) -> None:  # noqa: N802
        # The tab is polished on first show and QSS `min-height` then wins over the app's fixed
        # height; re-pin it so the apps list cannot squeeze the inputs.
        super().showEvent(event)
        for field in (self.provider, self.model, self.api_key):
            field.setFixedHeight(28)  # CONTROL_HEIGHT in app.py
        for button in self.findChildren(QPushButton):
            if button.property("compact"):
                button.setFixedHeight(22)  # the app's dialog setup pins buttons to 28; app rows stay compact

    def _restore_claude_state(self) -> None:
        """Show the last known Claude Code status at once: the CLI check takes a few seconds."""
        store = prefs()
        text = store.value("mcp/claude_state", "", str)
        if text:
            installed = store.value("mcp/claude_installed", False, bool)
            self.claude_state.setText(text)
            self.install_button.setText("Update" if installed else "Install")
            self.remove_button.setEnabled(installed)

    def _remember_claude_state(self, text: str, installed: bool) -> None:
        self.claude_state.setText(text)
        store = prefs()
        store.setValue("mcp/claude_state", text)
        store.setValue("mcp/claude_installed", installed)
        store.sync()

    def _say(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    # ── state ─────────────────────────────────────────────────────
    def set_models(self, names: list[str]) -> None:
        current = self.model.currentText()
        self.model.clear()
        self.model.addItems(names)
        self.model.setEditText(current)

    def _provider_changed(self, *_: object) -> None:
        needs_key = self.provider.currentData() != "ollama"
        self.key_label.setVisible(needs_key)
        self.api_key.setVisible(needs_key)

    def _env(self) -> dict[str, str]:
        key = self.api_key.text() if self.provider.currentData() != "ollama" else ""
        return server_env(self.provider.currentData(), self.model.currentText(), key)

    def _busy(self, busy: bool, message: str = "") -> None:
        for button in (self.install_button, self.remove_button):
            button.setEnabled(not busy)
        if message:
            self._say(message)

    def _run(self, commands: list[list[str]], on_done: Callable[[int, str], None], tolerate_first_failure: bool = False) -> None:
        if self.runner is not None and self.runner.isRunning():
            return
        self.runner = CommandRunner(commands, tolerate_first_failure)
        self.runner.done.connect(on_done)
        self.runner.start()

    # ── actions ───────────────────────────────────────────────────
    def refresh(self) -> None:
        self.refresh_files()
        claude = find_claude_cli()
        if claude is None:
            self.claude_state.setText("not found on this Mac")
            self.install_button.setEnabled(False)
            self.remove_button.setEnabled(False)
            return
        self._busy(True)
        if not prefs().value("mcp/claude_state", "", str):
            self.claude_state.setText("checking…")  # otherwise keep the remembered status while checking
        self._run([[claude, "mcp", "get", SERVER_NAME]], self._show_status)

    def _show_status(self, code: int, output: str) -> None:
        if code != 0 and "No MCP server" not in output:
            # A failing CLI is not the same as "not installed": say what happened.
            self._busy(False)
            self.remove_button.setEnabled(False)
            last = next((line.strip() for line in reversed(output.strip().splitlines()) if line.strip()), "no output")
            self.claude_state.setText("could not check")
            self._say(f"Could not check Claude Code ({find_claude_cli()}): {last[:160]}")
            return
        info = parse_mcp_get(output if code == 0 else "")
        self.installed = info["installed"]
        self._busy(False)
        self.install_button.setText("Update" if self.installed else "Install")
        self.remove_button.setEnabled(self.installed)
        if not self.installed:
            self._remember_claude_state("○  not installed", False)
            return
        env = info["env"]
        index = self.provider.findData(env.get("PROMPTA_PROVIDER", "ollama"))
        self.provider.setCurrentIndex(max(0, index))
        self.model.setEditText(env.get("PROMPTA_MODEL", ""))
        scope = "all projects" if info["scope"].startswith("User") else (info["scope"] or "unknown scope")
        health = "connected" if info["connected"] else "installed, not connected"
        self._remember_claude_state(f"●  {health} · {scope} · {model_note(env)}", True)

    def install(self) -> None:
        claude = find_claude_cli()
        if claude is None:
            self.refresh()
            return
        if not self.model.currentText().strip():
            self._say("Choose a model first")
            return
        self._busy(True)
        self.claude_state.setText("installing…")
        commands = install_commands(claude, self.node_binary(), self.server, self._env())
        self._run(commands, self._after_change, tolerate_first_failure=True)

    def remove(self) -> None:
        claude = find_claude_cli()
        if claude is None:
            return
        self._busy(True)
        self.claude_state.setText("removing…")
        self._run([[claude, "mcp", "remove", SERVER_NAME, "-s", "user"]], self._after_change)

    def _after_change(self, code: int, output: str) -> None:
        if code != 0:
            self._busy(False, f"Claude Code reported an error: {output.strip()[-200:]}")
            return
        self.runner = None
        self.refresh()

    # ── config-file clients ───────────────────────────────────────
    def refresh_files(self) -> None:
        for client in self.clients:
            install, remove, state = self.client_rows[client.key]
            if not client_present(client):
                install.setText("Install")
                install.setEnabled(False)
                remove.setEnabled(False)
                state.setText("not found on this Mac")
                continue
            try:
                entry = read_entry(client)
            except (OSError, ValueError) as exc:
                install.setEnabled(False)
                remove.setEnabled(False)
                state.setText("config unreadable")
                state.setToolTip(str(exc))
                continue
            state.setToolTip(str(client.path))
            install.setEnabled(True)
            install.setText("Update" if entry else "Install")
            remove.setEnabled(entry is not None)
            env = (entry or {}).get("env") or {}
            state.setText(f"●  installed · {model_note(env)}" if entry else "○  not installed")
            if entry and not self.model.currentText().strip() and env.get("PROMPTA_MODEL"):
                self.provider.setCurrentIndex(max(0, self.provider.findData(env.get("PROMPTA_PROVIDER", "ollama"))))
                self.model.setEditText(env["PROMPTA_MODEL"])

    def install_file(self, client: FileClient) -> None:
        if not self.model.currentText().strip():
            self._say("Choose a model first")
            return
        self._change_file(client, server_entry(client, self.node_binary(), self.server, self._env()), "installed in")

    def remove_file(self, client: FileClient) -> None:
        self._change_file(client, None, "removed from")

    def _change_file(self, client: FileClient, entry: dict | None, verb: str) -> None:
        if client.fmt == "openclaw":
            cli = find_openclaw_cli()
            if cli is None:
                self._say("OpenClaw CLI not found")
                return
            self.client_rows[client.key][2].setText("working…")

            def done(code: int, output: str) -> None:
                self.runner = None
                last = next((l.strip() for l in reversed(output.strip().splitlines()) if l.strip()), "")
                self._say(f"Prompta {verb} {client.name}. Restart its gateway to apply." if code == 0
                          else f"{client.name}: nothing changed — {last[:160]}")
                self.refresh_files()
            self._run(openclaw_commands(cli, entry), done)
            return
        try:
            write_entry(client, entry)
        except (OSError, ValueError) as exc:
            self._say(f"{client.name}: nothing changed — {exc}")
        else:
            self._say(f"Prompta {verb} {client.name}. Restart {client.name} to apply.")
        self.refresh_files()

    def copy_config(self) -> None:
        QGuiApplication.clipboard().setText(client_config(self.node_binary(), self.server, self._env()))
        self.copy_button.setText("✓  Copied to clipboard")
        QTimer.singleShot(1600, lambda: self.copy_button.setText(COPY_LABEL))
