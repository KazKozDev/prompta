"""Records docs/demo/demo.gif: a real run of the desktop app's Prompt tab, frame by frame.

    python3 docs/demo/record.py OUT_DIR [MODEL]
    sh build_gif.sh OUT_DIR/frames.txt docs/demo/demo.gif     (from the recording-readme-gifs skill)

The window renders offscreen (QWidget.grab): no cursor, no other windows, no screen-recording permission.
HOME is a throwaway folder, so no history, settings or Keychain keys reach the frame. The pipeline and the
model are real (Ollama at localhost:11434, MODEL defaults to deepseek-v4.1-flash:cloud); only the wait for
the model is shortened, by showing each progress frame for 0.3 s.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "demo-frames").resolve()
MODEL = sys.argv[2] if len(sys.argv) > 2 else "deepseek-v4.1-flash:cloud"
REQUEST = (
    "I paste a raw changelog from our repo and want release notes for users: "
    "what's new, what got fixed, no internal ticket numbers or jargon. short, markdown"
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["HOME"] = tempfile.mkdtemp(prefix="prompta-demo-home-")  # before app imports: paths derive from HOME
os.environ["PROMPTA_STATE_FILE"] = str(Path(os.environ["HOME"]) / "generator.json")
os.environ["PROMPTA_LOG_DIR"] = os.environ["HOME"]
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "desktop"))

from unittest.mock import patch  # noqa: E402

from PyQt6.QtCore import QSettings  # noqa: E402

QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, os.environ["HOME"])  # not the real prefs

import app as prompta  # noqa: E402
import keychain  # noqa: E402
from mcp_settings import prefs  # noqa: E402

W, H = 1160, 800
frames: list[tuple[str, int]] = []


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("f*.png"):
        old.unlink()
    qt = prompta.make_app(sys.argv[:1])
    prefs().setValue("generator/state", json.dumps({"provider": "ollama", "models": {"ollama": MODEL}}))
    with (
        patch.object(prompta, "load_local_providers", return_value={}),  # no personal providers or keys
        patch.object(keychain, "load", return_value=""),
        patch.object(keychain, "save"),
    ):
        window = prompta.PromptaWindow()
    window.resize(W, H)
    window.show()

    def snap(ms: int) -> None:
        """Save the window as the next frame, shown for `ms` milliseconds in the GIF."""
        path = OUT / f"f{len(frames):04d}.png"
        window.grab().save(str(path))
        frames.append((path.name, ms))

    def pump(seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            qt.processEvents()
            time.sleep(0.01)

    def wait_until(ready, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            pump(0.2)
            if ready():
                return True
        return False

    def model_ready() -> bool:
        return window.generator.current_model() == MODEL and bool(window.generator._model_lists.get("ollama"))

    if not wait_until(model_ready, 30):
        print(f"model {MODEL} is not in Ollama's list (is Ollama running?)", flush=True)
        return 1
    pump(1.0)
    snap(1000)  # 1 s on the empty window

    cursor = window.thoughts.textCursor()
    for i, ch in enumerate(REQUEST):
        cursor.insertText(ch)
        window.thoughts.setTextCursor(cursor)
        qt.processEvents()
        if i % 2 == 1 or i == len(REQUEST) - 1:
            snap(50)  # 2 characters per frame, 50 ms per frame
    snap(800)  # beat before Build

    started = time.monotonic()
    window.run_pipeline()  # what Build and ⌘↵ call

    def state() -> tuple:
        return (window.status.text(), window.generation_progress.value())

    pump(0.3)
    snap(500)
    last, last_snap = state(), time.monotonic()
    while window._running():
        pump(0.25)
        if state() != last or time.monotonic() - last_snap > 4:
            snap(300)
            last, last_snap = state(), time.monotonic()
        if time.monotonic() - started > 300:
            print("timeout: the run did not finish in 5 minutes", flush=True)
            return 1
    pump(1.0)
    real = time.monotonic() - started
    snap(5000)  # hold the result long enough to read

    (OUT / "frames.txt").write_text(
        "".join(f"file '{name}'\nduration {ms / 1000:.3f}\n" for name, ms in frames) + f"file '{frames[-1][0]}'\n"
    )
    shown = sum(ms for _, ms in frames) / 1000
    print(f"real run {real:.0f}s; GIF {shown:.1f}s in {len(frames)} frames -> {OUT / 'frames.txt'}", flush=True)
    window.close()
    return 0


if __name__ == "__main__":
    os._exit(main())  # skip Qt teardown order problems at interpreter exit
