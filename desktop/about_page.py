"""Settings → About: what Prompta does, where its data lives, and credits.

The page takes the version and the credits; `footer` is the credit line
that the Settings dialog shows on its Done row while About is open.
"""

from __future__ import annotations

import re

from PyQt6.QtWidgets import QLabel, QWidget

from library import data_versions
from settings_ui import LABEL_GAP, LINK_STYLE, add_section, muted, settings_page
from theme import ROOT


class AboutPage(QWidget):
    def __init__(
        self,
        version: str,
        author: str,
        author_url: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # Text keeps to the left; the photo (whole dialog) has the right.
        _, layout = settings_page(right_margin=330, page=self)
        title = QLabel(f"Prompta {version}")
        title.setObjectName("aboutTitle")
        layout.addWidget(title)
        layout.addSpacing(LABEL_GAP)
        self.how = muted(self.how_it_works())
        layout.addWidget(self.how)
        layout.addSpacing(12)  # paragraph breaks, not new sections
        layout.addWidget(
            muted(
                "For recurring tasks, Prompta turns your project rules and workflows into instructions, skills "
                "(SKILL.md), and subagent configurations. It validates the file formats before export so you can add "
                "them to your repository and use them with Claude Code, Codex, Cursor, or GitHub Copilot. You can also "
                "generate prompts from the terminal or via MCP."
            )
        )
        add_section(
            layout,
            "Your data",
            muted(
                "Everything stays on your Mac: history, settings, and the dictation model are stored locally, and API "
                "keys are kept in the macOS Keychain. Your requests go only to the model provider you choose. "
                "MIT licensed."
            ),
        )
        layout.addStretch(1)  # it fits the dialog: no scroll area, nothing to bounce
        self.author = QLabel(f'© 2026 <a href="{author_url}" {LINK_STYLE}>{author}</a>')
        self.author.setObjectName("muted")
        self.author.setOpenExternalLinks(True)
        self.author.setAccessibleName(f"Made by {author}")
        self.footer = self.author

    @staticmethod
    def versions() -> list[tuple[str, str]]:
        return data_versions(ROOT)

    def how_it_works(self) -> str:
        versions = dict(self.versions())
        count = (re.search(r"(\d+) entries", versions.get("Technique catalog", "")) or [None, "90"])[1]
        return (
            "Prompta is an open-source macOS app that turns rough requests into ready-to-use prompts. Describe what "
            "you want in your own words, type or dictate it, and attach any relevant files. Prompta writes a brief: "
            "your goal, the information the model should use, the output format, and any assumptions it had to make. "
            "It asks follow-up questions when details are missing. Then it picks one of "
            f"{count} prompting techniques, each traced to a research paper or official model documentation. The "
            "catalog is built on The Prompt Report (Schulhoff et al.) and guidance from Anthropic, OpenAI, Google, "
            "xAI and Nous Research. Prompta tailors the prompt to ChatGPT, Claude, Gemini, Grok, or an open-weight "
            "model and shows a simpler version for comparison."
        )
