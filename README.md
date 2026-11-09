# Prompta

Prompta turns a rough stream of thoughts into a ready-to-use prompt. The main app is a native macOS
desktop app ([desktop/README.md](desktop/README.md)). The same pipeline also runs from the terminal
(`npm run pipeline`) and as an MCP server for other agents ([mcp/README.md](mcp/README.md)).

![Prompta desktop](docs/preview-desktop.png)

## Features

- **Thoughts → brief → prompt.** The request is parsed into a brief (goal, format, constraints,
  assumptions), with up to 3 questions about missing facts. Answer them and rebuild for a sharper prompt.
- **Technique catalog.** 89 prompting techniques with sources ([catalog/catalog.json](catalog/catalog.json)).
  For the "Any" target, Prompta picks the cheapest technique that fits, and you can always choose one yourself.
- **Official guidance targets.** Claude, ChatGPT, Gemini and Grok prompts are built only from saved
  official rule sets with verified source links. Open-weight models use their own saved guides.
- **Zero-shot baseline.** Every result has a plain zero-shot variant to compare against.
- **Providers.** Ollama (local, no key), Gemini, OpenAI, Anthropic, xAI. Each request has a timeout,
  and token usage is reported for every run.
- **Untrusted input stays data.** Pasted documents and agent context are passed to the pipeline as
  delimited data. Prompts that process third-party material get a data-not-instructions rule in the
  prompt's own language.

## Quick start

Requirements: Node.js 22+. The desktop app also needs Python 3.12 with PyQt6.

```bash
npm install
```

```bash
python3 desktop/app.py
```

From the terminal (the key comes from the environment or `.env.local`):

```bash
npm run pipeline -- "sort support emails into billing/shipping/returns, strict JSON" --provider ollama --model qwen3:8b
```

| Provider | `--provider` | Key variable |
|---|---|---|
| Ollama | `ollama` | none |
| Gemini | `gemini` | `GEMINI_API_KEY` |
| OpenAI or a compatible API | `openai` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| xAI | `xai` | `XAI_API_KEY` |

## Measuring quality

Offline tests need no network and no keys:

```bash
npm test
```

```bash
npm run typecheck
```

Live evaluation lives in [eval/](eval/README.md). It runs 28 tasks, 10 of them with injected commands.
The judge scores prompts against a 5-criterion rubric, and an optional second judge from another model
family cross-checks it.

```bash
node eval/run.ts --target catalog --ids meeting-actions,inj-email-triage --repeat 3 --provider ollama --model qwen3:8b --out report.json
```

```bash
node eval/run.ts --target claude --repeat 3 --provider anthropic --model claude-opus-5-5
```

```bash
node eval/execute.ts --suite all --target catalog --provider ollama --model qwen3:8b
```

```bash
node eval/regress.ts --current report.json --baseline eval/baselines/catalog.json
```

- `--target` selects the mode under test: `catalog`, `claude`, `chatgpt`, `gemini`, `grok` or `open:<model id>`.
- `eval/execute.ts` runs the generated prompts on inputs with known answers (JSON extraction, math,
  sentiment) and reports accuracy, accuracy under injection, and the lift over zero-shot.
- Every report records the prompt version (a fingerprint of the pipeline's internal prompts), the
  judge version and token cost. `eval/regress.ts` fails on a clear drop against the saved baseline.

## CI

| Workflow | When | What |
|---|---|---|
| `ci` | every push and PR | types, offline tests, catalog validation, web build, desktop tests, `.app` bundle |
| `eval-nightly` | daily | live eval for `catalog` and `claude` against `eval/baselines/`; skipped without a provider key |
| `source-drift` | weekly | re-downloads the official Claude, ChatGPT, Gemini and Grok guides and fails if a snapshot changed |

## Repository layout

| Path | Contents |
|---|---|
| `pipeline/` | Brief, technique gate, selection, synthesis, official targets, LLM adapters ([README](pipeline/README.md)) |
| `catalog/` | Technique catalog and its validator ([README](catalog/README.md)) |
| `*_prompt_rules/`, `open_model_prompt_guides/` | Saved official guidance with snapshots and hashes |
| `eval/` | Tasks, judge, execution suites, regression gate, baselines |
| `desktop/` | PyQt6 app, bridge to the pipeline, local history |
| `mcp/` | MCP server: `improve_prompt`, `suggest_next_prompts` |
| `index.tsx` | Legacy web UI on Vite (`npm run dev`); the desktop app is the main interface |
| `docs/audit-2026-11.md` | Repository audit and the improvement plan it led to |

## Privacy

- The desktop app keeps API keys only in memory. The one exception: connecting the MCP server to a
  client from the app's MCP settings writes the key into that client's MCP config, as the client requires.
- History is stored locally in `~/Library/Application Support/Prompta/history.sqlite3` with
  owner-only permissions.
- History keeps the newest 500 entries. Change the limit with `PROMPTA_HISTORY_MAX`, add an age
  limit with `PROMPTA_HISTORY_DAYS`, or set `PROMPTA_HISTORY_MAX=-1` to turn history off.
- Context sent through MCP is trimmed, and secrets in it are redacted before it reaches a model.

## License

[MIT](LICENSE)
