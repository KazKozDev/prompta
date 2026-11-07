# Official Claude prompting rules

Verified on **2026-11-05**. The folder is at the root of the Prompta project;
`/claude_prompt_rules/` in the feature specification means this project folder,
not a directory at the root of the operating system.

## Corpus and traceability

- `sources.json`: 15 official documentation URLs, 159 section references, retrieval timestamps, snapshot filenames and SHA-256 hashes.
- `snapshots/`: original Markdown downloaded from `platform.claude.com`, the current official developer documentation linked from Anthropic/Claude.
- `rules.json`: 73 source-linked recommendations. 71 are active conditional/general recommendations; the older prefill recommendation is superseded, and medication-dose guidance is reference-only.
- `sections.json`: all 159 sections retained with original text, examples and source line ranges, including model-specific material that is not automatically activated.
- `coverage.json`: exact scope, exclusions and resolution of conflicting recommendations.
- `refresh_sources.py`: manual downloader restricted to the verified official host. A refresh does **not** automatically approve changed advice: re-review rules and regenerate their hashes before using changed snapshots.

This is a documented corpus, **not a claim to have captured every recommendation
on the entire Anthropic website**. Model-specific documents are preserved for
inspection, but this first mode targets **Claude general guidance** rather than
assuming a particular Claude release. Instructions requiring exact model-specific
settings or verbatim system blocks are not generalized. Source snapshots include
reference examples; examples are not automatically mandatory rules.

## Application behavior

“For Claude” is off by default. Enabling it uses a separate compiler with
only the active prompt-level saved Anthropic rules and the original user task. Workflow and API recommendations remain searchable source evidence rather than being pasted into unrelated end-user prompts. The generic
technique catalog is not sent to this compiler. The selected generator provider
and model stay unchanged; the generated prompt is intended for Claude. This does
not add a Claude API provider or make API calls to Anthropic.

Manual generic techniques and deterministic synthesis cannot bypass this mode.
The backend rejects mixed requests. The desktop disables incompatible controls;
the web's separate manual generator directs the user to the main Build prompt.

Results carry the rule-set version, verification date, per-variant rule IDs, and
clickable official source links. History stores that metadata with the original
result. Usage IDs are **model-reported**, not proof that every semantic condition
was satisfied. Runtime checks reject unknown IDs, incomplete outputs, missing
core rules and invalid/untraceable source records, with one correction attempt.
Rule bundles are loaded only when the checkbox is on, keeping the ordinary path
independent of missing or malformed Claude rule data.

Updates are manual and date-stamped. Prompta does not claim rules stay current
forever. The original source pages should be checked again when targeting a new
Claude version. Existing user history is neither rewritten nor translated.

## Verification

`npm test` checks snapshot hashes, section references, exclusions, isolated
routing, output validation and source-link rendering. Run native UI tests with:

```sh
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 desktop/test_app.py
```
