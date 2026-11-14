"""Settings → Model & API: the model that writes the prompts.

Each provider keeps its own model, key and URL. Keys live in the macOS Keychain (or only in memory);
the choice is saved in QSettings and published for the MCP server. No window: the page takes the personal
providers it should offer and reports through signals.
"""

from __future__ import annotations

import json
import os
from functools import partial

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

import keychain
from controls import Dropdown
from mcp_settings import generator_state, prefs, write_generator_state
from result_view import CONTROL_HEIGHT
from settings_ui import add_section, settings_page
from theme import COMPATIBLE, ROOT
from workers import FALLBACK_MODELS, ModelsLoader

BUILTIN_PROVIDERS = [
    {"key": "ollama", "label": "Ollama (local/cloud)"},
    {"key": "gemini", "label": "Gemini"},
    {"key": "openai", "label": "OpenAI"},
    {"key": COMPATIBLE, "label": "OpenAI-compatible"},
    {"key": "anthropic", "label": "Anthropic (Claude)"},
    {"key": "xai", "label": "xAI (Grok)"},
]


class GeneratorSettings(QWidget):
    """The Model & API tab. `changed` fires whenever the generator line under Build would read differently;
    `notice` carries a message for the window's status line."""

    changed = pyqtSignal()
    notice = pyqtSignal(str)

    GENERATOR_PREFS = "generator/state"  # provider, model per provider, URL per provider; keys stay in Keychain
    # Fetches still running, kept alive past a provider switch and past the page itself: a thread must end first.
    _running_loaders: set[ModelsLoader] = set()

    def __init__(self, local_providers: dict[str, dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.local_providers = local_providers
        self._restoring = False
        self._listed_key = ""  # the key the shown model list was fetched with
        self.models_loader: ModelsLoader | None = None
        self._changed_soon = QTimer(self)  # owned by the page: it never fires after the page is gone
        self._changed_soon.setSingleShot(True)
        self._changed_soon.setInterval(0)
        self._changed_soon.timeout.connect(self._emit_changed)

        self.provider = Dropdown("Ollama", popup_width=300)
        self.provider.set_items(
            BUILTIN_PROVIDERS + [{"key": key, "label": item["label"]} for key, item in local_providers.items()]
        )
        self.provider.set_current("ollama")
        self._url_owner = "ollama"

        model_row = QHBoxLayout()
        model_row.setSpacing(6)
        self.model = Dropdown("Choose a model", searchable=True, popup_width=460, search_placeholder="Filter models")
        self.model.set_items([{"key": name, "label": name} for name in FALLBACK_MODELS])
        self.model.set_current("minimax-m3.1-flash:cloud")
        model_row.addWidget(self.model, 1)
        # Other providers have no list to pick from: their model name is typed by hand, kept per provider.
        self.model_name = QLineEdit()
        self.model_name.setPlaceholderText("Model name, e.g. gpt-5.1 or mlx-community/Qwen3-8B")
        self.model_name.setAccessibleName("Model name")
        self.model_name.hide()
        self._model_lists: dict[str, list[str]] = {}  # each provider shows only its own models
        self._list_sources: dict[str, str] = {}  # "catalog" when a list came from models.dev, not the provider
        for key, item in local_providers.items():  # a personal provider starts with the models it names
            if item["models"]:
                self._model_lists[key] = item["models"]
                self._list_sources[key] = "local"
        self._model_choices: dict[str, str] = {}
        model_row.addWidget(self.model_name, 1)
        self.refresh_button = QPushButton()
        self.refresh_button.setObjectName("ghost")
        self.refresh_button.setIcon(QIcon(str(ROOT / "desktop" / "refresh.svg")))
        self.refresh_button.setIconSize(QSize(14, 14))
        self.refresh_button.setFixedSize(CONTROL_HEIGHT, CONTROL_HEIGHT)
        self.refresh_button.setToolTip("Refresh the provider's model list")
        self.refresh_button.clicked.connect(self.load_models)
        model_row.addWidget(self.refresh_button)
        self.models_hint = QLabel("Loading Ollama models")
        self.models_hint.setObjectName("muted")
        self.models_hint.setWordWrap(True)

        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Not needed for Ollama and local servers")
        self.api_key.setAccessibleName("API key")
        self.remember_key = QCheckBox("Remember in Keychain")
        self.remember_key.setToolTip(
            "Save this provider's key in your macOS login Keychain and fill it in next time. "
            "Unchecking removes the saved key; without it the key stays in memory until you quit."
        )
        self.remember_key.toggled.connect(self._on_remember_key_toggled)
        self.remember_key.setObjectName("settingsCheck")
        self.model_base_url = QLineEdit()
        self._base_urls: dict[str, str] = {}  # each provider keeps its own URL while you switch between them
        self.model_base_url.setPlaceholderText("Optional · http://127.0.0.1:8080/v1")
        self.model_base_url.setAccessibleName("Model base URL")
        self.model_base_url.setToolTip(
            "Requests and any API key you enter go to this endpoint. Empty uses the provider's "
            "default; OpenAI-compatible servers (MLX, LM Studio, vLLM, OpenRouter) need theirs."
        )

        # The app's own form: a caps label over each full-width field, shared gaps, one grey line where it helps.
        _, layout = settings_page(
            "The model that writes your prompts. Each provider keeps its own model, key and URL.", page=self
        )
        add_section(layout, "Provider", self.provider)
        add_section(layout, "Model", model_row, hint=self.models_hint)
        add_section(layout, "API key", self.api_key)
        layout.addSpacing(10)
        layout.addWidget(self.remember_key)  # under the key, flush with the fields
        add_section(
            layout,
            "Base URL",
            self.model_base_url,
            hint="Empty uses the provider's default. OpenAI-compatible servers need their own.",
        )
        self._load_saved_key(self.provider.current_key())
        layout.addStretch(1)

        self.provider.changed.connect(self._on_provider_changed)  # first: the page switches before anyone reads it
        # Bound methods, not lambdas: Qt drops these connections when the page goes, lambdas would outlive it.
        for edited in (self.provider.changed, self.model.changed, self.model_name.textChanged):
            edited.connect(self._emit_changed)
        self.model_base_url.textChanged.connect(self._emit_changed)
        self.api_key.editingFinished.connect(self._reload_models_for_key)  # a new key can unlock the provider's list
        for signal in (
            self.provider.changed,
            self.model.changed,
            self.model_name.editingFinished,
            self.model_base_url.editingFinished,
        ):
            signal.connect(self._save_on_edit)

    def _emit_changed(self, *_: object) -> None:
        self.changed.emit()

    def _save_on_edit(self, *_: object) -> None:
        self.save()

    # ── what the rest of the app reads ────────────────────────────
    def current_model(self) -> str:
        """The choice from the provider's list, or the name typed for an OpenAI-compatible server."""
        if self.provider.current_key() == COMPATIBLE:
            return self.model_name.text().strip()
        return self.model.current_key().strip()

    def local_url(self, provider: str) -> str:
        return self.local_providers.get(provider, {}).get("base_url", "")

    def api_provider(self, provider: str) -> str:
        """The pipeline's adapter: OpenAI-compatible servers, built-in or personal, speak the OpenAI API."""
        return "openai" if provider == COMPATIBLE or provider in self.local_providers else provider

    def base_url(self) -> str:
        return self.model_base_url.text().strip() or self.local_url(self.provider.current_key())

    def model_line(self) -> str:
        """The line under Build: which model writes the prompt, and where."""
        model = self.current_model()
        where = self.provider.text() + (" · custom URL" if self.model_base_url.text().strip() else "")
        return f"Generator model: {model} · {where}" if model else "Generator model: none chosen · open Settings"

    def request(self) -> tuple[dict[str, str], str]:
        """The generator part of a pipeline request, or ({}, what to fix first)."""
        provider = self.provider.current_key()
        model = self.current_model()
        api_key = self.api_key.text().strip()
        if self.remember_key.isChecked() and api_key and api_key != keychain.load(provider):
            keychain.save(provider, api_key)  # the key that works is the one to remember
        if not model:
            return {}, "Choose a model"
        base_url = self.base_url()
        if provider == COMPATIBLE and not base_url:
            return {}, "Add the server URL in Settings"
        if provider not in ("ollama", COMPATIBLE) and not api_key and not (provider == "openai" and base_url):
            return {}, "Add an API key in Settings"
        return {"provider": self.api_provider(provider), "model": model, "apiKey": api_key, "baseUrl": base_url}, ""

    def for_mcp(self) -> tuple[str, str, str, str, str]:
        """The MCP server writes with the same provider, model, key and URL as the app."""
        provider = self.provider.current_key()
        return (
            self.api_provider(provider),
            self.current_model(),
            self.api_key.text().strip(),
            self.base_url(),
            self.provider.text(),
        )

    def key_missing_for_mcp(self) -> str:
        """The provider whose key the MCP server cannot read from Keychain, or "" when nothing is missing."""
        provider = self.provider.current_key()
        if provider == "ollama" or (provider == COMPATIBLE and not self.api_key.text().strip()):
            return ""
        local = self.local_providers.get(provider)
        if local and local.get("api_key"):  # the server reads providers.local.json too; an env var it may not see
            return ""
        return "" if keychain.load(provider) else self.provider.text()

    # ── keys ──────────────────────────────────────────────────────
    def _load_saved_key(self, provider: str) -> None:
        """Each provider has its own key: show the saved one, or an empty field."""
        saved = keychain.load(provider) if provider != "ollama" else ""
        local = self.local_providers.get(provider)
        remembered = bool(saved)
        if local and not saved:  # a personal provider may keep its key in its env var or the gitignored file
            saved = os.environ.get(str(local.get("key_env") or ""), "") or str(local.get("api_key") or "")
        self.api_key.setText(saved)
        previous = self.remember_key.blockSignals(True)
        self.remember_key.setChecked(remembered)
        self.remember_key.blockSignals(previous)

    def _on_remember_key_toggled(self, checked: bool) -> None:
        provider = self.provider.current_key()
        if checked:
            key = self.api_key.text().strip()
            if key and not keychain.save(provider, key):
                self.notice.emit("Could not save the key to Keychain")
        else:
            keychain.forget(provider)

    # ── model lists ───────────────────────────────────────────────
    def load_models(self) -> None:
        """Fetch the chosen provider's models: Ollama's local list, or the cloud provider's own list with the key."""
        provider = self.provider.current_key()
        if provider == COMPATIBLE:
            return
        api_key = self.api_key.text().strip()
        self.models_hint.setText("Fetching Ollama models" if provider == "ollama" else "Fetching models")
        self.refresh_button.setEnabled(False)
        if provider != "ollama":
            self._listed_key = api_key
        loader = ModelsLoader(provider, api_key, self.base_url())
        loader.loaded.connect(self._models_arrived)  # a bound slot: Qt drops it if the page is gone first
        running = GeneratorSettings._running_loaders
        running.add(loader)
        # Released on the main thread once it is done, even if this page is gone by then.
        loader.finished.connect(  # type: ignore[call-arg]  # the stubs omit connect's connection type
            partial(running.discard, loader), Qt.ConnectionType.QueuedConnection
        )
        self.models_loader = loader
        loader.start()

    def _models_arrived(self, names: list) -> None:
        loader = self.sender()
        if isinstance(loader, ModelsLoader):
            self._on_models_loaded(names, loader.provider, loader.source)

    def _on_models_loaded(self, names: list, provider: str = "ollama", source: str = "") -> None:
        self._changed_soon.start()  # the list may change the current model without a signal
        self.refresh_button.setEnabled(True)
        if provider != self.provider.current_key():
            if names:
                self._model_lists[provider] = names  # ready for when the user switches back
            return
        if not names and self.local_providers.get(provider, {}).get("models"):
            names, source = self.local_providers[provider]["models"], "local"
        if not names:
            self.models_hint.setText(
                "Ollama is unavailable at localhost:11434. Using the previous model list."
                if provider == "ollama"
                else "Could not load models. Check the API key and connection, then refresh."
            )
            return

        self._model_lists[provider] = names
        current = self.model.current_key().strip()
        self.model.set_items([{"key": name, "label": name} for name in names], keep=current)
        if not self.model.current_key() or current not in names:
            self.model.set_current(names[0])
        self._list_sources[provider] = source
        self._show_models_hint(provider, len(names))

    def _show_models_hint(self, provider: str, count: int) -> None:
        if self._list_sources.get(provider) == "local":
            self.models_hint.setText(
                f"{count} models from providers.local.json · ↻ asks the provider for its full list"
            )
            return
        self.models_hint.setText(
            f"{count} models from the public models.dev catalog · add the API key for your account's own list"
            if self._list_sources.get(provider) == "catalog"
            else f"{count} models loaded"
        )

    def _reload_models_for_key(self) -> None:
        key = self.api_key.text().strip()
        if self.provider.current_key() not in ("ollama", COMPATIBLE) and key and key != self._listed_key:
            self._listed_key = key
            self.load_models()

    def _on_provider_changed(self, provider: str) -> None:
        if self._url_owner:
            self._base_urls[self._url_owner] = self.model_base_url.text().strip()
        self._model_choices[self._url_owner] = (
            self.model_name.text().strip() if self._url_owner == COMPATIBLE else self.model.current_key()
        )
        self._model_lists.setdefault(self._url_owner, [i["key"] for i in self.model._items])
        self._url_owner = provider
        typed = provider == COMPATIBLE  # a custom server: its model name is typed, not picked
        self.model.setVisible(not typed)
        self.refresh_button.setVisible(not typed)
        self.model_name.setVisible(typed)
        if typed:
            self.model_name.setText(self._model_choices.get(COMPATIBLE, ""))
        names = self._model_lists.get(provider, [])
        self.model.set_items([{"key": name, "label": name} for name in names])
        self.model.set_current(self._model_choices.get(provider, "") or (names[0] if names else ""))
        self.model_base_url.setText(self._base_urls.get(provider, ""))
        self.model_base_url.setPlaceholderText(
            self.local_url(provider)
            or (("Required" if provider == COMPATIBLE else "Optional") + " · http://127.0.0.1:8080/v1")
        )
        self._load_saved_key(provider)
        if typed:
            self.models_hint.setText("Type the model name exactly as your server lists it")
        elif names:
            self._show_models_hint(provider, len(names))
        else:
            self.load_models()

    # ── saved state ───────────────────────────────────────────────
    def save(self) -> None:
        if self._restoring:
            return  # restoring replays the last session's choice: nothing new to save
        provider = self.provider.current_key()
        models = {**self._model_choices}
        if provider == COMPATIBLE:
            models[provider] = self.model_name.text().strip()
        else:
            models[provider] = self.model.current_key()
        urls = {**self._base_urls, provider: self.model_base_url.text().strip()}
        state = {
            "provider": provider,
            "models": {k: v for k, v in models.items() if v},
            "urls": {k: v for k, v in urls.items() if v},
        }
        prefs().setValue(self.GENERATOR_PREFS, json.dumps(state))
        self.publish()

    def publish(self) -> None:
        """The MCP server follows this file: provider, model, URL and the Keychain item with the key."""
        api_provider, model, _, base_url, _ = self.for_mcp()
        write_generator_state(generator_state(api_provider, self.provider.current_key(), model, base_url))

    def restore(self) -> None:
        """Bring back the generator settings of the last session, load that provider's models and publish them:
        the MCP server sees the restored choice even before anything changes."""
        try:
            state = json.loads(prefs().value(self.GENERATOR_PREFS, "", str) or "{}")
        except ValueError:
            state = {}
        known = {item["key"] for item in self.provider._items}
        models = {k: v for k, v in (state.get("models") or {}).items() if k in known and isinstance(v, str)}
        urls = {k: v for k, v in (state.get("urls") or {}).items() if k in known and isinstance(v, str)}
        provider = str(state["provider"]) if state.get("provider") in known else "ollama"
        self._model_choices.update(models)
        self._base_urls.update(urls)
        self._restoring = True
        try:
            self.model_name.setText(models.get(COMPATIBLE, ""))
            if models.get("ollama"):
                self.model.set_current(models["ollama"])
            self.model_base_url.setText(urls.get("ollama", ""))
            if provider == "ollama":
                self.load_models()
            else:
                self.provider.set_current(provider, emit=True)  # shows its key, URL and model, and loads its list
        finally:
            self._restoring = False
        self.publish()
