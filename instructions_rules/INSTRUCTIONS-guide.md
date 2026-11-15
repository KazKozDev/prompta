# Writing project instructions

Verified on **2026-11-15** against `snapshots/` (ids in brackets are `sources.json` entries).
Each rule the model receives is in `rules.json` with an exact quote (`evidence`) from its source.

## One body, four files

`INSTRUCTIONS-template.md` is the body for every target. Sections are optional: AGENTS.md has
no required fields [agents-md-site]. Keep a section only if it holds something the agent cannot
work out from the code [claude-code-best-practices].

| Target | File | Header | Size |
|---|---|---|---|
| `agentsMd` | `AGENTS.md` at the repo root; nested per package in a monorepo | none | Codex reads up to 32 KiB of all files combined [codex-agents-md] *(volatile)* |
| `claudeMd` | `CLAUDE.md` or `.claude/CLAUDE.md`; personal: `CLAUDE.local.md` | none; `@AGENTS.md` first line if the repo has one | under 200 lines [claude-code-memory] |
| `cursor` | `.cursor/rules/<name>.mdc` (`.md` is ignored) | frontmatter: `alwaysApply`, `globs`, `description` | under 500 lines per rule [cursor-rules] |
| `copilot` | `.github/copilot-instructions.md`; per path: `.github/instructions/NAME.instructions.md` | none; per path: `applyTo` | well under ~1,000 lines [github-blog-instructions-files] |

Cursor frontmatter for a project-wide rule:

```
---
alwaysApply: true
---
```

Claude Code also reads AGENTS.md when the repo has no CLAUDE.md [claude-code-memory] *(volatile:
behaviour since v2.1.277)*; Cursor and Copilot read AGENTS.md too [cursor-rules, copilot-repo-instructions].
So one AGENTS.md is the portable choice; the other three add tool-specific features.

## What to write

- Concrete and checkable: `Run npm test before committing`, not `Test your changes` [claude-code-memory].
- Name the command, directory or example file [vscode-custom-instructions].
- Reference files instead of copying them [cursor-rules].
- Headings and short bullets [claude-code-memory].

## What to leave out

- What a linter or formatter enforces, whole style guides, every common command [vscode-custom-instructions, cursor-rules].
- Multi-step procedures: a skill [claude-code-memory].
- Rules for one part of the codebase: a path-scoped file [claude-code-memory].
- Personal preferences: user scope [vscode-custom-instructions].
- `IMPORTANT`, capitals, "be more accurate": a rule without exceptions belongs in a hook or CI [claude-code-best-practices, github-blog-instructions-files].
- Contradictions: the agent may pick either side [claude-code-memory].

## What a validator can check

Deterministic: Cursor frontmatter keys and an `.mdc` name; `applyTo` present in an `.instructions.md`;
line count per target; no frontmatter in AGENTS.md / CLAUDE.md / copilot-instructions.md; no `IMPORTANT`/
all-caps emphasis; at least one runnable command in backticks. Contradictions need the model.
