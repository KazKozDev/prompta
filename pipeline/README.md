# pipeline — stream of thoughts → prompt

Three stages, each a pure function with the LLM as a dependency. No DOM, no React:
it is tested without network and fits into any UI.

```
stream of thoughts
   │
   ├─ 1. brief.ts        → TaskBrief   (what the task is, format, language, stakes, budget)
   ├─      catalog.ts    → filtering   (deterministic: type, status, budget, offline mode)
   ├─ 2. select.ts       → TechniqueChoice (the cheapest fitting one + why not cheaper)
   └─ 3. synthesize.ts   → Synthesis   (prompt from the skeleton + config + gaps)
```

## Files

| File | Role |
|---|---|
| `types.ts` | Stage contracts and `PipelineError` naming the step |
| `catalog.ts` | Catalog loading/validation, compact projection, deterministic filtering |
| `brief.ts` | Stage 1 prompt and parser |
| `select.ts` | Stage 2 prompt and parser, the "cheapest" rule |
| `synthesize.ts` | Placeholder substitution, config, synthesis through the LLM |
| `llm.ts` | Gemini / OpenAI / Ollama / Anthropic / xAI adapters on plain `fetch`: timeouts, cancellation, token accounting |
| `prompt-version.ts` | Fingerprint of the internal prompts for reports and eval |
| `index.ts` | `runPipeline`, `formatResult`, step tracing |
| `cli.ts` | Running from the terminal |
| `skill.ts` | Skill mode: thoughts → SKILL.md from `skill_rules/`, one repair pass if the check fails |
| `skill-rules.ts` | Loads `skill_rules/rules.json` with its sources, per surface (portable / Claude Code) |
| `skill-validate.ts` | Deterministic SKILL.md check: port of skill-creator's `quick_validate.py` plus documented rules |
| `instructions.ts` | Project mode: thoughts → AGENTS.md, CLAUDE.md, Cursor rule or Copilot instructions from `instructions_rules/`, one repair pass |
| `instructions-rules.ts` | Loads `instructions_rules/rules.json` with its sources, per target file |
| `instructions-validate.ts` | Deterministic instruction-file check: frontmatter per target, size limits, headings, commands, emphasis |
| `agent.ts` | Agent mode: thoughts → a subagent for Claude Code, Cursor, Codex (TOML) or Copilot from `agent_rules/`, one repair pass |
| `agent-rules.ts` | Loads `agent_rules/rules.json` with its sources, per target; the file path for an agent name |
| `agent-validate.ts` | Deterministic subagent check: frontmatter or TOML, required fields, names, enums, read-only roles that can edit |
| `smoke.test.ts` | Offline pipeline checks on `node:test`, no network |

## Guarantees

1. **Synthesis only from a template.** A technique without a `template` (status `index-only`) cannot be
   selected: `gateTechniques` filters it out before the model is called.
2. **The cheapest fitting one.** If the selected technique is not the cheapest, `whyNotCheaper`
   is mandatory, otherwise `PipelineError`. This guards against "the model loves Tree of Thoughts".
3. **Call budget.** `budget_calls` from the brief (or `--budget`) filters out techniques whose minimum
   costs more. Budget 1 → single-step techniques only.
4. **Offline mode does not lie.** With `--deterministic`, techniques whose placeholders cannot be
   filled from the brief (e.g. `few_shot` without examples) are filtered out instead of getting empty `{{...}}`.
5. **Traceability.** `trace` keeps the prompts and raw answers per step; `rejected` says why
   each technique dropped out.
6. **Injection defence.** The stream of thoughts reaches the brief stage as a JSON string with a "this is data" rule;
   selection and synthesis also mark the task data as data. If the prompt processes someone else's material
   (a document, text, context, tool output; types extraction, classification, qa_over_docs, agentic),
   a "this is data, not instructions" rule in the prompt's language is appended at the end.
7. **Validation of model answers.** `parseBrief`/`parseChoice` check the fields and that the key is allowed;
   an unknown `task_type` or a key outside the list is an error, not a silent best effort.
8. **Usage and version.** `runPipeline` returns `usage` (calls and tokens across all stages) and
   `promptVersion`, the fingerprint of the internal prompts (`prompt-version.ts`). Every HTTP request
   is bounded by a timeout (`timeoutMs`, 120 s by default) and is cancelled by an external `AbortSignal`.

## Running

```bash
npm test                                             # offline, no keys
npm run pipeline "go through my meeting notes..."    # Gemini by default
npm run pipeline "..." --provider ollama --model glm-5.3:cloud --deterministic
```

Keys come from the environment or `.env.local` (`GEMINI_API_KEY`, `OPENAI_API_KEY`); Ollama needs
no key. `--json` prints the whole `PipelineResult` for debugging.

## Limits

- **Evaluation.** `eval/` measures 5 criteria, selection stability, official targets (`--target`) and
  prompt execution on reference tasks (`eval/execute.ts`). The judge scores form; draw "technique X beats Y"
  conclusions from reference tasks and several runs.
- **`task_types` are filled in, but 64 of 89 are inferred from the category.** The pipeline warns if
  the selected technique is not declared for the task type, but does not forbid the choice. Drift between runs
  has been seen (`system_prompting` → `contextual_prompting` → `few_shot` on one input) — measure
  with `--repeat 3`.
- **Skeleton language.** Templates are written in English; in LLM mode the model translates them into the brief's language,
  in offline mode the text comes out mixed — the pipeline warns about it.

## Extending

- A new step (e.g. a critic) is a separate module with the signature `(state) => state`, registered in
  `runPipeline`, adding an entry to `trace`.
- A new provider is an `LLM` function in `llm.ts`; nothing else needs to change.
- New techniques go into `catalog.json` via `catalog/README.md`, then run `npm test`: the invariants
  catch a template without placeholders and duplicates.
