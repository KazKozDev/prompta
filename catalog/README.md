# catalog.json — machine-readable catalog of techniques

The foundation of the "stream of thoughts → prompt" pipeline. Built from
[`../archive-org-prompting/techniques-map.md`](../archive-org-prompting/techniques-map.md), so
every entry can be traced to a page of the primary source.

```bash
python3 catalog/validate.py        # check structure and completeness
```

## What's inside

| | Count |
|---|---|
| Total entries | 90 (catalog version 0.2.0) |
| `status: "ready"` — has a synthesis template, "when not to use" and a config | 64 |
| `status: "procedure"` — not a prompt but a procedure: execution steps instead of a template | 19 |
| `status: "index-only"` — settings and risks, cannot be a prompt | 7 |
| Taxonomy categories | 16 |

The split is deliberate and exhaustive — no "stubs" are left:

- **64 `ready`**: have a template, "when not to use" and a config; synthesis is possible.
- **19 `procedure`**: not a prompt but a procedure over data or the model (KNN selection, RL optimisers, DSPy,
  ensembles). Instead of a template they have `procedure`: a list of steps that can be carried out or shown.
- **7 `index-only`**: 3 generation settings (temperature, top-k/top-p, output length) and 4 security
  risks (injection, jailbreak, prompt leaking, hallucinated packages). They cannot be a prompt
  by nature and should not pretend to be a template.

**Selection** sees the whole catalog, **synthesis** only `ready`, **procedures** are shown as steps.

## Technique sources (`source-links.json`)

A technique's first source is its original paper on [arXiv](https://arxiv.org) (83 of 90 entries,
ids and titles checked against the arXiv API on 2026-11-07), followed by the archive.org documents and The Prompt Report.
7 entries have no paper of their own — output length, contextual prompting, three pedagogical types (closed, open,
reflective), the regex extractor and separate LLM; they keep their earlier sources.

## Primary-source excerpts (`source-excerpts.ts`)

`python3 catalog/build_excerpts.py` collects, for every technique, a passage of its primary source from
`archive-org-prompting/md` (by the pages in `source_ref`) and the original arXiv paper from `source-links.json`.
These passages are quoted in every synthesis request (`pipeline/sources.ts`), including zero-shot (Variant 0):
the model writes the prompt from the method itself, not only from the catalog's summary of it. Rerun the script
after editing the catalog or the sources.

## Entry schema

| Field | Type | Purpose |
|---|---|---|
| `key` | string | Stable identifier, Latin letters. Used in the API and logs |
| `name` | string | Human-readable name from the map |
| `kind` | enum | `technique` \| `setting` \| `prompt_type` \| `risk` |
| `category` | enum | Taxonomy section (16 values) |
| `task_types` | string[] | Task types the technique suits. Empty — no restrictions |
| `task_types_source` | enum | `explicit` (set by hand) \| `category-default` (inferred from the category) |
| `execution` | enum | `single_call` \| `multi_step` \| `n_calls_vote` \| `tool_loop` \| `optimizer_loop` \| `postprocess` \| `none` |
| `when_to_use` | string | From the map. The basis for choosing the technique |
| `when_not` | string \| null | When the technique hurts. Filled in for `ready` |
| `cost_calls` | int \| string | Estimated number of LLM calls (`1`, `"5–10"`, `0`) |
| `config` | object | `temperature`, `top_p`, `max_tokens_hint`, `rationale` |
| `template` | string \| null | Prompt skeleton with `{{...}}` placeholders. Only for `ready` |
| `example` | string | Example from the primary source |
| `source_ref` | string | `whitepaper, p. 29–32` or `§2.2.3, p. 13` |
| `source_docs` | string[] | Document IDs from `../archive-org-prompting/md/` |
| `related` | string[] | Neighbouring techniques: for "show an alternative" |
| `status` | enum | `ready` \| `procedure` \| `index-only` |

## Config policy

`temperature` in the catalog is **a starting recommendation, not the truth**: the value is derived from the technique's
type and backed by `rationale`.

| Category | temp | Why |
|---|---|---|
| `answer_engineering` | 0.0 | Extraction must be deterministic |
| `agents`, `rag` | 0.1 | Actions and citations must not be "creative" |
| `context`, `reasoning`, `decomposition`, `self_critique`, `icl` | 0.2 | Stability matters more than variety |
| `zero_shot_boost`, `automation` | 0.3 | The wording changes, not the content |
| `pedagogy` | 0.5 | Questions should vary |
| `ensembling`, `optimization` | 0.7 | Ensembles and search live only on variety |
| `generation_config`, `security` | `null` | Temperature is either the setting itself or does not apply |

## How the pipeline uses it

1. **Selection.** The model gets the brief + a compact projection of the catalog (`key`, `name`, `category`,
   `when_to_use`, `when_not`, `cost_calls`) and returns a `key` + reason + confidence.
   Mandatory rule: the cheapest technique that covers the brief.
2. **Synthesis.** The selected technique's `template` is taken and its placeholders filled from the brief; `example`
   serves as a few-shot hint about quality; `config` is carried over into the recommendations to the user.
3. **Check.** `when_not` + the rubric give the critic material: if the brief falls into `when_not`,
   the choice is rejected before generation.

## Known gaps (next data steps)

- `task_types` are filled in: 25 entries by hand, 64 inferred from the category, 8 (settings and risks) without
  types. The inferred ones have not been checked on real tasks: eval should show where the category is wrong.
- The 7 `index-only` entries are 3 generation settings and 4 security risks (not prompts by nature); they cannot be synthesised, only recommended.
- No `language`/`modality` — when multimodality is added the schema expands
  (`modality: ["text", "image"]`), and entries without the needed modality are filtered out at selection.
- The scoring rubric lives with the eval suite (`eval/rubric.md`).

## How to rebuild

The catalog is generated by a script from the map, not edited by hand:

```bash
python3 catalog/build_catalog.py   # rebuild catalog.json from techniques-map.md
python3 catalog/build_excerpts.py  # rebuild source-excerpts.ts and the source summaries
python3 catalog/validate.py        # check the structure
npm test                           # pipeline invariants
```

`when_to_use`, `example` and `source_ref` come from `techniques-map.md`; `template`, `procedure`,
`when_not`, `related` and `execution` are set in `build_catalog.py`. After editing the map, regenerate the catalog,
or they will drift apart. The English UI names and short hints live in `display.en.ts`.
