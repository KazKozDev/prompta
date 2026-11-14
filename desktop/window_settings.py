"""The Settings dialog of the Prompta window: provider and model lists, the generator state, the About page."""

from __future__ import annotations

import json
import platform
import re

from PyQt6.QtCore import QEvent, QSize, QTimer, QUrl, Qt
from PyQt6.QtGui import QDesktopServices, QGuiApplication, QIcon
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

try:
    from .controls import Dropdown
    from .library import data_versions
    from .mcp_settings import generator_state, prefs, write_generator_state
    from .result_view import CONTROL_HEIGHT, field_label
    from .settings_ui import LABEL_GAP, LINK_STYLE, add_section, muted, settings_page, text_link
    from .theme import COMPATIBLE, ROOT
    from .workers import ModelsLoader, TechniquesLoader
except ImportError:
    from controls import Dropdown
    from library import data_versions
    from mcp_settings import generator_state, prefs, write_generator_state
    from result_view import CONTROL_HEIGHT, field_label
    from settings_ui import LABEL_GAP, LINK_STYLE, add_section, muted, settings_page, text_link
    from theme import COMPATIBLE, ROOT
    from workers import ModelsLoader, TechniquesLoader

class SettingsMixin:
    """Settings in the main window: the dialog, provider and model lists, the saved generator, About."""

    def open_settings(self) -> None:
        self.settings_dialog.open()
        if self.settings_tabs.currentIndex() == 0:
            self.api_key.setFocus()
        elif self.settings_tabs.currentIndex() == 2:  # MCP server (wrapped in a scroll area)
            self.mcp_settings.refresh()
        elif self.settings_tabs.currentIndex() == 1:
            self.library.reload()
            self.library.search.setFocus()

    def _sync_settings_footer(self, index: int) -> None:
        """The Done row carries the open tab's footer: Library's summary, MCP's copy link,
        History's delete link, About's links and credits."""
        self.library.summary.setVisible(index == 1)
        self.mcp_settings.copy_button.setVisible(index == 2)
        self.delete_all_history_button.setVisible(index == 3)
        self.about_footer.setVisible(index == 4)
        self.settings_backdrop.setVisible(index == 4)
        self.settings_backdrop.setGeometry(self.settings_dialog.rect())
        self.settings_backdrop.lower()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt naming
        if watched is getattr(self, "settings_dialog", None) and event.type() == QEvent.Type.Resize:
            self.settings_backdrop.setGeometry(self.settings_dialog.rect())  # the About photo covers the whole dialog
        return super().eventFilter(watched, event)

    def _settings_tab_changed(self, index: int) -> None:
        self._sync_settings_footer(index)
        if index == 1:
            self.library.reload()
        elif index == 2:  # MCP server
            self.mcp_settings.refresh()

    @staticmethod
    def about_versions() -> list[tuple[str, str]]:
        return data_versions(ROOT)

    def _about_version_text(self) -> str:
        lines = [f"Prompta {self.APP_VERSION}"] + [f"{name}: {value}" for name, value in self.about_versions()]
        return "\n".join(lines + [f"macOS {platform.mac_ver()[0] or 'unknown'}"])

    def _how_it_works(self) -> str:
        versions = dict(self.about_versions())
        count = (re.search(r"(\d+) entries", versions.get("Technique catalog", "")) or [None, "90"])[1]
        return ("A model reads your request and writes a brief \u2014 the goal, the input, "
                f"the format, and what it had to guess. Then it picks one of {count} prompting techniques, each traced to "
                "a paper or an official doc, and writes the prompt with it.")

    def _build_about_settings(self) -> QWidget:
        link = LINK_STYLE
        page, layout = settings_page(right_margin=330)  # text keeps to the left; the photo (whole dialog) has the right
        title = QLabel(f"Prompta {self.APP_VERSION}")
        title.setObjectName("aboutTitle")
        layout.addWidget(title)
        layout.addSpacing(LABEL_GAP)
        layout.addWidget(muted("Turns a rough request into a structured prompt, "
                               "built from a catalog of sourced prompting techniques and official model guidance."))
        self.about_how = muted(self._how_it_works())  # same grey text as the line above it
        layout.addSpacing(12)  # the description goes on: a paragraph break, not a new section
        layout.addWidget(self.about_how)
        finder = text_link("Show in Finder")
        finder.clicked.connect(self._show_data_folder)
        self.show_data_button = finder
        add_section(layout, "Your data", muted(
            "Everything stays on this Mac: history, its limits and the model list cache in "
            "~/Library/Application Support/Prompta, other settings in ~/.config/Prompta, API keys in the "
            "macOS Keychain. Your requests and prompts go only to the provider chosen in Model & API."), finder)
        self.about_links = QLabel()
        self.about_links.setOpenExternalLinks(False)  # web links open below; "copy:" stays in the app
        self.about_links.linkActivated.connect(self._about_link)
        self._set_about_links()
        add_section(layout, "Project", muted(
            "Techniques come from The Prompt Report (Schulhoff et al.) and the arXiv papers it cites; "
            "guidance comes from the official docs of Anthropic, OpenAI, Google, xAI and Nous Research."))
        layout.addStretch(1)
        # Links and credits go on the dialog's Done row (see _sync_settings_footer).
        self.about_author = QLabel(f'MIT License \u00b7 \u00a9 2025 <a href="{self.AUTHOR_URL}" {link}>{self.AUTHOR}</a>')
        self.about_author.setObjectName("muted")
        self.about_author.setOpenExternalLinks(True)
        self.about_author.setAccessibleName(f"Made by {self.AUTHOR}")
        self.about_footer = QWidget()
        footer = QHBoxLayout(self.about_footer)
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(24)
        footer.addWidget(self.about_links)
        footer.addWidget(self.about_author)
        return page  # it fits the dialog: no scroll area, nothing to bounce

    def _set_about_links(self, copied: bool = False) -> None:
        link = LINK_STYLE
        copy = "\u2713 Copied" if copied else f'<a href="copy:version" {link}>Copy version info</a>'
        self.about_links.setText(f'<a href="{self.REPO_URL}" {link}>Source on GitHub</a> \u00b7 '
                                 f'<a href="{self.REPO_URL}/issues" {link}>Report an issue</a> \u00b7 {copy}')

    def _about_link(self, href: str) -> None:
        if href == "copy:version":
            self.copy_version_info()
        elif href == "finder:data":
            self._show_data_folder()
        else:
            QDesktopServices.openUrl(QUrl(href))

    def copy_version_info(self) -> None:
        """Versions for a bug report, pasted next to "Report an issue"."""
        QGuiApplication.clipboard().setText(self._about_version_text())
        self._set_about_links(copied=True)
        QTimer.singleShot(1600, self._set_about_links)

    def _show_data_folder(self) -> None:
        folder = self.history_store.path.parent
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _mini_label(self, text: str) -> QLabel:
        return field_label(text)

    def load_techniques(self) -> None:
        self.techniques_loader = TechniquesLoader()
        self.techniques_loader.loaded.connect(self._on_techniques_loaded)
        self.techniques_loader.start()

    def _on_techniques_loaded(self, techniques: list) -> None:
        loader = getattr(self, "techniques_loader", None)
        self.prompt_version = getattr(loader, "prompt_version", "") or getattr(self, "prompt_version", "")
        if not techniques:
            return
        for item in techniques:
            if item.get("status") == "procedure":
                item["name"] = f"{item.get('name', item['key'])} (procedure)"
            item["label"] = item.get("name", item["key"])
        self.technique.set_items(techniques, keep=self.technique.current_key())
        self.technique_label.setText(f"TECHNIQUE · {len(techniques)}")
        procedures = sum(1 for item in techniques if item.get("status") == "procedure")
        ready = len(techniques) - procedures
        self.catalog_summary = f"{ready} technique{'s' if ready != 1 else ''}" + (
            f" + {procedures} procedure{'s' if procedures != 1 else ''}" if procedures else "") + " available"
        self._update_advanced_title()

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
        loader = ModelsLoader(provider, api_key, self.model_base_url.text().strip() or self._local_url(provider))
        loader.loaded.connect(lambda names, p=provider, l=loader: self._on_models_loaded(names, p, l.source))
        # A provider switch starts a new fetch while the old one may still run: keep each alive until it ends.
        running = self.__dict__.setdefault("_models_loaders", set())
        running.add(loader)
        loader.finished.connect(lambda l=loader: running.discard(l))
        self.models_loader = loader
        loader.start()

    def _on_models_loaded(self, names: list, provider: str = "ollama", source: str = "") -> None:
        QTimer.singleShot(0, self._sync_model_line)  # the list may change the current model without a signal
        self.refresh_button.setEnabled(True)
        if provider != self.provider.current_key():
            if names:
                self._model_lists[provider] = names  # ready for when the user switches back
            return
        if not names and self.local_providers.get(provider, {}).get("models"):
            names, source = self.local_providers[provider]["models"], "local"
        if not names:
            self.models_hint.setText("Ollama is unavailable at localhost:11434. Using the previous model list."
                                     if provider == "ollama" else "Could not load models. Check the API key and connection, then refresh.")
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
            self.models_hint.setText(f"{count} models from providers.local.json · ↻ asks the provider for its full list")
            return
        self.models_hint.setText(
            f"{count} models from the public models.dev catalog · add the API key for your account's own list"
            if self._list_sources.get(provider) == "catalog" else f"{count} models loaded")

    GENERATOR_PREFS = "generator/state"  # provider, model per provider, URL per provider; keys stay in Keychain

    def _save_generator(self) -> None:
        provider = self.provider.current_key()
        models = {**self._model_choices}
        if provider == COMPATIBLE:
            models[provider] = self.model_name.text().strip()
        else:
            models[provider] = self.model.current_key()
        urls = {**self._base_urls, provider: self.model_base_url.text().strip()}
        state = {"provider": provider, "models": {k: v for k, v in models.items() if v},
                 "urls": {k: v for k, v in urls.items() if v}}
        prefs().setValue(self.GENERATOR_PREFS, json.dumps(state))
        self._publish_generator()

    def _publish_generator(self) -> None:
        """The MCP server follows this file: provider, model, URL and the Keychain item with the key."""
        provider = self.provider.current_key()
        api_provider, model, _, base_url, _ = self._generator_for_mcp()
        write_generator_state(generator_state(api_provider, provider, model, base_url))

    def _restore_generator(self) -> None:
        """Bring back the generator settings of the last session, then load that provider's models."""
        try:
            state = json.loads(prefs().value(self.GENERATOR_PREFS, "", str) or "{}")
        except ValueError:
            state = {}
        known = {item["key"] for item in self.provider._items}
        models = {k: v for k, v in (state.get("models") or {}).items() if k in known and isinstance(v, str)}
        urls = {k: v for k, v in (state.get("urls") or {}).items() if k in known and isinstance(v, str)}
        provider = state.get("provider") if state.get("provider") in known else "ollama"
        self._model_choices.update(models)
        self._base_urls.update(urls)
        self.model_name.setText(models.get(COMPATIBLE, ""))
        if models.get("ollama"):
            self.model.set_current(models["ollama"])
        self.model_base_url.setText(urls.get("ollama", ""))
        if provider == "ollama":
            self.load_models()
        else:
            self.provider.set_current(provider, emit=True)  # shows its key, URL and model, and loads its list

    def _generator_for_mcp(self) -> tuple[str, str, str, str, str]:
        """The MCP server writes with the same provider, model, key and URL as the app."""
        provider = self.provider.current_key()
        return (self._api_provider(provider), self._current_model(), self.api_key.text().strip(),
                self.model_base_url.text().strip() or self._local_url(provider), self.provider.text())

    def _local_url(self, provider: str) -> str:
        return self.local_providers.get(provider, {}).get("base_url", "")

    def _api_provider(self, provider: str) -> str:
        """The pipeline's adapter: OpenAI-compatible servers, built-in or personal, speak the OpenAI API."""
        return "openai" if provider == COMPATIBLE or provider in self.local_providers else provider

    def _reload_models_for_key(self) -> None:
        key = self.api_key.text().strip()
        if self.provider.current_key() not in ("ollama", COMPATIBLE) and key and key != getattr(self, "_listed_key", ""):
            self._listed_key = key
            self.load_models()

    def _current_model(self) -> str:
        """The choice from the provider's list, or the name typed for an OpenAI-compatible server."""
        if self.provider.current_key() == COMPATIBLE:
            return self.model_name.text().strip()
        return self.model.current_key().strip()

    def _on_provider_changed(self, provider: str) -> None:
        if self._url_owner:
            self._base_urls[self._url_owner] = self.model_base_url.text().strip()
        self._model_choices[self._url_owner] = (self.model_name.text().strip() if self._url_owner == COMPATIBLE
                                                else self.model.current_key())
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
        self.model_base_url.setPlaceholderText(self._local_url(provider) or (("Required" if provider == COMPATIBLE else "Optional")
                                               + " · http://127.0.0.1:8080/v1"))
        self._load_saved_key(provider)
        if typed:
            self.models_hint.setText("Type the model name exactly as your server lists it")
        elif names:
            self._show_models_hint(provider, len(names))
        else:
            self.load_models()

    # ── settings: same controls and rhythm as the main window ─────
    def _restyle_settings(self) -> None:
        self.settings_tabs.setObjectName("settingsTabs")
        self.settings_tabs.tabBar().setDrawBase(False)
        self.settings_tabs.tabBar().setExpanding(False)
        self.settings_tabs.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        self.settings_tabs.tabBar().setUsesScrollButtons(False)
        # Tab sizes were measured with the old style; re-polish so the new padding counts.
        for widget in (self.settings_tabs, self.settings_tabs.tabBar()):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        for child in self.settings_dialog.findChildren(QWidget):
            if isinstance(child, QLineEdit) and not isinstance(child.parentWidget(), QComboBox):
                child.setFixedHeight(CONTROL_HEIGHT)
            elif isinstance(child, (QComboBox, Dropdown)):
                child.setFixedHeight(CONTROL_HEIGHT)
            elif isinstance(child, QPushButton) and child.objectName() in ("ghost", "primary"):
                child.setFixedHeight(CONTROL_HEIGHT)
        self.refresh_button.setText("")
        self.refresh_button.setIcon(QIcon(str(ROOT / "desktop" / "refresh.svg")))
        self.refresh_button.setIconSize(QSize(14, 14))
        self.refresh_button.setFixedSize(CONTROL_HEIGHT, CONTROL_HEIGHT)
        self.refresh_button.setToolTip("Refresh the provider's model list")
