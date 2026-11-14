# Official Agent Skills rules

Verified on **2026-11-14**. Used by Skill mode (`pipeline/skill.ts`) to write a `SKILL.md`.

- `SKILL-template.md`: the skeleton the model fills in; the official validator accepts it.
- `SKILL-guide.md`: how to fill it, with sources; parts marked *volatile* change between releases.
- `rules.json`: the rules given to the model, each tied to a source; `surface: claude-code` rules apply only to Claude Code skills.
- `sources.json`: every snapshot with its URL and SHA-256; `pipeline/skill.test.ts` checks the hashes.
- `snapshots/`: the documents as downloaded, including selected files from
  [anthropics/skills](https://github.com/anthropics/skills) pinned to a commit (`snapshots/anthropics-skills/SOURCE.md`).
  Kept byte-for-byte, so ruff skips this folder.

`pipeline/skill-validate.ts` ports the checks of skill-creator's `quick_validate.py`
(`snapshots/anthropics-skills/skills/skill-creator/scripts/quick_validate.py`) and adds the
documented name, description and Claude Code key rules. A refresh of the snapshots does not
update the rules: re-read the changed documents, update `rules.json`, then the hashes.
