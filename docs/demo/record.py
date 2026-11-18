"""The README demo: one real run of the desktop app's Prompt tab, captured once, then edited into a clip.

    python3 docs/demo/record.py capture OUT_DIR [MODEL]     # the real run: raw 2x window grabs + manifest.json
    python3 docs/demo/record.py render OUT_DIR              # the video frames: OUT_DIR/video/frames.txt
    python3 docs/demo/record.py render OUT_DIR --plain      # the GIF frames:   OUT_DIR/plain/frames.txt
    python3 docs/demo/record.py assemble OUT_DIR [CRF]      # intro.png + the video frames + outro.mp4 -> demo.mp4

    ffmpeg -f concat -safe 0 -i OUT_DIR/plain/frames.txt -vf "fps=15,split[a][b];[a]palettegen=stats_mode=diff[p];\\
[b][p]paletteuse=dither=none:diff_mode=rectangle" OUT_DIR/raw.gif
    gifsicle -O3 --lossy=65 OUT_DIR/raw.gif -o docs/demo/demo.gif

Capture: the window renders offscreen (QWidget.grab) in a throwaway HOME, so no history, settings or Keychain keys
reach the frame. The pipeline and the model are real (Ollama at localhost:11434, MODEL defaults to
deepseek-v4.1-flash:cloud). Nothing is grabbed while the model works: the clip cuts from Build to the result and says
how long the run really took.

Render: the shots are edited in the order of a short product demo, not in the order they were taken:
  the finished prompt -> the request being typed -> Build -> the result: techniques, zero-shot baseline,
  assumptions.
The video puts the window on the app's background (desktop/background.png, washed out) with rounded corners and no
shadow, runs subtitles along the bottom, and moves a slow camera (sine-eased, at most 1.4x, at least 2.8 s per move,
still in between). --plain keeps only the window and a camera that cuts instead of moving, for a GIF small enough for
GitHub. Everything around the window is drawn; the window itself is the real app, untouched.
Assemble: the video opens on docs/demo/intro.png (the name and what the app does) and ends with docs/demo/outro.mp4,
both 16:9 like the stage, each joined by a dissolve; no sound.
GitHub plays a video only from its own upload URL, so demo.mp4 is uploaded by hand through the README editor on
github.com; a new build means a new upload and a new URL in the README.
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
MODE = ARGS[0] if ARGS else ""
OUT = Path(ARGS[1] if len(ARGS) > 1 else "demo-frames").resolve()
MODEL = ARGS[2] if len(ARGS) > 2 else "deepseek-v4.1-flash:cloud"
PLAIN = "--plain" in sys.argv[1:]
REQUEST = "turn a raw changelog into release notes for users: what's new, what's fixed, no ticket numbers"
ROOT = Path(__file__).resolve().parents[2]

if MODE not in ("capture", "render", "assemble"):
    sys.exit(__doc__)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_SCALE_FACTOR"] = "2" if MODE == "capture" else "1"  # the window renders at 2x = S below
os.environ["HOME"] = tempfile.mkdtemp(prefix="prompta-demo-home-")  # before app imports: paths derive from HOME
os.environ["PROMPTA_STATE_FILE"] = str(Path(os.environ["HOME"]) / "generator.json")
os.environ["PROMPTA_LOG_DIR"] = os.environ["HOME"]
sys.path.insert(0, str(ROOT / "desktop"))

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSettings, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QLinearGradient, QPainterPath, QRadialGradient  # noqa: E402
from PyQt6.QtWidgets import QApplication, QTabWidget  # noqa: E402

QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, os.environ["HOME"])  # not the real prefs

W, H = 1160, 800  # the window, logical px
S = 2  # capture scale


# ── capture ─────────────────────────────────────────────────────────────────────────────────────────


def capture() -> int:
    from unittest.mock import patch  # noqa: PLC0415

    import app as prompta  # noqa: PLC0415
    import keychain  # noqa: PLC0415
    from mcp_settings import prefs  # noqa: PLC0415

    raw = OUT / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for old in raw.glob("*.png"):
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

    def pump(seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            qt.processEvents()
            time.sleep(0.01)

    def grab(name: str) -> str:
        pump(0.15)
        window.grab().save(str(raw / f"{name}.png"))
        return f"raw/{name}.png"

    def rect(*widgets) -> list[int]:
        r = QRect()
        for widget in widgets:
            r = r.united(QRect(widget.mapTo(window, QPoint(0, 0)), widget.size()))
        return [r.x(), r.y(), r.width(), r.height()]

    end = time.monotonic() + 30
    while not (window.generator.current_model() == MODEL and window.generator._model_lists.get("ollama")):
        pump(0.2)
        if time.monotonic() > end:
            print(f"model {MODEL} is not in Ollama's list (is Ollama running?)", flush=True)
            return 1
    window.variants.setValue(2)  # two prompts, built with different techniques
    pump(1.0)
    if window.grab().width() < W * S:
        print("warning: the window did not render at 2x: zoomed text will be soft", flush=True)

    shots: dict[str, object] = {"empty": grab("empty")}
    rects: dict[str, object] = {
        "input": rect(window.thoughts),
        "controls": rect(window.variants, window.run_button),
    }
    typing = []
    cursor = window.thoughts.textCursor()
    for i, ch in enumerate(REQUEST):
        cursor.insertText(ch)
        window.thoughts.setTextCursor(cursor)
        if i % 2 == 1 or i == len(REQUEST) - 1:
            typing.append(grab(f"type{len(typing):03d}"))
    shots["typing"] = typing
    window.run_button.setDown(True)
    shots["build"] = grab("build")
    window.run_button.setDown(False)

    started = time.monotonic()
    window.run_button.click()  # Build: the real pipeline; nothing is grabbed while it works
    pump(0.5)
    while window._running():
        pump(0.25)
        if time.monotonic() - started > 300:
            print("timeout: the run did not finish in 5 minutes", flush=True)
            return 1
    real = time.monotonic() - started
    pump(1.0)

    tabs = window.result_column.findChild(QTabWidget, "variantTabs")
    if tabs is None:
        grab("failed")
        print("no result tabs: the run failed, see raw/failed.png", flush=True)
        return 1
    names = [tabs.tabText(i) for i in range(tabs.count())]
    for index in (1, 0, 2):
        if index < tabs.count():
            tabs.setCurrentIndex(index)
            shots[f"tab{index}"] = grab(f"tab{index}")
    tabs.setCurrentIndex(1)
    pump(0.3)
    rects["tabs"] = rect(tabs)
    card = window.assumptions_card
    rects["assumptions"] = rect(card) if card is not None and card.isVisible() else None

    manifest = {
        "model": MODEL,
        "request": REQUEST,
        "real_run_s": round(real),
        "tabs": names,
        "shots": shots,
        "rects": rects,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"captured: run {real:.0f}s, tabs {names}, {len(typing)} typing shots -> {OUT / 'manifest.json'}", flush=True)
    window.close()
    return 0


# ── render ──────────────────────────────────────────────────────────────────────────────────────────

OW, OH = (W, H) if PLAIN else (1600, 900)  # stage and output frame, logical px
WX, WY = (OW - W) // 2, (OH - H) // 2  # the window on the stage
FPS = 15 if PLAIN else 30
RADIUS = 0 if PLAIN else 14
MAX_ZOOM = 1.4  # close enough to read, far enough that moves stay short and calm

Cam = tuple[float, float, float]  # centre x, centre y (stage px), zoom (1 = the whole stage)
FULL: Cam = (OW / 2, OH / 2, 1.0)


def smooth(t: float) -> float:
    """Sine ease in-out: starts and stops at rest, peak speed only 1.57x the average."""
    t = min(1.0, max(0.0, t))
    return 0.5 - 0.5 * math.cos(math.pi * t)


def crop(cam: Cam) -> QRectF:
    cx, cy, z = cam
    w, h = OW / z, OH / z
    return QRectF(min(max(cx - w / 2, 0), OW - w), min(max(cy - h / 2, 0), OH - h), w, h)


def focus(r: list[int] | None, zoom: float, pad: int = 28, top: int = 0) -> Cam:
    """A camera on a window rect (window px), no closer than `zoom`; `top` keeps only the rect's top part."""
    if not r:
        return FULL
    x, y, w, h = r
    if top:
        h = min(h, top)
    z = max(1.0, min(zoom, MAX_ZOOM, OW / (w + 2 * pad), OH / (h + 2 * pad)))
    return (WX + x + w / 2, WY + y + h / 2, z)


class Track:
    """Camera keyframes on clip time, stored as crop rects (x, y, width) that already fit the stage: a move between
    two of them never touches the stage edge, so it has no kinks. A move eases (sine) and is at rest at every key;
    a key with cut=True is reached by a dissolve instead, for framings too far apart to pan between calmly."""

    def __init__(self) -> None:
        self.keys: list[tuple[float, tuple[float, float, float], bool]] = []

    def key(self, t: float, cam: Cam, cut: bool = False) -> None:
        r = crop(cam)
        self.keys.append((t, (r.x(), r.y(), r.width()), cut))

    @staticmethod
    def rect(v: tuple[float, float, float]) -> QRectF:
        return QRectF(v[0], v[1], v[2], v[2] * OH / OW)

    def at(self, t: float) -> tuple[QRectF, QRectF | None, float]:
        """The framing at t; during a dissolve, the outgoing one, the incoming one and how far it is."""
        keys = self.keys
        if t <= keys[0][0]:
            return self.rect(keys[0][1]), None, 0.0
        for (t0, a, _), (t1, b, cut) in zip(keys, keys[1:]):
            if t <= t1:
                k = smooth((t - t0) / (t1 - t0)) if t1 > t0 else 1.0
                if PLAIN:  # the GIF cuts between framings: a moving camera changes every pixel and triples the file
                    k = float(k >= 0.5)
                if cut:
                    return self.rect(a), self.rect(b), k
                w = a[2] * (b[2] / a[2]) ** k  # zoom evenly; x and y follow linearly, so the rect stays on stage
                return self.rect((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, w)), None, 0.0
        return self.rect(keys[-1][1]), None, 0.0


class Layer:
    """A value that fades over time: ramps of (start, end, from, to), applied in order."""

    def __init__(self, value: float = 0.0) -> None:
        self.value0 = value
        self.ramps: list[tuple[float, float, float, float]] = []

    def ramp(self, start: float, end: float, a: float, b: float) -> None:
        self.ramps.append((start, end, a, b))

    def at(self, t: float) -> float:
        v = self.value0
        for start, end, a, b in self.ramps:
            if t >= end:
                v = b
            elif t >= start:
                v = a + (b - a) * smooth((t - start) / (end - start))
        return v


BLUR_FROM, BLUR_TO = 640, 980  # logical x where the background blur starts to fade and where it is gone


def backdrop() -> QImage:
    photo = QImage(str(ROOT / "desktop" / "background.png"))
    photo = photo.scaled(
        OW * S, OH * S, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
    )
    stage = photo.copy((photo.width() - OW * S) // 2, (photo.height() - OH * S) // 2, OW * S, OH * S)
    stage = stage.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    # The left of the photo, where the title text sits, goes soft; the blur fades out before the woman on the right.
    blur = stage
    for k in (6, 4):  # two down-and-up passes: a smooth blur without the blocks of a single big scale
        small = blur.scaled(
            blur.width() // k, blur.height() // k, transformMode=Qt.TransformationMode.SmoothTransformation
        )
        blur = small.scaled(stage.size(), transformMode=Qt.TransformationMode.SmoothTransformation)
    blur = blur.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    mask = QPainter(blur)
    mask.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    fade = QLinearGradient(QPointF(BLUR_FROM * S, 0), QPointF(BLUR_TO * S, 0))
    fade.setColorAt(0.0, QColor(0, 0, 0, 255))
    fade.setColorAt(1.0, QColor(0, 0, 0, 0))
    mask.fillRect(blur.rect(), fade)
    mask.end()
    painter = QPainter(stage)
    painter.drawImage(0, 0, blur)
    vignette = QRadialGradient(QPointF(OW * S / 2, OH * S / 2), OW * S * 0.75)
    vignette.setColorAt(0.55, QColor(30, 18, 0, 0))
    vignette.setColorAt(1.0, QColor(30, 18, 0, 120))
    painter.fillRect(stage.rect(), vignette)
    # Washed out, so the window is what the eye goes to: part grey, then a pale cream veil.
    gray = stage.convertToFormat(QImage.Format.Format_Grayscale8)
    painter.setOpacity(0.45)
    painter.drawImage(0, 0, gray)
    painter.setOpacity(1.0)
    painter.fillRect(stage.rect(), QColor(250, 243, 226, 105))
    painter.end()
    return stage


def font(px: int, weight: QFont.Weight, tracking: int = 100, family: str = "") -> QFont:
    f = QFont(family) if family else QFont()
    f.setPixelSize(px * S)
    f.setWeight(weight)
    f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, tracking)
    return f


def draw_caption(painter: QPainter, text: str, alpha: float) -> None:
    """A subtitle at the bottom saying what happens on screen, so the clip reads without sound. Drawn on the
    output frame."""
    if alpha <= 0 or not text:
        return
    painter.save()
    painter.setOpacity(alpha)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = QFont()
    f.setPixelSize(34)
    f.setWeight(QFont.Weight.DemiBold)
    painter.setFont(f)
    h = 72.0
    w = painter.fontMetrics().horizontalAdvance(text) + 64
    box = QRectF((OW - w) / 2, OH - 112 + 6 * (1 - alpha), w, h)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(28, 20, 4, 215))
    painter.drawRoundedRect(box, h / 2, h / 2)
    painter.setPen(QColor(255, 244, 214))
    painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()


def render() -> int:
    manifest = json.loads((OUT / "manifest.json").read_text())
    shots, rects, tabs = manifest["shots"], manifest["rects"], manifest["tabs"]
    out = OUT / ("plain" if PLAIN else "video")
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("f*.png"):
        old.unlink()
    qt = QApplication(sys.argv[:1])  # fonts need it; keep the reference or it is collected at once

    # ── the edit: what is on screen when ──
    timeline: list[tuple[float, str, float]] = []  # (from t, shot path, crossfade seconds), each until the next
    captions: list[tuple[float, float, str]] = []
    track = Track()
    win = Layer(1.0 if PLAIN else 0.0)  # window opacity
    rise = Layer(0.0 if PLAIN else 1.0)  # 1 = lowered and shrunk, for the entrance and the exit
    tech = list(tabs[1:3])
    on_tabs = focus(rects["tabs"], 1.3, top=440)
    move, fade = 2.8, 1.0  # every camera move and every dissolve between framings: slow, so nothing jumps

    def say(start: float, text: str) -> None:
        """Subtitles run back to back: each one holds until the next starts."""
        if captions:
            captions[-1] = (captions[-1][0], start, captions[-1][2])
        captions.append((start, math.inf, text))

    t = 0.0
    if not PLAIN:  # the window rises at once, under the intro picture's dissolve: no bare stage on screen
        win.ramp(0.0, 1.0, 0, 1)
        rise.ramp(0.0, 1.4, 1, 0)
    track.key(0.0, FULL)
    timeline.append((t, shots["tab1"], 0.0))  # first the finished prompt, whole, then a slow push onto it
    say(0.8, "The result: a ready prompt, built from one rough sentence")
    t = 2.6
    track.key(t, FULL)
    track.key(t + move, on_tabs)
    t += move + 1.6

    timeline.append((t, shots["empty"], fade))  # back to the start: the empty window, the request field
    on_input = focus(rects["input"], 1.35, top=170)
    track.key(t, on_tabs)
    track.key(t + fade, on_input, cut=True)
    say(t + 0.4, "Type what you need, in your own words")
    t += fade + 0.6
    typing = shots["typing"]
    for i, path in enumerate(typing):  # 2 characters per shot, a little slower than real typing
        timeline.append((t + i * 0.07, path, 0.0))
    t += len(typing) * 0.07 + 1.2  # and a rest on the full request
    track.key(t, on_input)

    on_build = focus(rects["controls"], 1.35)
    track.key(t + fade, on_build, cut=True)
    say(t + 0.4, "Pick how many variants, press Build")
    t += fade + 1.6  # the camera is still before the click
    track.key(t, on_build)
    timeline.append((t, shots["build"], 0.0))
    t += 0.7

    timeline.append((t, shots["tab1"], 0.5))  # the cut: no progress bar, the result arrives
    say(t + 0.1, f"{manifest['real_run_s']} seconds later the prompts are ready")
    t += 1.2
    track.key(t, on_build)
    t += move + 0.4  # one slow pan from the button to the result tabs
    track.key(t - 0.4, on_tabs)
    track.key(t, on_tabs)
    say(t - 0.6, f"Variant 1 is built with {tech[0]}" if tech else "Built with a matching technique")
    t += 2.6
    timeline.append((t, shots["tab0"], 0.4))  # the baseline it is compared against
    say(t + 0.1, "Zero-shot: the plain baseline to compare against")
    t += 2.8
    if len(tech) > 1 and "tab2" in shots:
        timeline.append((t, shots["tab2"], 0.4))
        say(t + 0.1, f"Variant 2 is built with {tech[1]}")
        t += 2.8
    timeline.append((t, shots["tab1"], 0.4))
    t += 0.5
    track.key(t, on_tabs)
    if rects.get("assumptions"):  # what it assumed: editable, then Build again
        on_card = focus(rects["assumptions"], 1.35, top=300)
        track.key(t + fade, on_card, cut=True)
        say(t + 0.4, "It shows what it assumed. Edit a line, build again")
        t += fade + 3.0
        track.key(t, on_card)
    track.key(t + move, FULL)
    say(t + 0.4, "For Claude, ChatGPT, Gemini, Grok and open models")
    t += move + (1.8 if PLAIN else 1.4)  # the video ends on the window; the outro dissolves in over it
    track.key(t, FULL)
    say(t - 0.6, "")  # the last subtitle is gone before the outro, which has its own text
    total = t

    # The camera's speed, checked before anything is drawn: output px per frame, and its change between frames.
    velocity: list[float] = []
    prev: QRectF | None = None
    for i in range(int(total * FPS) + 1):
        a, b, _ = track.at(i / FPS)
        if b is None and prev is not None:
            s = OW / a.width()
            velocity.append(max(abs(a.x() - prev.x()), abs(a.y() - prev.y()), abs(a.width() - prev.width())) * s)
        prev = a if b is None else None
    jerk = max((abs(y - x) for x, y in zip(velocity, velocity[1:])), default=0)
    fastest = [(round(i / FPS, 1), round(v, 1)) for i, v in sorted(enumerate(velocity), key=lambda x: -x[1])[:4]]
    print("camera: cuts only (GIF)") if PLAIN else print(
        f"camera: max {max(velocity):.1f} px/frame ({max(velocity) * FPS:.0f} px/s) at ~t={fastest}, "
        f"max change between frames {jerk:.2f} px/frame",
        flush=True,
    )
    if "--dry" in sys.argv:
        return 0

    # ── drawing ──
    stage_bg = backdrop() if not PLAIN else None
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(WX * S, WY * S, W * S, H * S), RADIUS * S, RADIUS * S)
    cache: dict[str, QImage] = {}

    def image(path: str) -> QImage:
        if path not in cache:
            if len(cache) > 6:
                cache.pop(next(iter(cache)))
            cache[path] = QImage(str(OUT / path))
        return cache[path]

    def window_at(now: float) -> QImage:
        current = max((i for i, (start, _, _) in enumerate(timeline) if start <= now), default=0)
        start, path, fade = timeline[current]
        img = image(path)
        if fade and current and now < start + fade:
            mixed = QImage(image(timeline[current - 1][1]))
            painter = QPainter(mixed)
            painter.setOpacity(smooth((now - start) / fade))
            painter.drawImage(0, 0, img)
            painter.end()
            return mixed
        return img

    frames: list[str] = []
    for i in range(int(total * FPS) + 1):
        now = i / FPS
        scene = QImage(stage_bg) if stage_bg is not None else QImage(OW * S, OH * S, QImage.Format.Format_RGB32)
        painter = QPainter(scene)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        alpha, lowered = win.at(now), rise.at(now)
        if alpha > 0:
            k = 1 - 0.06 * lowered
            cx, cy = (WX + W / 2) * S, (WY + H / 2) * S
            painter.translate(cx, cy + 40 * S * lowered)
            painter.scale(k, k)
            painter.translate(-cx, -cy)
            painter.setOpacity(alpha)
            painter.setClipPath(clip)
            painter.drawImage(QRectF(WX * S, WY * S, W * S, H * S), window_at(now))
            painter.resetTransform()
            painter.setClipping(False)
            painter.setOpacity(1.0)
        painter.end()

        frame = QImage(OW, OH, QImage.Format.Format_RGB32)
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        outgoing, incoming, mix = track.at(now)
        for src, opacity in ((outgoing, 1.0), (incoming, mix)):
            if src is not None:
                painter.setOpacity(opacity)
                painter.drawImage(
                    QRectF(0, 0, OW, OH), scene, QRectF(src.x() * S, src.y() * S, src.width() * S, src.height() * S)
                )
        painter.setOpacity(1.0)
        if not PLAIN:
            for start, end, text in captions:
                if start <= now <= end:
                    draw_caption(painter, text, min(smooth((now - start) / 0.4), smooth((end - now) / 0.4)))
        painter.end()
        name = f"f{i:05d}.png"
        frame.save(str(out / name))
        frames.append(name)

    (out / "frames.txt").write_text(
        "".join(f"file '{name}'\nduration {1 / FPS:.4f}\n" for name in frames) + f"file '{frames[-1]}'\n"
    )
    print(f"{'plain' if PLAIN else 'video'}: {total:.1f}s, {len(frames)} frames at {FPS} fps -> {out / 'frames.txt'}")
    del qt
    return 0


INTRO_S, INTRO_FADE, OUTRO_FADE = 2.5, 0.6, 0.8


def rgb_stats(src: list[str]) -> list[tuple[float, float]]:
    """Mean and standard deviation of each RGB channel of one frame, from a 160x90 thumbnail."""
    import subprocess

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", *src, "-frames:v", "1", "-vf", "scale=160:90"]
        + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True,
        capture_output=True,
    ).stdout
    out = []
    for ch in range(3):
        values = raw[ch::3]
        mean = sum(values) / len(values)
        out.append((mean, (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5))
    return out


def assemble() -> int:
    """intro.png, then the rendered video frames, then outro.mp4, dissolving into each other -> docs/demo/demo.mp4."""
    import subprocess

    here = Path(__file__).resolve().parent
    frames = OUT / "video" / "frames.txt"
    n = frames.read_text().count("duration ")
    demo_s = n / 30
    fit = f"scale={OW}:{OH}:force_original_aspect_ratio=increase,crop={OW}:{OH},setsar=1,fps=30,format=yuv420p"
    # The outro ends on the intro's picture, re-shot warmer: grade the intro to the outro's last frame, so the clip
    # starts and ends in the same colour. Per channel, match mean and spread.
    ref = rgb_stats(["-sseof", "-0.1", "-i", str(here / "outro.mp4")])
    src = rgb_stats(["-i", str(here / "intro.png")])
    lut = []
    for ch, (ms, ss), (mr, sr) in zip("rgb", src, ref):
        a = sr / ss
        lut.append(f"{ch}='clip(val*{a:.4f}+{mr - a * ms:.2f},0,255)'")
    grade = "lutrgb=" + ":".join(lut)
    outro_at = INTRO_S - INTRO_FADE + demo_s - OUTRO_FADE
    graph = (
        f"[0:v]format=rgb24,{grade},{fit}[i];[1:v]{fit}[d];[2:v]{fit}[o];"
        f"[i][d]xfade=transition=fade:duration={INTRO_FADE}:offset={INTRO_S - INTRO_FADE:.3f}[id];"
        f"[id][o]xfade=transition=fade:duration={OUTRO_FADE}:offset={outro_at:.3f}[v]"
    )
    crf = ARGS[2] if len(ARGS) > 2 else "27"
    # fmt: off
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-loop", "1", "-framerate", "30", "-t", str(INTRO_S), "-i", str(here / "intro.png"),
        "-f", "concat", "-safe", "0", "-i", str(frames),
        "-i", str(here / "outro.mp4"),
        "-filter_complex", graph, "-map", "[v]", "-an",
        "-c:v", "libx264", "-preset", "slow", "-crf", crf, "-tune", "animation", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(here / "demo.mp4"),
    ]
    # fmt: on
    subprocess.run(cmd, check=True)
    print(f"demo.mp4: intro {INTRO_S}s + video {demo_s:.1f}s + outro, crf {crf}", flush=True)
    return 0


if __name__ == "__main__":
    modes = {"capture": capture, "render": render, "assemble": assemble}
    os._exit(modes.get(MODE, render)())  # skip Qt teardown order problems at exit
