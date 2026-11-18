"""Records docs/demo/demo.gif: a real run of the desktop app's Prompt tab, frame by frame.

    python3 docs/demo/record.py OUT_DIR [MODEL]
    ffmpeg -f concat -safe 0 -i OUT_DIR/frames.txt -vf "fps=15,split[a][b];[a]palettegen=stats_mode=diff[p];\
[b][p]paletteuse=dither=none:diff_mode=rectangle" OUT_DIR/raw.gif
    gifsicle -O3 --lossy=65 OUT_DIR/raw.gif -o docs/demo/demo.gif

No dithering and 15 fps: every camera move redraws the photo background, and dither noise there doubles the size.

The window renders offscreen (QWidget.grab): no cursor, no other windows, no screen-recording permission.
HOME is a throwaway folder, so no history, settings or Keychain keys reach the frame. The pipeline and the
model are real (Ollama at localhost:11434, MODEL defaults to deepseek-v4.1-flash:cloud); only the wait for
the model is shortened, by showing each progress frame for 0.3 s.

Scenario: type the request, pick 2 variants, Build; then flip through the result tabs (zero-shot baseline,
then each technique's prompt) and end on what the prompt adds over zero-shot.

Camera: the window renders at 2x; each GIF frame is a crop of it scaled to 1160x800, so zooming in (up to 2x)
shows native pixels. The camera eases between the request field, the controls, the result tabs and the whole
window. It only reframes real frames: what the app shows is untouched.
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
REQUEST = "turn a raw changelog into release notes for users: what's new, what's fixed, no ticket numbers"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_SCALE_FACTOR"] = "2"  # = SCALE below
os.environ["HOME"] = tempfile.mkdtemp(prefix="prompta-demo-home-")  # before app imports: paths derive from HOME
os.environ["PROMPTA_STATE_FILE"] = str(Path(os.environ["HOME"]) / "generator.json")
os.environ["PROMPTA_LOG_DIR"] = os.environ["HOME"]
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "desktop"))

from unittest.mock import patch  # noqa: E402

from PyQt6.QtCore import QPoint, QRect, QRectF, QSettings  # noqa: E402
from PyQt6.QtGui import QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QLabel, QTabWidget  # noqa: E402

QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, os.environ["HOME"])  # not the real prefs

import app as prompta  # noqa: E402
import keychain  # noqa: E402
from mcp_settings import prefs  # noqa: E402

W, H = 1160, 800  # the window, in logical pixels; also the GIF size
SCALE = 2  # the window renders at 2x, so a 2x zoom crops native pixels and the text stays sharp
STEP = 50  # ms per frame while the camera moves (20 fps, as build_gif.sh samples)
frames: list[tuple[str, int]] = []

Cam = tuple[float, float, float]  # centre x, centre y (logical px), zoom (1 = whole window)
FULL: Cam = (W / 2, H / 2, 1.0)


def ease(t: float) -> float:
    return 4 * t**3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def crop(cam: Cam) -> QRectF:
    """The part of the window the camera sees, in logical px, kept inside the window."""
    cx, cy, z = cam
    w, h = W / z, H / z
    return QRectF(min(max(cx - w / 2, 0), W - w), min(max(cy - h / 2, 0), H - h), w, h)


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

    shot = QImage()
    cam: Cam = FULL

    def emit(ms: int, at: Cam) -> None:
        """Write the last grab, as the camera at `at` sees it, as the next GIF frame shown for `ms` ms."""
        src = crop(at)
        k = shot.width() / W
        frame = QImage(W, H, QImage.Format.Format_RGB32)
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QRectF(0, 0, W, H), shot, QRectF(src.x() * k, src.y() * k, src.width() * k, src.height() * k))
        painter.end()
        path = OUT / f"f{len(frames):04d}.png"
        frame.save(str(path))
        frames.append((path.name, ms))

    def snap(ms: int) -> None:
        """Grab the window as it is now and show it for `ms` ms through the current camera."""
        nonlocal shot
        shot = window.grab().toImage()
        emit(ms, cam)

    def glide(to: Cam, ms: int) -> None:
        """Move the camera smoothly over the last grab: centre linearly, zoom on a log scale, eased in and out."""
        nonlocal cam
        (x0, y0, z0), (x1, y1, z1) = cam, to
        steps = max(2, round(ms / STEP))
        for i in range(1, steps + 1):
            t = ease(i / steps)
            emit(STEP, (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, z0 * (z1 / z0) ** t))
        cam = to

    def area(*widgets, height: int = 0) -> QRect:
        """The widgets' rectangle in window coordinates; `height` keeps only its top part."""
        rect = QRect()
        for widget in widgets:
            rect = rect.united(QRect(widget.mapTo(window, QPoint(0, 0)), widget.size()))
        if height:
            rect.setHeight(min(rect.height(), height))
        return rect

    def focus(rect: QRect, zoom: float, pad: int = 24) -> Cam:
        """A camera on `rect` with some room around it, no closer than `zoom`."""
        z = max(1.0, min(zoom, W / (rect.width() + 2 * pad), H / (rect.height() + 2 * pad)))
        return (rect.center().x(), rect.center().y(), z)

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
    snap(900)  # the whole window first
    if shot.width() < W * SCALE:
        print(f"warning: the window rendered at {shot.width()}px, not {W * SCALE}: zoomed text will be soft")

    glide(focus(area(window.thoughts, height=150), 2.0), 700)  # in on the request field
    cursor = window.thoughts.textCursor()
    for i, ch in enumerate(REQUEST):
        cursor.insertText(ch)
        window.thoughts.setTextCursor(cursor)
        qt.processEvents()
        if i % 2 == 1 or i == len(REQUEST) - 1:
            snap(50)  # 2 characters per frame, 50 ms per frame
    snap(400)

    def press(button) -> None:
        """Show the button held down for a moment (there is no cursor offscreen), then click it for real."""
        button.setDown(True)
        qt.processEvents()
        snap(250)
        button.setDown(False)
        button.click()
        pump(0.2)

    glide(focus(area(window.variants, window.run_button, window.status), 2.0), 600)  # down to the controls
    press(window.variants.buttons.button(2))  # two prompts, built with different techniques
    snap(400)
    started = time.monotonic()
    press(window.run_button)  # Build: calls run_pipeline

    def state() -> tuple:
        return (window.status.text(), window.generation_progress.value())

    pump(0.3)
    snap(500)
    last, last_snap = state(), time.monotonic()
    while window._running():  # the status line under Build, close up
        pump(0.25)
        if state() != last or time.monotonic() - last_snap > 4:
            snap(300)
            last, last_snap = state(), time.monotonic()
        if time.monotonic() - started > 300:
            print("timeout: the run did not finish in 5 minutes", flush=True)
            return 1
    pump(1.0)
    real = time.monotonic() - started
    snap(500)
    glide(FULL, 900)  # out to the whole result
    snap(1400)

    tabs = window.result_column.findChild(QTabWidget, "variantTabs")
    if tabs is None:
        print("no result tabs: the run failed, see the window status", flush=True)
        window.grab().save(str(OUT / "failed.png"))
        return 1
    glide(focus(area(tabs, height=360), 1.6), 700)  # in on the prompt tabs
    snap(1600)
    for index, ms in ((0, 1800), (2, 1600), (1, 900)):  # zero-shot baseline, the second technique, back
        tabs.setCurrentIndex(index)
        pump(0.2)
        snap(ms)

    heading = next(
        (
            label
            for label in window.result_column.findChildren(QLabel)
            if label.isVisible() and "adds over zero-shot" in label.text().lower()
        ),
        None,
    )
    if heading is not None and area(heading).bottom() + 90 < H:  # what the prompt adds over the baseline
        rect = area(heading).adjusted(0, -8, 0, 90)
        rect.setWidth(area(tabs).width())
    else:  # a long prompt pushes that block below the window: show the end of the prompt instead
        rect = area(tabs).intersected(QRect(0, 0, W, H))
        rect.setTop(max(rect.top(), rect.bottom() - 360))
    glide(focus(rect, 1.6), 700)
    snap(1800)

    glide(FULL, 900)
    snap(2200)

    (OUT / "frames.txt").write_text(
        "".join(f"file '{name}'\nduration {ms / 1000:.3f}\n" for name, ms in frames) + f"file '{frames[-1][0]}'\n"
    )
    shown = sum(ms for _, ms in frames) / 1000
    print(f"real run {real:.0f}s; GIF {shown:.1f}s in {len(frames)} frames -> {OUT / 'frames.txt'}", flush=True)
    window.close()
    return 0


if __name__ == "__main__":
    os._exit(main())  # skip Qt teardown order problems at interpreter exit
