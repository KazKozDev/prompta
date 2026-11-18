"""One line per mode, shown at the top of the empty request field: what you get and who uses it when.

Worded from the user's side ("You get …"), so it reads as the result of the mode, not a description of Prompta.
"""

from __future__ import annotations

# mode key (skill_mode.py) → what the user gets and when it is used
NOTES = {
    "prompt": "You get a prompt: the text for one task. Paste it into a chat and use it once.",
    "instructions": "You get AGENTS.md: your project's rules. Your coding agent reads it in every session.",
    "skill": "You get SKILL.md: a repeated procedure. An agent loads it when a task matches, in any project.",
    "agent": "You get a subagent: a specialist with its own tools. The main agent hands it a job.",
}


def mode_note(mode: str) -> str:
    return NOTES.get(mode, NOTES["prompt"])
