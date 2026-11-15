# Official project-instruction rules

Verified on **2026-11-15**. Used by Project mode (`pipeline/instructions.ts`): thoughts → an agent instruction file
(AGENTS.md, CLAUDE.md, Cursor `.cursor/rules/*.mdc`, Copilot `copilot-instructions.md`).

- `sources.json`: every snapshot with its URL and SHA-256.
- `snapshots/`: the documents as downloaded, Markdown where the site serves it. `agents-md-repo/` holds
  files from [openai/agents.md](https://github.com/openai/agents.md) pinned to a commit (`SOURCE.md`).
  Kept byte-for-byte.
- `rules.json`: 31 rules for the model, each tied to a source, the targets it applies to, and an exact quote
  (`evidence`) that must appear in the snapshot.
- `INSTRUCTIONS-template.md`: the body skeleton, the same for every target.
- `INSTRUCTIONS-guide.md`: file names, headers and size limits per target, with sources.

Key facts, checked against the snapshots: CLAUDE.md, target under 200 lines; Claude Code also reads AGENTS.md;
Codex stops adding AGENTS.md files at `project_doc_max_bytes`, 32 KiB by default; Cursor ignores a plain
`.md` in `.cursor/rules` (rules are `.mdc` with `description`, `globs`, `alwaysApply`).

`pipeline/instructions.test.ts` checks the snapshot hashes and that every rule's `evidence` appears in its snapshot.
A refresh of the snapshots does not update the rules: re-read the changed documents, update `rules.json`, then the hashes.
