"""What the window sends to the bridge for a prompt and what the status line says when the answer comes back.

Plain data in and out, no widgets: PromptaWindow reads its controls and passes the values here.
"""

from __future__ import annotations

from collections.abc import Sequence


def prompt_request(
    thoughts: str,
    generator: dict,
    target: dict,
    variants: int,
    files: dict,
    profile: str,
    agent_capabilities: Sequence[str],
    technique_keys: Sequence[str],
    revised_brief: dict | None = None,
) -> dict:
    """The bridge request for Prompt mode (desktop/bridge.ts BridgeRequest)."""
    payload = {
        "thoughts": thoughts,
        **generator,  # provider, model, key and URL
        **target,  # the "Written for" choice; nothing for any LLM
        "variants": variants,
        **files,
        "executionProfile": profile,
    }
    if profile == "agent":
        payload["agentCapabilities"] = list(agent_capabilities)
    if len(technique_keys) == 1:
        payload["manualTechnique"] = technique_keys[0]
    elif technique_keys:
        payload["manualTechniques"] = list(technique_keys)
    if revised_brief is not None:
        payload["brief"] = revised_brief  # edited assumptions: rebuild from this brief, not a new one
    return payload


def document_status(ready_name: str, file_name: str, check: dict | None) -> str:
    """SKILL.md, AGENTS.md or a subagent: ready, or how many validation problems are left."""
    check = check or {}
    if check.get("valid"):
        return f"{ready_name} · ready"
    return f"{file_name} · {len(check.get('errors') or [])} problem(s) left"


def manual_status(manual: dict) -> str:
    built, failed = len(manual.get("variants") or []), len(manual.get("failed") or [])
    if built > 1:
        return f"{built} techniques built" + (f" · {failed} failed, see below the prompt" if failed else "")
    return f"{manual['technique']['name']} · built using this method"


def pipeline_status(name: str, warnings: int) -> str:
    if not warnings:
        return f"{name} · ready"
    return f"{name} · {warnings} warning{'s' if warnings != 1 else ''} below the prompt"
