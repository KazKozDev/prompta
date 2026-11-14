# eval — measuring prompt quality and selection stability

Without this suite, "a good prompt" is a matter of taste. It has 28 tasks (10 of them adversarial, with injected
commands), a 5-criterion rubric, a judge, reference suites for checking by result, and a regression gate.

## New (November 2026)

```bash
node eval/run.ts --target claude --ids invoice-fields,inj-doc-qa --repeat 3 --provider anthropic --model claude-opus-5-5 --out report.json
node eval/execute.ts --suite all --target catalog --provider ollama --model qwen3:8b [--exec-provider anthropic --exec-model claude-opus-5-5] [--judge]
node eval/regress.ts --current report.json --baseline eval/baselines/claude.json [--update]
```

| What | Where |
|---|---|
| `--target catalog\|claude\|chatgpt\|gemini\|grok\|open:<id>` — which generation mode is measured; for official targets the judge checks the prompt against the rules the generator cited, and technique-selection metrics are not computed | `run.ts`, `target.ts` |
| `taskTypeHit`, `scoreCI95` (half-width of the 95% interval), `cost` (generation tokens), `promptVersions`, `judgeVersion` | `aggregate.ts` |
| Adversarial tasks (`adversarial: true`): `injectionHit` — the generator executed the injected command, `guardHit` — the prompt has the "material is data" rule | `tasks.json`, `aggregate.ts` |
| Running prompts on reference suites: invoice fields to JSON, word problems, sentiment; accuracy, accuracy under injection, lift over zero-shot, judge-vs-accuracy correlation | `execute.ts`, `data/exec-suites.json` |
| Regression gate: a score drop beyond max(0.5, combined 95% interval), growth of forbidden techniques, injections, failures | `regress.ts`, `baselines/` |

```bash
npm test                                                     # offline, no keys
node eval/run.ts --ids meeting-actions,tickets-classify --repeat 3 --provider ollama --model glm-5.3:cloud
node eval/run.ts --tasks 5 --repeat 2 --provider gemini --model gemini-2.5-flash
node eval/run.ts --json > report.json                        # raw records for analysis

# crosscheck two judges from different families (required for any conclusion)
node eval/run.ts --ids meeting-actions,tickets-classify --provider ollama --model glm-5.3:cloud \
  --judge2-provider ollama --judge2-model deepseek-v4-pro:cloud
```

## What's inside

| File | Role |
|---|---|
| `crosscheck.ts` | Two-judge crosscheck: gap, per-criterion bias, trust verdict |
| `calibrate.ts` | Judge calibration on labelled data: accuracy versus score |
| `stats.ts` | Pearson / Spearman with no dependencies |
| `fetch.ts` | One-off download of the Hugging Face fixture into `eval/data/` |
| `tasks.json` | Tasks: a raw stream of thoughts + expected type, allowed and forbidden techniques, expected wording |
| `rubric.md` | 5 criteria with 1/3/5 anchors and verdict thresholds |
| `judge.ts` | Judge prompt and score parser (a score without an explanation is rejected) |
| `aggregate.ts` | Per-task and per-technique metrics, text report |
| `run.ts` | CLI: pipeline run → scoring → report |

## Metrics

| Metric | Meaning | What it tells you |
|---|---|---|
| `meanScore` | Mean rubric score (1–5) | Overall prompt quality |
| `stability` | Share of runs where the most frequent technique was picked | **Selection drift**. Always 100% at `--repeat 1`: measure from 3 runs |
| `expectedHit` | Share of runs where a technique from `any_of` was picked | Whether the choice lands in a sensible range |
| `forbiddenHit` | Share of runs where a technique from `forbidden` was picked | Gross selection errors; should be 0 |
| `mentionHit` | Whether the prompt has the expected wording (`must_mention`) | A cheap check that the prompt is about the task |
| `failures` | Failed runs | Parsing and validation errors |
| `crossCheck` | Agreement of two judges: `meanAbsDelta`, `verdictAgreement`, `biasPerCriterion`, `pearson` | Whether a single judge's scores can be trusted |
| `panel` | Per-judge means and the panel mean | The only number worth comparing between runs |

## First live run (2 tasks, Ollama glm-5.3, offline synthesis)

```
meeting-actions    3.40  contextual_prompting   expected 100%  forbidden 0%
tickets-classify   2.40  system_prompting       expected 100%  forbidden 0%
```

Both choices "hit" the expected list, but the second got `reject`: for a simple classification
`system_prompting` was picked instead of the cheap `zero_shot`/`verbalizer`, and the judge took points off
`technique_fit` and `clean_output` (an English skeleton in a Russian prompt). That is exactly the signal
eyeballing did not give.

## Calibration on labelled data (Hugging Face)

The judge scores a prompt by the rubric, but nobody had checked that **a high score = a working prompt**.
Calibration answers this directly: take labelled data, run prompts of different techniques on it,
and see whether the "by judge" order matches the "by accuracy" order.

Data: [sy-volkov/russian-sentiment-analysis-dataset](https://huggingface.co/datasets/sy-volkov/russian-sentiment-analysis-dataset)
(3 sentiment classes, Russian). The fixture is balanced at 6 examples per class and lives in
`eval/data/sentiment-ru.json`; the runtime is offline, and `fetch.ts` is only needed to refresh it.

```bash
node eval/fetch.ts                     # refresh the fixture (18 examples)
node eval/calibrate.ts --techniques zero_shot,few_shot,system_prompting --examples 12 \
  --provider ollama --model glm-5.3:cloud \
  --judge2-provider ollama --judge2-model deepseek-v4-pro:cloud
```

Metrics: accuracy on the labelled examples, the judges' panel score, and the correlation between them
(Spearman, because monotonicity matters, not linearity).

### Result: saturation first, then discrimination

**Full set (18 examples)**: every technique got the same accuracy, nothing to calibrate:

```
zero_shot          panel 4.10 | 92% (11/12)
few_shot           panel 3.80 | 92% (11/12)
system_prompting   panel 3.90 | 92% (11/12)
Spearman 0, Pearson 0 — ceiling, nothing to discriminate
```

**Hard examples only** (`--hard`: the cheap `qwen3:8b` gets them wrong; 6 of 18 left):

```
zero_shot          panel 3.60 | 33% (2/6)
few_shot           panel 3.50 | 17% (1/6)
system_prompting   panel 3.90 | 33% (2/6)
Spearman 0.87, Pearson 0.69 (n=3, pilot)
Best by accuracy: zero_shot | best by judge: system_prompting — DISAGREE
```

**How to read it.** A rank correlation of 0.87 looks encouraging, but it rests on a single
agreement: `few_shot` is worst both by accuracy and by judge. Where accuracy ties (2/6 and 2/6),
the judge picks `system_prompting`, i.e. it **scores the prompt's form, not its effectiveness**.
The conclusion is cautious: the judge is not useless (it catches gross errors), but it does not replace a run on data.

### Why not `agentlans/prompt-quality`

A dataset with human ratings of prompt quality exists and looks tempting
(`prompt`, `quality`, ratings from eight models), but our judge's rubric needs the task's **brief**:
the `fidelity` and `technique_fit` criteria are undefined without it. Comparing our score with an abstract
"prompt quality" would measure a different construct. So we calibrate on objective accuracy,
not on subjective ratings.

## Two-judge crosscheck (3 tasks, glm-5.3 vs deepseek-v4-pro, Ollama cloud)

```
meeting-actions    4.40   system_prompting
tickets-classify   3.00   system_prompting
math-word-problem  3.80   chain_of_thought

Crosscheck: DO NOT TRUST
  score gap: mean 0.6, max 1.0
  verdict agreement: 0% | total correlation: 0.86
  bias: fidelity −0.67, specificity −1.00, technique_fit −0.33, clean_output −0.33
```

The main finding: the judges **rank alike** (correlation 0.86) but **score at different levels**:
the second judge is systematically stricter on `fidelity` and `specificity`, and all three verdicts differed.
So any single score ("3.4 — revise") is a property of the judge, not of the prompt.

Practical rule: compare only the **panel mean** (`panel.panelMean`) and make no
decisions on a difference under 1 point.

## Drift measurement (one task, 3 repeats)

```
tickets-classify  #1 system_prompting 2.0
tickets-classify  #2 system_prompting 2.8
tickets-classify  #3 system_prompting 3.4
selection stability: 100%
```

There was no drift, but something else showed: **the judge is noisy**, with a 1.4-point spread on the same task.
So a single run cannot be compared with another single run: only means over 3+ repeats.

## Full run: 18 tasks × 3 repeats (llama3.2:3b, offline synthesis)

```
Runs: 54, failures: 0
Mean score: 4.21 | selection stability: 98%
Expected technique hit: 17% | forbidden techniques: 17%
Expected wording in the prompt: 72%
```

**What each number means.**

- **0 failures**: after strict JSON mode, parse retries and normalisation
  (`modality: "текст"`, `stakes: "средний"`) the pipeline does not fail on the weak model at all.
- **98% stability**: the technique choice is reproducible; drift only on `agent-research` (67%).
- **17% hit**: on a 3B model the choice barely matches the expected one: it systematically picks
  `least_to_most` (22 runs) and `zero_shot` (18). That is a model limitation, not a catalog one: on
  `glm-5.3` the same catalog gave meaningful hits.
- **17% forbidden**: `zero_shot` was picked for `docs-qa`, `contract-clauses` and `long-context-summary`,
  where the technique is explicitly marked "not suitable": the model ignores `when_not`. This is the main open
  selection defect.
- **4.21 score**: the judge is the same 3B model, so it is inflated (see the two-judge crosscheck above).

## Weak models

The run on `llama3.2:3b` first gave **54 failures out of 54**: the model answered in prose instead of JSON. That
exposed two holes, both closed:

1. **Strict JSON mode.** For the "brief", "selection" and "judge" stages the adapter now passes
   `format: "json"` (Ollama), `responseMimeType` (Gemini) and `response_format` (OpenAI).
2. **Tolerant score parsing.** A judge answering `{"fidelity": 4}` without a reason has the score accepted
   but marked `degraded: true`. A score object without `why` is still an error.

Without these fixes eval on weak models measured not prompt quality but the model's inability to keep to JSON.

## Honest limits

- **The judge is the same model.** Self-bias is measured: see the crosscheck above, 100% verdict disagreement.
  A second judge is implemented (`--judge2-provider/--judge2-model`), but there is no calibration between them:
  the panel mean is a compromise, not the truth.
- **Judge correlation is meaningful from 3 runs.** With 1–2 runs `pearson` degenerates (0 or 1 by
  construction): look only at `meanAbsDelta` and `biasPerCriterion`.
- **Calibration is a pilot at n=3** on six hard examples: a direction, not a verdict.
- **Easy-task ceiling.** On the full set everyone gets 92% accuracy; such a set discriminates nothing.
  Calibration needs deliberately hard examples (`--hard`) or tasks with a checkable format.
- **The task set is small** for statistics: it is for regressions, not for "technique X beats Y" conclusions.
- **`must_mention` is a heuristic.** It checks wording, not meaning; false positives are possible.
- **`stability` is meaningless on one run**: measuring drift needs `--repeat 3`.
- **Offline mode** mixes the English skeleton with Russian text and so lowers `clean_output`;
  compare techniques with each other within one mode.

## Adding a task

Add an object to `tasks.json`; `npm test` checks that `task_type` exists and that every key in
`any_of`/`forbidden` is in the catalog and the two do not overlap. Take the expected technique
from the catalog's `task_types`, not from memory. Task `thoughts` and `must_mention` are Russian on purpose:
they are the test inputs.
