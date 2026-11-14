"""Renders the app's main screens to PNG without showing a window — for eyeballing UI changes and for CI.

    python3 desktop/screenshots.py [OUT_DIR]     (default: /tmp/prompta-screens)

Runs offscreen in a throwaway HOME: no history, settings, Keychain, network or Node — the same pictures
on every machine with the same fonts. Writes main.png (a demo result with two variants) and one
settings-<tab>.png per Settings tab.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["HOME"] = tempfile.mkdtemp(prefix="prompta-home-")  # before app imports: paths derive from HOME
os.environ["PROMPTA_STATE_FILE"] = str(Path(os.environ["HOME"]) / "generator.json")
os.environ["PROMPTA_LOG_DIR"] = os.environ["HOME"]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from unittest.mock import patch  # noqa: E402

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QSettings  # noqa: E402

QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, os.environ["HOME"])  # not the real prefs

import app as prompta  # noqa: E402
import keychain  # noqa: E402
from generator_settings import GeneratorSettings  # noqa: E402


def settle(qt_app, rounds: int = 10) -> None:
    for _ in range(rounds):
        qt_app.processEvents()


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/prompta-screens")
    out.mkdir(parents=True, exist_ok=True)
    qt_app = prompta.make_app(sys.argv[:1])
    with (
        patch.object(prompta, "load_local_providers", return_value={}),
        patch.object(keychain, "load", return_value=""),
        patch.object(GeneratorSettings, "load_models"),
        patch.object(prompta.PromptaWindow, "load_techniques"),
    ):
        window = prompta.PromptaWindow()
    window.show()
    window.thoughts.setPlainText(
        "I want AI to review my meeting notes and extract decisions, tasks, and owners into a table"
    )
    window.result_column.render_result(prompta.demo_result())
    window.status.setText("Contextual prompting · ready")
    window.resize(1160, 1180)
    settle(qt_app)
    shots = [out / "main.png"]
    window.grab().save(str(shots[0]))

    dialog = window.settings_dialog
    tabs = dialog.tabs
    dialog.resize(820, 560)
    dialog.show()
    for index in range(tabs.count()):
        tabs.setCurrentIndex(index)
        settle(qt_app)
        name = re.sub(r"[^a-z0-9]+", "-", tabs.tabText(index).lower()).strip("-")
        shots.append(out / f"settings-{name}.png")
        dialog.grab().save(str(shots[-1]))
    dialog.close()
    window.close()
    sip.delete(window)  # now, with its children, not during interpreter exit after the QApplication is gone
    for path in shots:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
