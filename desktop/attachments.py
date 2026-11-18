"""Project files attached next to the request: every mode reads them as reference (pipeline/context.ts).

The files are read here, as text; a dropped folder brings its text files, without what git ignores and without
files that usually hold secrets. The bridge redacts secrets; files past the budget reach the model as a digest
(pipeline/digest.ts): the file tree, small files whole, outlines of long ones.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from theme import ROOT

MAX_FILES = 200  # pipeline/context.ts MAX_FILES
MAX_FILE_CHARS = 8_000  # pipeline/context.ts MAX_FILE_CHARS: a longer file makes the model read a digest
MAX_FILES_CHARS = 24_000  # pipeline/context.ts MAX_FILES_CHARS: past it the model reads a digest
MAX_FILE_BYTES = 1_000_000  # bridge.ts MAX_FILE_INPUT
MAX_TOTAL_CHARS = 5_000_000  # pipeline/context.ts MAX_FILES_INPUT
SHOWN_ROWS = 6  # more files than this collapse into one "and N more" row
# How a file reached the model in the last run (the bridge's filesUsed), as the file's row says it.
USE_NOTES = {"whole": "read whole", "outline": "outline", "tree": "only in the file tree"}

# Not taken from a dropped folder: dependencies, build output, caches, lock files, and files that hold secrets.
# A file picked by hand is the user's choice and is attached (the bridge still redacts what it recognises).
# fmt: off
SKIP_DIRS = {
    "node_modules", "dist", "build", "out", "target", "coverage", "venv", "__pycache__",
    "vendor", "Pods", "DerivedData",
}
LOCK_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "uv.lock",
    "Gemfile.lock", "composer.lock", "Pipfile.lock", "go.sum",
}
# Never text: skipped by name, so a folder of images or builds is not read file by file on the UI thread.
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".icns", ".bmp", ".tiff", ".heic", ".psd",
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".mp4", ".mov", ".avi", ".mkv", ".webm",
    ".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".tar", ".dmg", ".pkg", ".iso",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".so", ".dylib", ".dll", ".exe", ".o", ".a", ".class", ".jar", ".pyc", ".wasm", ".bin",
    ".sqlite", ".sqlite3", ".db", ".npy", ".npz", ".pt", ".pth", ".onnx", ".safetensors", ".gguf", ".parquet",
}
# fmt: on
MAX_CANDIDATES = 5_000  # a folder walk stops here: a home folder dropped by mistake must not hang the window
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore", ".jks", ".crt", ".der"}
SAFE_ENV = {".env.example", ".env.sample", ".env.template", ".env.dist"}
MAX_EMBED_CHARS = 200_000  # pipeline/context.ts MAX_EMBED_CHARS: Prompt mode appends this much to the prompt


def read_text_file(path: Path) -> str | None:
    """The file as text, or None for a binary, unreadable or too large file."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        with path.open("rb") as file:
            head = file.read(8192)
            if b"\0" in head:
                return None  # images, archives, compiled files: known from the first block
            data = head + file.read()
    except OSError:
        return None
    return data.decode("utf-8", errors="replace")


def may_hold_secrets(path: Path) -> bool:
    name = path.name.lower()
    if name.startswith(".env"):
        return name not in SAFE_ENV
    return (
        path.suffix.lower() in SECRET_SUFFIXES
        or name.startswith(("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"))
        or name in {"credentials", "credentials.json", ".netrc", ".npmrc", ".pypirc"}
    )


def _git_files(folder: Path) -> list[Path] | None:
    """The folder's files git would commit (tracked and new, not ignored), or None outside a repository."""
    try:
        done = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=folder,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return [folder / name for name in done.stdout.decode("utf-8", errors="replace").split("\0") if name]


def _walked_files(folder: Path) -> list[Path]:
    found: list[Path] = []
    for top, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and (not d.startswith(".") or d == ".github"))
        found.extend(Path(top) / name for name in sorted(names))
        if len(found) >= MAX_CANDIDATES:
            break
    return found[:MAX_CANDIDATES]


def folder_files(folder: Path) -> tuple[list[Path], int, int]:
    """The folder's candidate files, how many were left out as possible secrets, and how many as binaries by name."""
    listed = _git_files(folder)
    paths = listed[:MAX_CANDIDATES] if listed is not None else _walked_files(folder)
    kept: list[Path] = []
    secrets = binaries = 0
    # Shallow first: past MAX_FILES the root README and manifests are kept, not the first files of a deep folder.
    for path in sorted(paths, key=lambda p: (len(p.relative_to(folder).parts), str(p))):
        parts = path.relative_to(folder).parts
        if any(part in SKIP_DIRS for part in parts[:-1]) or path.name in LOCK_FILES or not path.is_file():
            continue
        if may_hold_secrets(path):
            secrets += 1
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            binaries += 1
            continue
        kept.append(path)
    return kept, secrets, binaries


def relative_names(paths: list[Path]) -> list[str]:
    """Paths from the files' common folder (src/app.py, not app.py), so the model sees the real layout."""
    if not paths:
        return []
    try:
        base = Path(os.path.commonpath([p.parent for p in paths]))
    except ValueError:  # different drives
        return [p.name for p in paths]
    return [p.relative_to(base).as_posix() for p in paths]


class Attachments(QWidget):
    """A link that picks files, then one row per file: its path, a note when it is cut, and a remove cross."""

    changed = pyqtSignal()
    notice = pyqtSignal(str)  # a skipped file or the limit, for the status line

    def __init__(self) -> None:
        super().__init__()
        self._paths: list[Path] = []
        self._texts: dict[Path, str] = {}
        self._material = True  # Prompt mode, the default: the prompt carries each file whole
        self._uses: dict[str, str] | None = None  # the last run's filesUsed, until the files or the request change
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)  # the paperclip in the request field opens pick()
        self.rows = QVBoxLayout()
        self.rows.setSpacing(3)
        box.addLayout(self.rows)
        self.hide()  # until a file is attached

    def pick(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, "Attach project files")
        self.add_paths([Path(n) for n in names])

    def add_paths(self, paths: list[Path]) -> None:
        skipped: list[str] = []  # files the user named: listed by name
        folder_skipped = 0  # images and other binaries are expected in a folder: counted only
        secrets = 0
        candidates: list[tuple[Path, bool]] = []
        for path in paths:
            if path.is_dir():
                found, hidden, binaries = folder_files(path.resolve())
                secrets += hidden
                folder_skipped += binaries
                candidates.extend((p, True) for p in found)
            else:
                candidates.append((path, False))
        total = sum(len(text) for text in self._texts.values())
        self._uses = None
        limit = ""
        for path, from_folder in candidates:
            path = path.resolve()
            if path in self._texts or not path.is_file():
                continue
            if len(self._paths) >= MAX_FILES:
                limit = f"At most {MAX_FILES} files"
                break
            text = read_text_file(path)
            if text is None:
                if from_folder:
                    folder_skipped += 1
                else:
                    skipped.append(path.name)
                continue
            if total + len(text) > MAX_TOTAL_CHARS:
                limit = f"At most {MAX_TOTAL_CHARS // 1_000_000} MB of text"
                break
            total += len(text)
            self._paths.append(path)
            self._texts[path] = text
        notes = [limit] if limit else []
        if skipped:
            notes.append(f"Not a text file or over 1 MB, skipped: {', '.join(skipped)}")
        if folder_skipped:
            notes.append(f"{folder_skipped} binary or large files skipped")
        if secrets:
            notes.append(f"{secrets} files that may hold secrets (.env, keys) left out")
        if notes:
            self.notice.emit(" · ".join(notes))
        self._rebuild()

    def remove(self, path: Path) -> None:
        if path in self._texts:
            self._paths.remove(path)
            del self._texts[path]
            self._uses = None
            self._rebuild()

    def set_material(self, material: bool) -> None:
        """Prompt mode appends the files to the prompt in full; the file modes read the start of each."""
        if material != self._material:
            self._material = material
            self._rebuild()

    def clear(self) -> None:
        self._paths.clear()
        self._texts.clear()
        self._uses = None
        self._rebuild()

    def set_uses(self, uses: object) -> None:
        """The bridge's filesUsed after a run: each row says whether the model read the file whole, its outline,
        or only its line in the file tree. Ignored unless it names exactly the attached files."""
        names = relative_names(self._paths)
        if isinstance(uses, dict) and set(uses) == set(names) and all(value in USE_NOTES for value in uses.values()):
            self._uses = dict(uses)
        else:
            self._uses = None
        self._rebuild()

    def forget_uses(self) -> None:
        """The request changed: which file gets how much depends on it, so the last run's labels no longer hold."""
        if self._uses is not None:
            self._uses = None
            self._rebuild()

    def files(self) -> list[dict]:
        """The bridge's `files` field: [{path, content}]."""
        return [
            {"path": name, "content": self._texts[path]}
            for name, path in zip(relative_names(self._paths), self._paths, strict=True)
        ]

    def _rebuild(self) -> None:
        while self.rows.count():
            item = self.rows.takeAt(0)
            row = item.widget() if item is not None else None
            if row is not None:
                row.hide()
                row.deleteLater()
        names = relative_names(self._paths)
        sizes = [len(self._texts[path].strip()) for path in self._paths]
        notes = [""] * len(self._paths)
        # Labels from the last run matter only when it read a digest; whole files everywhere need no label.
        uses = self._uses if self._uses and any(use != "whole" for use in self._uses.values()) else None
        if not self._material and uses:
            notes = [USE_NOTES[uses[name]] for name in names]
        if self._material:
            # The prompt carries the files whole after it (embedFiles), up to MAX_EMBED_CHARS together.
            room = MAX_EMBED_CHARS
            for index, size in enumerate(sizes):
                if room <= 0:
                    notes[index] = "left out: over the total limit"
                elif size > room:
                    notes[index] = "only the start is used"
                room -= min(size, max(room, 0))
        collapse = len(self._paths) > SHOWN_ROWS + 2
        for index, (name, path) in enumerate(zip(names, self._paths, strict=True)):
            if collapse and index >= SHOWN_ROWS:
                break
            self.rows.addWidget(self._row(name, path, notes[index]))
        if collapse:
            hidden = notes[SHOWN_ROWS:] if not self._material and uses else []
            self.rows.addWidget(self._more_row(len(self._paths) - SHOWN_ROWS, hidden))
        # A skill, project file or subagent reads the files whole while they fit, else a digest (composeWithFiles);
        # which file gets how much depends on the request, so the rows do not guess it per file.
        if not self._material and (any(size > MAX_FILE_CHARS for size in sizes) or sum(sizes) > MAX_FILES_CHARS):
            digest = QLabel(
                "The last run read a digest: the file tree, then each file as its row says"
                if uses
                else "Too long to read whole: the model reads the file tree, small files whole, outlines of the rest"
            )
            digest.setObjectName("attachNote")
            digest.setWordWrap(True)
            self.rows.addWidget(digest)
        # Hidden while empty: a visible zero-height block would still add the column's spacing under the request.
        self.setVisible(bool(self._paths))
        self.changed.emit()

    def _more_row(self, more: int, notes: list[str]) -> QWidget:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(4)
        counts = [f"{notes.count(note)} {note}" for note in USE_NOTES.values() if notes.count(note)]
        chip = QLabel(f"… and {more} more files" + (f"  · {', '.join(counts)}" if counts else ""))
        chip.setObjectName("chip")
        chip.setToolTip("\n".join(relative_names(self._paths)[SHOWN_ROWS : SHOWN_ROWS + 60]))
        line.addWidget(chip)
        cross = QPushButton()
        cross.setObjectName("deleteItem")
        cross.setIcon(QIcon(str(ROOT / "desktop" / "close.svg")))
        cross.setIconSize(QSize(12, 12))
        cross.setFixedSize(20, 20)
        cross.setToolTip("Remove all attached files")
        cross.setAccessibleName("Remove all attached files")
        cross.setCursor(Qt.CursorShape.PointingHandCursor)
        cross.clicked.connect(self.clear)
        line.addWidget(cross)
        line.addStretch(1)
        return row

    def _row(self, name: str, path: Path, note: str) -> QWidget:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(4)
        chip = QLabel(f"{name}  · {note}" if note else name)
        chip.setObjectName("chip")
        chip.setToolTip(str(path))
        line.addWidget(chip)
        cross = QPushButton()
        cross.setObjectName("deleteItem")
        cross.setIcon(QIcon(str(ROOT / "desktop" / "close.svg")))
        cross.setIconSize(QSize(12, 12))
        cross.setFixedSize(20, 20)
        cross.setToolTip("Remove this file")
        cross.setAccessibleName(f"Remove {name}")
        cross.setCursor(Qt.CursorShape.PointingHandCursor)
        cross.clicked.connect(lambda: self.remove(path))
        line.addWidget(cross)
        line.addStretch(1)
        return row
