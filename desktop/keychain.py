"""API keys in the macOS login Keychain, one item per provider, through the built-in `security` tool.

The key is written over stdin (`security -i`), never as a command-line argument, so it does not show
up in the process list. Without `security` (not macOS) every call is a quiet no-op.
"""

from __future__ import annotations

import shutil
import subprocess

SERVICE = "Prompta"


def _security() -> str | None:
    return shutil.which("security")


def load(provider: str) -> str:
    """The saved key for this provider, or "" when there is none."""
    tool = _security()
    if not tool or not provider:
        return ""
    result = subprocess.run([tool, "find-generic-password", "-s", SERVICE, "-a", provider, "-w"],
                            capture_output=True, text=True, timeout=10)
    return result.stdout.strip() if result.returncode == 0 else ""


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save(provider: str, key: str) -> bool:
    """Create or replace the provider's item. Keys with line breaks are refused rather than mangled."""
    tool = _security()
    if not tool or not provider or not key or "\n" in key or "\r" in key:
        return False
    command = f"add-generic-password -U -s {_quote(SERVICE)} -a {_quote(provider)} -w {_quote(key)}\n"
    result = subprocess.run([tool, "-i"], input=command, capture_output=True, text=True, timeout=10)
    return result.returncode == 0 and load(provider) == key


def forget(provider: str) -> None:
    tool = _security()
    if tool and provider:
        subprocess.run([tool, "delete-generic-password", "-s", SERVICE, "-a", provider],
                       capture_output=True, text=True, timeout=10)
