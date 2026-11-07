# Official ChatGPT prompting rules

Verified **2026-11-05**, scoped to the seven URLs in `sources.json`.
This is not a claim to have copied every recommendation on the OpenAI website.

- `snapshots/`: original official Markdown from ChatGPT Learn and OpenAI Developers.
- `sources.json`: titles, URLs, exact section anchors, timestamps, and SHA-256 hashes.
- `rules.json`: 52 recommendations; 41 active prompt-level rules. Workflow/API advice stays out of ordinary consumer prompts. Historical reasoning/formatting examples are marked reference-only.
- `sections.json`: all 167 scoped sections with original examples and source line ranges.
- `coverage.json`: boundaries and resolutions of conflicting or version-dependent advice.
- `refresh_sources.py`: manual official-host-only downloader. Refreshing snapshots does not approve changed recommendations; re-review rules and hashes before activation.

“For ChatGPT” is off by default and mutually exclusive with Claude and
Gemini. It targets a paste-ready ChatGPT prompt without changing the generator
provider or model. It does not provision API credentials, call ChatGPT, or assume
any subscription, exact GPT model, browsing, connectors, or API-only features.

The shared compiler in `pipeline/official.ts` receives only this target's active
prompt-level rules plus the original user task. Generic catalog techniques,
manual-technique selection, deterministic synthesis, and simultaneous target
flags cannot bypass the mode. Rule datasets are lazily loaded per target.

Generated results carry a rule-set version, verification date, model-reported
rule IDs for each variant, and official source links. These survive native
history persistence. IDs are traceability metadata, not independently measured
proof of semantic compliance. Incomplete outputs, unknown IDs, changed source
hashes, and untrusted URLs are rejected with one correction attempt.

General reasoning guidance takes precedence over older meta-prompt examples that
request visible chain-of-thought. Prompt formatting instructions do not guarantee
API Structured Outputs. Relevant application-level rules remain stored for
inspection without being inserted into unrelated user prompts.

Verification: `npm test`, `npm run typecheck`, `npm run build`, and
`python3 desktop/test_app.py` with PyQt6 installed. Live checks use the already
configured generator on synthetic data; they do not assert execution on ChatGPT.
