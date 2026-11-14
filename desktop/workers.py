"""Prompta background threads: the bridge to the TS pipeline, loading models and techniques."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import deque
from threading import Thread
import sys
import urllib.request
from pathlib import Path


from PyQt6.QtCore import QThread, pyqtSignal

from theme import FROZEN, ROOT


BRIDGE = ROOT / "desktop" / "bridge.ts"

OLLAMA_TAGS = "http://localhost:11434/api/tags"
FALLBACK_MODELS = [
    "minimax-m3.1-flash:cloud",
    "glm-5.3:cloud",
    "deepseek-v4-pro:cloud",
    "qwen3:30b",
]


def fetch_ollama_models(timeout: float = 3.0) -> list[str]:
    """The full model list from the local Ollama daemon. Empty means the daemon is not running."""
    try:
        with urllib.request.urlopen(OLLAMA_TAGS, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    names = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    return sorted(set(names), key=str.lower)


def node_binary() -> str:
    if FROZEN:  # the standalone app carries its own node (build_standalone.sh)
        return str(Path(getattr(sys, "_MEIPASS", "")) / "node")
    for candidate in (shutil.which("node"), "/opt/homebrew/bin/node", "/usr/local/bin/node"):
        if candidate and Path(candidate).exists():
            return candidate
    return "node"


class TechniquesLoader(QThread):
    loaded = pyqtSignal(list)
    prompt_version = ""  # version of the pipeline's prompts, to spot history built under older rules

    def run(self) -> None:
        try:
            proc = subprocess.run(
                [node_binary(), str(BRIDGE)],
                input=json.dumps({"thoughts": "x", "listTechniques": True, "model": "dummy"}),
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(ROOT),
            )
            data = json.loads(proc.stdout or "{}")
            self.prompt_version = str(data.get("promptVersion") or "")
            self.loaded.emit(data.get("techniques", []))
        except Exception:
            self.loaded.emit([])


CLOUD_MODEL_LISTS = {  # provider → default API root; each lists its models at its own endpoint
    "openai": "https://api.openai.com",
    "xai": "https://api.x.ai",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
}


def fetch_cloud_models(provider: str, api_key: str, base_url: str = "", timeout: float = 8.0) -> list[str]:
    """The provider's current model ids, asked from its own API with the user's key. Empty on any failure."""
    base = (base_url.strip() or CLOUD_MODEL_LISTS.get(provider, "")).rstrip("/")
    if not base.startswith(("http://", "https://")) or not api_key:
        return []
    if provider == "anthropic":
        url, headers = base + "/v1/models?limit=1000", {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    elif provider == "gemini":
        url, headers = (
            base + "/v1beta/models?pageSize=1000",
            {"x-goog-api-key": api_key},
        )  # key in a header, not the URL
    else:
        url = (base if base.endswith("/v1") else base + "/v1") + "/models"
        headers = {"authorization": f"Bearer {api_key}"}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    if provider == "gemini":  # only models that can generate text; ids come as "models/<id>"
        names = [
            m.get("name", "").removeprefix("models/")
            for m in data.get("models", [])
            if isinstance(m, dict) and "generateContent" in (m.get("supportedGenerationMethods") or [])
        ]
    else:
        names = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]
    return sorted({n for n in names if n}, key=str.lower)


# Without a key the providers refuse their model list, so a public catalog fills it: models.dev (anonymous GET).
CATALOG_URL = "https://models.dev/api.json"
CATALOG_CACHE = Path.home() / "Library" / "Application Support" / "Prompta" / "model-catalog.json"
CATALOG_IDS = {"openai": "openai", "anthropic": "anthropic", "gemini": "google", "xai": "xai"}  # ours → models.dev
CATALOG_MAX_AGE = 24 * 3600  # the full file is ~6 MB: fetch at most once a day, keep only the ids we use


def reduce_catalog(data: dict) -> dict[str, list[str]]:
    """Per provider: current text-generating model ids, newest first."""
    out: dict[str, list[str]] = {}
    for ours, theirs in CATALOG_IDS.items():
        models = ((data.get(theirs) or {}).get("models") or {}).values()
        usable = [
            m
            for m in models
            if isinstance(m, dict)
            and m.get("id")
            and m.get("status") != "deprecated"
            and "text" in ((m.get("modalities") or {}).get("output") or [])
        ]
        usable.sort(key=lambda m: (str(m.get("release_date") or ""), m["id"]), reverse=True)
        out[ours] = [m["id"] for m in usable]
    return out


def catalog_models(provider: str, cache: Path | None = None, timeout: float = 20.0) -> list[str]:
    """The provider's models from the cached catalog, refreshed when older than a day; a stale copy beats nothing."""
    import time

    cache = cache or CATALOG_CACHE
    try:
        saved = json.loads(cache.read_text())
    except (OSError, ValueError):
        saved = {}
    if time.time() - float(saved.get("fetched", 0)) > CATALOG_MAX_AGE:
        try:
            request = urllib.request.Request(CATALOG_URL, headers={"user-agent": "Prompta"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                fresh = reduce_catalog(json.loads(response.read().decode("utf-8")))
            saved = {"fetched": time.time(), "models": fresh}
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(saved))
        except Exception:
            pass  # offline: keep whatever copy there is
    return list((saved.get("models") or {}).get(provider) or [])


class ModelsLoader(QThread):
    """One provider's model list: Ollama's local daemon, the cloud provider's API with the user's key,
    or, without a key (or when the provider refuses), the public catalog. `source` says which one answered."""

    loaded = pyqtSignal(list)

    def __init__(self, provider: str = "ollama", api_key: str = "", base_url: str = "") -> None:
        super().__init__()
        self.provider, self.api_key, self.base_url = provider, api_key, base_url
        self.source = "ollama" if provider == "ollama" else "provider"

    def run(self) -> None:
        if self.provider == "ollama":
            self.loaded.emit(fetch_ollama_models())
            return
        names = fetch_cloud_models(self.provider, self.api_key, self.base_url) if self.api_key else []
        if not names and not self.base_url:  # a custom URL is not that provider's public catalog
            names, self.source = catalog_models(self.provider), "catalog"
        self.loaded.emit(names)


class Worker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(dict)

    def __init__(self, payload: dict) -> None:
        super().__init__()
        self.payload = payload
        self.proc: subprocess.Popen | None = None
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def run(self) -> None:
        try:
            if self.cancelled:
                self.finished_ok.emit({"ok": False, "error": "Cancelled"})
                return
            self.proc = subprocess.Popen(
                [node_binary(), str(BRIDGE)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(ROOT),
            )
            if self.cancelled:
                self.proc.terminate()
            errors: deque[str] = deque(maxlen=20)
            stderr = self.proc.stderr
            # Drain progress separately while communicate retains its timeout and stdout handling.
            self.proc.stderr = None

            def read_progress() -> None:
                try:
                    for line in stderr:
                        if line.startswith("PROMPTA_PROGRESS "):
                            try:
                                update = json.loads(line.removeprefix("PROMPTA_PROGRESS "))
                                percent, stage = update["percent"], update["stage"]
                                if type(percent) is int and 0 <= percent <= 100 and isinstance(stage, str):
                                    self.progress.emit(percent, stage[:160])
                            except (ValueError, KeyError, TypeError):
                                pass
                        else:
                            errors.append(line[-400:])
                finally:
                    stderr.close()

            reader = Thread(target=read_progress, daemon=True)
            reader.start()
            try:
                out, err = self.proc.communicate(json.dumps({**self.payload, "reportProgress": True}), timeout=900)
            finally:
                if self.proc.poll() is None:
                    self.proc.kill()
                    self.proc.communicate()
                reader.join(timeout=2)
            err = "".join(errors) or err
            if self.cancelled:
                self.finished_ok.emit({"ok": False, "error": "Cancelled"})
                return
            out = (out or "").strip()
            if not out:
                raise RuntimeError((err or "Empty response from the pipeline")[-400:])
            self.finished_ok.emit(json.loads(out))
        except Exception as exc:  # noqa: BLE001
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
                self.proc.communicate()
            message = "Cancelled" if self.cancelled else str(exc)
            self.finished_ok.emit({"ok": False, "error": message})
