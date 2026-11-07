# Official Gemini prompting rules

Verified **2026-11-05**, scoped to the six URLs in `sources.json`.
This is not an exhaustive claim about all Google documentation.

- `snapshots/`: original official Google Markdown.
- `sources.json`: original requests, canonical URLs after verified redirects, exact authored heading anchors, timestamps, and SHA-256 hashes.
- `rules.json`: 45 recommendations; 30 active prompt-level rules. API/workflow settings are stored separately; four model-dependent or illustrative recommendations are reference-only.
- `sections.json`: all 99 scoped sections and original examples, with line references.
- `coverage.json`: scope and resolution of conflicting recommendations.
- `refresh_sources.py`: manual downloader restricted to verified Google documentation hosts. Changed sources require a fresh rule review, not automatic activation.

`ai.google.dev` currently redirects these guides to the official
`aistudio.google.com` documentation. Authored `{% id="..." %}` anchors are retained,
including sections after malformed example fences in the publisher's Markdown.

“For Gemini” is off by default and mutually exclusive with Claude and
ChatGPT. The selected generator provider/model remain unchanged. This feature
produces a prompt intended for Gemini; it does not call the Gemini service or
assume exact model versions, media inputs, grounding, or API tools are available.

The shared official-rule compiler receives only this target's active prompt rules
and the original task. Rules about temperature, reasoning configuration, schema
configuration, and thought signatures are not pasted into ordinary end-user
prompts. Generic manual techniques and deterministic synthesis cannot bypass it.

In particular, older temperature advice and fixed example dates/cutoffs are not
universal rules. Example visible-reasoning templates do not override newer
internal-thinking guidance. Precise wording and version-appropriate behavior take
priority over copying a large template.

Results include the rule-set version, date checked, per-variant model-reported
rule IDs, and clickable source links, retained in native history. Provenance is
not a claim that semantic compliance was independently verified. Invalid or
untraceable rule data blocks this mode rather than falling back to another one.

Verification: `npm test`, `npm run typecheck`, `npm run build`, and
`python3 desktop/test_app.py` with PyQt6 installed. Synthetic live checks test the
configured generator, not execution on the target Gemini service.
