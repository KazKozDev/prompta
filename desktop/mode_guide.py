"""The text of the empty request field, per mode: one short paragraph, what to type and what you get.

The second sentence carries the difference between the modes: when the result is used and by whom
(once in a chat, every session in this project, whenever a task matches, a job handed over).
"""

from __future__ import annotations

# mode key (skill_mode.py) → what to type, then what the user gets and when it is used
GUIDES = {
    "prompt": (
        "Describe the task in your own words, rough is fine. "
        "You'll get a prompt for this one task: paste it into any chat."
    ),
    "instructions": (
        "Describe the project: stack, commands, conventions, what agents get wrong. "
        "You'll get AGENTS.md: rules your coding agent follows in every session of this project."
    ),
    "skill": (
        "Describe a procedure you repeat: what it does, when to use it, its steps and limits. "
        "You'll get SKILL.md: an agent loads it whenever a task matches, in any project."
    ),
    "agent": (
        "Describe the specialist: its one job, when to call it, what it must not touch. "
        "You'll get a subagent: your main agent hands it that job and gets the result back."
    ),
}


def placeholder(mode: str) -> str:
    return GUIDES.get(mode, GUIDES["prompt"])
