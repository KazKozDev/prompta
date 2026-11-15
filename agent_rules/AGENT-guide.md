# Writing a subagent

Verified on **2026-11-15** against `snapshots/` (ids in brackets are `sources.json` entries).
Each rule the model receives is in `rules.json` with an exact quote (`evidence`) from its source.

## One prompt, four files

`AGENT-template.md` is the agent's prompt for every target: role, steps, checks, limits, what to do
when unclear, report format. Only the wrapper differs.

| Target | File | Wrapper | Required | Limits |
|---|---|---|---|---|
| `claudeCode` | `.claude/agents/<name>.md` | YAML frontmatter, prompt as body | `name`, `description` [claude-code-subagents] | descriptions of all agents under 15,000 tokens combined |
| `cursor` | `.cursor/agents/<name>.md` (also reads `.claude/agents/`) | YAML frontmatter, prompt as body | none; `name` from the file name [cursor-subagents] | keep the prompt short |
| `codex` | `.codex/agents/<name>.toml` | TOML; prompt in `developer_instructions = """…"""` | `name`, `description`, `developer_instructions` [codex-subagents] | |
| `copilot` | `.github/agents/<name>.agent.md` | YAML frontmatter, prompt as body | `description` [copilot-custom-agents-configuration] | prompt ≤ 30,000 characters |

Known fields:

- **claudeCode**: `name`, `description`, `tools`, `disallowedTools`, `model`, `permissionMode`, `maxTurns`,
  `autoCompactWindow`, `skills`, `mcpServers`, `hooks`, `memory`, `background`, `omitClaudeMd`, `effort`,
  `isolation`, `color`, `initialPrompt`, `experimental`. Unknown fields are ignored without an error.
  `model`: `sonnet`, `opus`, `haiku`, `fable`, a full model ID, `inherit`. `permissionMode`: `default`,
  `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions`, `plan`, `manual`. *(volatile: fields are added often)*
- **cursor**: `name`, `description`, `model`, `readonly`, `is_background`.
- **codex**: `name`, `description`, `developer_instructions`, `model`, `model_reasoning_effort`,
  `model_reasoning_summary`, `model_verbosity`, `features.*`, `skills.*`. `sandbox_mode`, `approval_policy`,
  `model_provider`, `mcp_servers` are ignored in an agent file.
- **copilot**: `name`, `description`, `target`, `tools`, `model`, `disable-model-invocation`, `user-invocable`,
  `mcp-servers`, `metadata` (`infer` is retired). Tool aliases: `execute`, `read`, `edit`, `search`, `agent`,
  `web`, `todo`.

## What a validator can check

- The wrapper parses: frontmatter starts on line 1 (Markdown targets), TOML parses (codex).
- Required fields are present and non-empty; `name` is lowercase-hyphen, no `:`.
- Unknown fields per target (a warning for claudeCode, where new fields appear between versions).
- Enumerated values: `model`, `permissionMode`, `readonly`/`is_background` booleans, `target`.
- A read-only role (reviewer, auditor, researcher) that keeps edit tools: a warning.
- The prompt is not empty; Copilot prompt length; «INSERT HERE» placeholders left.

## Left out on purpose

Hooks, MCP server definitions and persistent memory: they need project configuration the task rarely
gives. The writer adds them only when the task names them.
