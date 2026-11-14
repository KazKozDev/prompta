"""Local Whisper dictation: where the model lives, how the worker starts, and Settings → Dictation.

The model is not part of the app (it alone is ~490 MB): Settings → Dictation downloads it once from Hugging
Face into Application Support, pinned to one revision and checked by size, so a cut-off download never counts
as installed. The worker runs as the app's own binary with --voice-worker in the standalone build, and with
.venv-whisper from the sources; a model in .whisper-models/small (the old setup step) still works there.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import IO

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from settings_ui import add_section, body, muted, settings_page, text_link
from theme import FROZEN, ROOT

REPO = "Systran/faster-whisper-small"
REVISION = "536b0662742c02347bc0e980a01041f333bce120"
FILES = {"config.json": 2370, "model.bin": 483546902, "tokenizer.json": 2203239, "vocabulary.txt": 459861}
TOTAL = sum(FILES.values())
LEGACY_MODEL = ROOT / ".whisper-models" / "small"


def megabytes(size: int) -> str:
    return f"{size / 1_000_000:.0f} MB"


def models_home() -> Path:
    override = os.environ.get("PROMPTA_MODELS_DIR")  # tests keep away from the real model
    return Path(override) if override else Path.home() / "Library" / "Application Support" / "Prompta" / "models"


def model_dir() -> Path:
    return models_home() / "whisper-small"


def is_complete(folder: Path) -> bool:
    """Every file of the pinned revision, each at its exact size."""
    try:
        return all((folder / name).stat().st_size == size for name, size in FILES.items())
    except OSError:
        return False


def installed_model() -> Path | None:
    if is_complete(model_dir()):
        return model_dir()
    if not FROZEN and all((LEGACY_MODEL / name).is_file() for name in FILES):
        return LEGACY_MODEL
    return None


def runtime_bundled() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in ("faster_whisper", "sounddevice"))


def worker_command() -> tuple[str, list[str]] | None:
    """The program and arguments that run voice_input.py, or None when Whisper itself is missing."""
    if FROZEN:
        # The app's own binary: macOS grants it the app's microphone access, no helper needed.
        return (sys.executable, ["--voice-worker"]) if runtime_bundled() else None
    interpreter = ROOT / ".venv-whisper/bin/python"
    if not interpreter.exists():
        return None
    script = str(ROOT / "desktop/voice_input.py")
    # Through prompta-mic when it is built: it carries the microphone usage text the system Python lacks,
    # so macOS asks for access instead of silently recording silence.
    helper = ROOT / "release/Prompta.app/Contents/MacOS/prompta-mic"
    if helper.exists():
        return str(helper), [str(interpreter), script]
    return str(interpreter), [script]


class ModelDownload(QObject):
    """Downloads the pinned files into a .part folder and renames it into place only when all are complete."""

    progress = pyqtSignal(int)  # bytes so far, out of TOTAL
    finished = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)  # the system trust store, unlike the bundled Python's OpenSSL
        self.reply: QNetworkReply | None = None
        self.handle: IO[bytes] | None = None
        self.queue: list[str] = []
        self.done_bytes = 0
        self.partial = models_home() / "whisper-small.part"

    @property
    def running(self) -> bool:
        return self.reply is not None

    def start(self) -> None:
        if self.running:
            return
        self.partial = models_home() / "whisper-small.part"
        shutil.rmtree(self.partial, ignore_errors=True)
        try:
            self.partial.mkdir(parents=True)
        except OSError as exc:
            self.failed.emit(f"Could not create {self.partial}: {exc.strerror}")
            return
        self.queue, self.done_bytes = list(FILES), 0
        self.progress.emit(0)
        self._next()

    def cancel(self) -> None:
        self._stop()
        shutil.rmtree(self.partial, ignore_errors=True)

    def _stop(self) -> None:
        reply, self.reply = self.reply, None  # cleared first: abort() emits finished at once
        if reply is not None:
            reply.abort()
            reply.deleteLater()
        if self.handle is not None:
            self.handle.close()
            self.handle = None

    def _fail(self, message: str) -> None:
        self.cancel()
        self.failed.emit(message)

    def _next(self) -> None:
        if not self.queue:
            self._install()
            return
        name = self.queue[0]
        request = QNetworkRequest(QUrl(f"https://huggingface.co/{REPO}/resolve/{REVISION}/{name}"))
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,  # model.bin is served from a CDN
        )
        try:
            self.handle = open(self.partial / name, "wb")
        except OSError as exc:
            self._fail(f"Could not write {name}: {exc.strerror}")
            return
        reply = self.network.get(request)
        assert reply is not None  # get() always returns a reply; the stubs allow None
        self.reply = reply
        reply.readyRead.connect(lambda: self._read(reply))
        reply.downloadProgress.connect(lambda received, _total: self._progress(reply, received))
        reply.finished.connect(lambda: self._file_finished(reply))

    def _read(self, reply: QNetworkReply) -> None:
        if reply is not self.reply or self.handle is None:
            return
        try:
            self.handle.write(bytes(reply.readAll()))  # type: ignore[call-overload]  # QByteArray
        except OSError as exc:
            self._fail(f"Could not save the model: {exc.strerror}")

    def _progress(self, reply: QNetworkReply, received: int) -> None:
        if reply is self.reply and self.queue:
            self.progress.emit(self.done_bytes + min(received, FILES[self.queue[0]]))

    def _file_finished(self, reply: QNetworkReply) -> None:
        if reply is not self.reply:
            return  # cancelled
        self._read(reply)
        if reply is not self.reply or self.handle is None:
            return  # the last write failed
        self.handle.close()
        self.handle = None
        self.reply = None
        reply.deleteLater()
        name = self.queue.pop(0)
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._fail(f"Download failed: {reply.errorString()}")
        elif status != 200 or (self.partial / name).stat().st_size != FILES[name]:
            self._fail(f"Download failed: Hugging Face sent an unexpected {name} (HTTP {status}). Try again.")
        else:
            self.done_bytes += FILES[name]
            self.progress.emit(self.done_bytes)
            self._next()

    def _install(self) -> None:
        target = model_dir()
        try:
            shutil.rmtree(target, ignore_errors=True)
            self.partial.rename(target)
        except OSError as exc:
            self._fail(f"Could not install the model: {exc.strerror}")
            return
        self.finished.emit()


def remove_model() -> None:
    shutil.rmtree(model_dir(), ignore_errors=True)


class DictationPage(QWidget):
    """Settings → Dictation: whether the model is here, and Download (with progress and Cancel) or Remove."""

    def __init__(self, is_dictating: Callable[[], bool], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.is_dictating = is_dictating
        self.error = ""
        self.download = ModelDownload(self)
        self.download.progress.connect(self._progress)
        self.download.finished.connect(self.refresh)
        self.download.failed.connect(self._failed)
        _, layout = settings_page(
            "Dictate into Thoughts with the microphone. Whisper runs on this Mac: "
            "audio stays in memory and is never uploaded.",
            page=self,
        )
        self.status = body()
        self.download_button = text_link(f"Download model ({megabytes(TOTAL)})")
        self.download_button.clicked.connect(self._download)
        self.cancel_button = text_link("Cancel download")
        self.cancel_button.clicked.connect(self._cancel)
        self.remove_button = text_link("Remove model", danger=True)
        self.remove_button.clicked.connect(self._remove)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(18)
        for button in (self.download_button, self.cancel_button, self.remove_button):
            actions.addWidget(button)
        actions.addStretch(1)
        self.hint = muted()
        add_section(layout, "Whisper model", self.status, actions, hint=self.hint)
        layout.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        downloading = self.download.running
        model = None if downloading else installed_model()
        if downloading:
            self._progress(self.download.done_bytes)
        elif model is not None:
            self.status.setText("Whisper small · ready")
        else:
            self.status.setText("Not downloaded")
        self.download_button.setVisible(not downloading and model is None)
        self.cancel_button.setVisible(downloading)
        self.remove_button.setVisible(model == model_dir())  # the repository's own copy is not ours to delete
        if self.error:
            hint = self.error
        elif worker_command() is None:
            hint = (
                "This build has no Whisper runtime, so dictation is not available."
                if FROZEN
                else "Whisper itself is not installed: see “Local Whisper dictation” in desktop/README.md."
            )
        elif model == LEGACY_MODEL:
            hint = "Using the model in .whisper-models/small from the repository."
        else:
            hint = f"Downloaded once from Hugging Face ({REPO}) into ~/Library/Application Support/Prompta/models."
        self.hint.setText(hint)

    def _download(self) -> None:
        self.error = ""
        self.download.start()
        self.refresh()

    def _cancel(self) -> None:
        self.download.cancel()
        self.refresh()

    def _remove(self) -> None:
        if self.is_dictating():
            self.error = "Stop dictation first."
        else:
            self.error = ""
            remove_model()
        self.refresh()

    def _progress(self, received: int) -> None:
        self.status.setText(f"Downloading… {received * 100 // TOTAL} % of {megabytes(TOTAL)}")

    def _failed(self, message: str) -> None:
        self.error = message
        self.refresh()
