"""Prompta look and target constants: loads app.qss (the one stylesheet), chat URLs, prompt targets."""

from __future__ import annotations

import sys
from pathlib import Path

# The repository in development; inside the standalone app (build_standalone.sh) the same tree ships as
# Contents/Resources/prompta, next to PyInstaller's own files.
ROOT = Path(sys._MEIPASS) / "prompta" if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
FROZEN = getattr(sys, "frozen", False)

COMPATIBLE = "openai_compatible"  # a second OpenAI-API provider: its own server URL and Keychain key

PROMPT_TARGETS = {
    "claude": ("Claude", ("platform.claude.com",)),
    "chatgpt": ("ChatGPT", ("developers.openai.com", "platform.openai.com", "learn.chatgpt.com")),
    "gemini": ("Gemini", ("ai.google.dev", "aistudio.google.com", "docs.cloud.google.com", "cloud.google.com")),
    "grok": ("Grok", ("docs.x.ai",)),
    "hermes": ("Hermes", ("hermes-agent.nousresearch.com", "github.com/NousResearch/hermes-agent")),
    "openModel": ("Open-weight model", ("huggingface.co",)),
}


def is_official_source(url: str, target: str) -> bool:
    """HTTPS link to a target's official host; a host/path entry admits only that path (one repository on github.com)."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or target not in PROMPT_TARGETS:
        return False
    for entry in PROMPT_TARGETS[target][1]:
        host, _, path = entry.partition("/")
        if parsed.hostname == host and (not path or parsed.path.startswith(f"/{path}/")):
            return True
    return False


CHAT_URLS = {
    "chatgpt": "https://chatgpt.com/",
    "claude": "https://claude.ai/new",
    "gemini": "https://gemini.google.com/app",
    "grok": "https://grok.com/",
}


QSS = (ROOT / "desktop" / "app.qss").read_text(encoding="utf-8").replace("@desktop/", (ROOT / "desktop").as_posix() + "/")


DARK_SCROLL_QSS = """
QScrollBar:vertical, QScrollBar:horizontal { background: #3e3e3e; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #606060; }
QScrollBar::handle:hover { background: #797979; }
QScrollBar::handle:pressed { background: #929292; }
"""
