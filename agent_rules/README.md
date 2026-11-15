# Official subagent rules

Verified on **2026-11-15**. For Agent mode (planned): thoughts → a subagent definition file.

- `sources.json`: every snapshot with its URL and SHA-256.
- `snapshots/`: the documents as downloaded (all served as Markdown). Kept byte-for-byte.

Formats, from the snapshots:

| Tool | Project file | Format | Required |
|---|---|---|---|
| Claude Code | `.claude/agents/<name>.md` | YAML frontmatter + prompt | `name`, `description` |
| Cursor | `.cursor/agents/<name>.md` (also reads `.claude/agents/`, `.codex/agents/`) | YAML frontmatter + prompt | none (`name` from file name) |
| Codex | `.codex/agents/<name>.toml` | TOML | `name`, `description`, `developer_instructions` |
| GitHub Copilot | `.github/agents/<name>.agent.md` | YAML frontmatter + prompt | `description` |

- `rules.json`: 43 rules for the model, each tied to a source, the targets it applies to, and an exact quote
  (`evidence`) that appears in the snapshot.
- `AGENT-template.md`: the agent's prompt skeleton, the same for every target.
- `AGENT-guide.md`: file names, wrappers, known fields and what a validator can check.

A refresh of the snapshots does not update the rules: re-read the changed documents, update `rules.json`, then the hashes.
