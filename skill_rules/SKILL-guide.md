# Writing a SKILL.md: guide

Companion to [SKILL-template.md](SKILL-template.md). The template is the skeleton to copy;
this file explains how to fill it.

Verified against the sources below on **2026-11-14**. Numbers and field lists change:
re-check the sources before relying on anything marked *(volatile)*.

## Sources

- [Agent Skills specification](https://agentskills.io/specification): open standard (fields, directories, validation)
- [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview): field rules, runtime per surface
- [Using Agent Skills with the API](https://platform.claude.com/docs/en/build-with-claude/skills-guide): upload limits, versions
- [Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices): writing guidance
- [Use Skills in Claude Code](https://code.claude.com/docs/en/skills): Claude Code frontmatter extensions
- [skill-creator `quick_validate.py`](https://github.com/anthropics/skills/blob/main/skills/skill-creator/scripts/quick_validate.py): allowed keys check

## Frontmatter

Only `name` and `description` are required. Every skill's `name` and `description`
are loaded at session start (~100 tokens per skill); the body is read only when the skill is used.

### `name`

- 1–64 characters: lowercase letters, digits, hyphens.
- No leading/trailing hyphen, no `--`, no XML tags.
- Must not contain `anthropic` or `claude`.
- Must match the skill's folder name.
- Prefer a gerund: `processing-pdfs`, `analyzing-spreadsheets`. Avoid `helper`, `utils`, `tools`, `data`.

### `description`

The most important field: Claude matches requests against it to decide whether to load the skill.

- Non-empty, up to 1024 characters, no XML tags.
- Third person: "Extracts…", not "I can help…" or "You can use this…".
- Two parts: **what** it does + **when** to use it ("Use when …").
- Concrete triggers: file formats, terms, phrases a user would actually say.
- Main use case first: Claude Code truncates `description` + `when_to_use` to
  1,536 characters in the skill listing *(volatile)*.
- Triggers too often → add "Do NOT use for …" and narrow the scope.
- Bad: "Helps with documents".

### Optional fields from the open standard

| Field | Notes |
| - | - |
| `license` | License name or bundled license file. |
| `compatibility` | Up to 500 chars: environment requirements. Most skills don't need it. |
| `metadata` | Map of string keys to string values for your own tooling. |
| `allowed-tools` | Space-separated pre-approved tools, e.g. `Read Bash(python3:*)`. Marked **experimental** in the spec; support varies by client *(volatile)*. In Claude Code it pre-approves tools for the invoking turn only and does not restrict other tools. |

### Claude Code-only extensions *(volatile)*

skill-creator's `quick_validate.py` accepts only `name`, `description`, `license`,
`allowed-tools`, `metadata` and `compatibility`, and fails on any other top-level key.
`package_skill.py` runs the same check before zipping a skill into a `.skill` file.
How claude.ai and the Skills API treat unknown keys isn't documented. Use the keys below
only in skills that live in Claude Code.

| Key | Effect |
| - | - |
| `when_to_use` | Extra trigger phrases, appended to `description` (counts toward the 1,536 cap). |
| `argument-hint` | Autocomplete hint, e.g. `"[invoice-file]"`. |
| `arguments` | Named arguments → `$file`, `$format` in the body. |
| `disable-model-invocation: true` | Only runs manually via `/name` (deploys etc.). |
| `user-invocable: false` | Hidden from the `/` menu; only Claude invokes it. |
| `disallowed-tools` | Tools removed while the skill is active. |
| `model`, `effort` | Model and effort for the rest of the turn. |
| `context: fork` + `agent` | Run in a forked subagent; `background: false` waits for the result. |
| `paths` | Globs limiting automatic loading, e.g. `["**/*.pdf"]`. |
| `hooks` | Hooks registered on invocation, kept for the session. |
| `shell` | Shell for `` !`command` `` blocks: `bash` (default) or `powershell`. |

In Claude Code, `name` defaults to the folder name.

## Body

- Under 500 lines; move details into separate files as you approach it.
- Claude is already smart: don't explain what a PDF or CSV is. Each paragraph must justify its tokens.
- One set of terms throughout ("field", not field/box/element).
- No time-sensitive instructions ("before August 2025…"); put outdated material in an "Old patterns" section.
- Forward slashes in paths: `scripts/validate.py`.
- Critical rules at the top: they are less likely to be skipped.
- The body stays in context after invocation and isn't re-read, so write standing rules, not one-time steps.
- No API keys or passwords: everyone you share the skill with gets them.

### Section by section

**Quick start.** The most common scenario in minimal form. One default approach, not five
libraries to choose from; at most one fallback branch.

**Workflow.** A checklist Claude copies and ticks off. Match freedom to fragility:
- high (prose instructions): several approaches are valid;
- medium (template or pseudocode with parameters): a preferred pattern exists;
- low (exact command, "don't change the flags"): the operation is fragile.

Add a feedback loop: validate → fix → repeat. The validator can be a script or a reference
file (e.g. `STYLE_GUIDE.md`). For batch or irreversible operations use a plan file:
analyze → plan → validate the plan → execute → verify.

**Output format.** Strict (APIs, data formats): "ALWAYS use this exact structure".
Flexible: "sensible default, adapt as needed". If quality depends on style, give 2–3
input → output pairs.

**Rules.** Hard constraints, right after Quick start: after compaction only the start of a skill may be kept.
If Claude skips them, phrase them more strongly ("MUST") and give the reason. For MCP tools use fully qualified names: `ServerName:tool_name`.

**Scripts.** Say explicitly whether Claude should **run** a script or **read** it as reference.
Scripts handle their own errors, avoid unexplained magic numbers, and list dependencies.

**Additional resources.** Files Claude reads only when needed (progressive disclosure).
Links one level deep from SKILL.md, descriptive file names, a table of contents in files
over 100 lines, one file per domain.

### Runtime per surface *(volatile)*

| Surface | Network | Packages |
| - | - | - |
| Claude API | none | pre-installed only, no runtime install |
| claude.ai | depends on user/admin settings | — |
| Claude Code | full | install locally, not globally |

Script paths: Claude Code substitutes `${CLAUDE_SKILL_DIR}` (the folder of SKILL.md).
Elsewhere use paths relative to SKILL.md (`scripts/extract.py`); relative paths are the portable choice.

## Folder structure

```
processing-invoices/      ← folder name = name
├── SKILL.md              ← required, exactly this name (case-sensitive)
├── examples.md           ← loaded as needed
├── references/           ← documentation
├── assets/               ← templates, images, tables Claude copies or fills in
└── scripts/              ← executed, not loaded into context
```

No README.md inside the skill folder; keep it at the repository level.

## Before publishing

- [ ] `description` is specific, has key terms, covers what + when
- [ ] Body under 500 lines, details in separate files
- [ ] References one level deep, nothing time-sensitive, consistent terms
- [ ] Concrete examples, clear workflow steps, checks on critical operations
- [ ] Scripts handle errors, dependencies listed, paths use `/`
- [ ] At least 3 evals; tested on Haiku, Sonnet and Opus on real tasks
- [ ] Triggering: loads on obvious and paraphrased requests, not on unrelated ones
- [ ] Baseline: same requests in a fresh session with and without the skill
- [ ] Validate: `skills-ref validate ./my-skill` (or `claude plugin validate` for a plugin)
- [ ] claude.ai: zip from the parent folder so the skill folder is the archive root;
      check with `unzip -l`
- [ ] API: total upload under 30 MB uncompressed *(volatile)*; a new version is a full
      snapshot, so upload every file each time

## How to develop

1. Solve the task with Claude without a skill; note what you keep explaining.
2. Write 3 test scenarios and measure results without the skill.
3. Ask one Claude instance ("Claude A") to turn it into a skill, then cut the excess.
4. Test on a fresh instance ("Claude B") with real tasks, bring observations back to A, repeat.
5. For automated checks, use the skill-creator skill from
   [anthropics/skills](https://github.com/anthropics/skills): it runs prompts with and
   without the skill and helps tune the description.

## Troubleshooting

- **Doesn't trigger:** make the description more specific, add real phrases and file types;
  ask Claude when it would use the skill.
- **Triggers too often:** negative triggers, narrower scope.
- **Doesn't load:** file named `SKILL.md`, first line exactly `---`, valid YAML,
  no spaces or capitals in `name`.
- **Rules ignored:** shorten, move critical rules to the top, replace vague wording with
  explicit checks or a script.
