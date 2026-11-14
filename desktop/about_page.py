"""Settings → About: what Prompta does, where its data lives, links and credits.

The page takes the version, the credits and the data folder; `footer` holds the links and the licence line
that the Settings dialog shows on its Done row while About is open.
"""

from __future__ import annotations

import platform
import re
from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from library import data_versions
from settings_ui import LABEL_GAP, LINK_STYLE, add_section, muted, settings_page, text_link
from theme import ROOT


class AboutPage(QWidget):
    def __init__(
        self,
        version: str,
        author: str,
        author_url: str,
        repo_url: str,
        data_folder: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.version, self.repo_url, self.data_folder = version, repo_url, data_folder
        # Text keeps to the left; the photo (whole dialog) has the right.
        _, layout = settings_page(right_margin=330, page=self)
        title = QLabel(f"Prompta {version}")
        title.setObjectName("aboutTitle")
        layout.addWidget(title)
        layout.addSpacing(LABEL_GAP)
        layout.addWidget(
            muted(
                "Turns a rough request into a structured prompt, "
                "built from a catalog of sourced prompting techniques and official model guidance."
            )
        )
        self.how = muted(self.how_it_works())  # same grey text as the line above it
        layout.addSpacing(12)  # the description goes on: a paragraph break, not a new section
        layout.addWidget(self.how)
        self.show_data_button = text_link("Show in Finder")
        self.show_data_button.clicked.connect(self.show_data_folder)
        add_section(
            layout,
            "Your data",
            muted(
                "Everything stays on this Mac: history, its limits and the model list cache in "
                "~/Library/Application Support/Prompta, other settings in ~/.config/Prompta, API keys in the "
                "macOS Keychain. Your requests and prompts go only to the provider chosen in Model & API."
            ),
            self.show_data_button,
        )
        self.links = QLabel()
        self.links.setOpenExternalLinks(False)  # web links open below; "copy:" stays in the app
        self.links.linkActivated.connect(self._link)
        self._set_links()
        add_section(
            layout,
            "Project",
            muted(
                "Techniques come from The Prompt Report (Schulhoff et al.) and the arXiv papers it cites; "
                "guidance comes from the official docs of Anthropic, OpenAI, Google, xAI and Nous Research."
            ),
        )
        layout.addStretch(1)  # it fits the dialog: no scroll area, nothing to bounce
        self.author = QLabel(f'MIT License · © 2026 <a href="{author_url}" {LINK_STYLE}>{author}</a>')
        self.author.setObjectName("muted")
        self.author.setOpenExternalLinks(True)
        self.author.setAccessibleName(f"Made by {author}")
        self.footer = QWidget()
        footer = QHBoxLayout(self.footer)
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(24)
        footer.addWidget(self.links)
        footer.addWidget(self.author)

    @staticmethod
    def versions() -> list[tuple[str, str]]:
        return data_versions(ROOT)

    def version_text(self) -> str:
        lines = [f"Prompta {self.version}"] + [f"{name}: {value}" for name, value in self.versions()]
        return "\n".join(lines + [f"macOS {platform.mac_ver()[0] or 'unknown'}"])

    def how_it_works(self) -> str:
        versions = dict(self.versions())
        count = (re.search(r"(\d+) entries", versions.get("Technique catalog", "")) or [None, "90"])[1]
        return (
            "A model reads your request and writes a brief — the goal, the input, "
            f"the format, and what it had to guess. Then it picks one of {count} prompting techniques, each traced to "
            "a paper or an official doc, and writes the prompt with it."
        )

    def _set_links(self, copied: bool = False) -> None:
        link = LINK_STYLE
        copy = "✓ Copied" if copied else f'<a href="copy:version" {link}>Copy version info</a>'
        self.links.setText(
            f'<a href="{self.repo_url}" {link}>Source on GitHub</a> · '
            f'<a href="{self.repo_url}/issues" {link}>Report an issue</a> · {copy}'
        )

    def _link(self, href: str) -> None:
        if href == "copy:version":
            self.copy_version_info()
        elif href == "finder:data":
            self.show_data_folder()
        else:
            QDesktopServices.openUrl(QUrl(href))

    def copy_version_info(self) -> None:
        """Versions for a bug report, pasted next to "Report an issue"."""
        QGuiApplication.clipboard().setText(self.version_text())
        self._set_links(copied=True)
        QTimer.singleShot(1600, self._set_links)

    def show_data_folder(self) -> None:
        self.data_folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.data_folder)))
