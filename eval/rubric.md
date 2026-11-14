# Scoring rubric: what counts as a good prompt

Five criteria, each 1–5. **Only the prompt** is scored, regardless of whether a person
liked it. The judge is an LLM at temperature 0; the judge prompt does not see the whole catalog, only the selected
technique.

## 1. Fidelity — faithfulness to the brief

Does the prompt keep the goal, constraints and answer format from the brief.

| Score | Sign |
|---|---|
| 5 | The goal, format and all significant constraints are carried over faithfully; nothing is lost |
| 3 | The goal is there, but a constraint is lost (language, length, no-speculation rule) |
| 1 | The prompt solves a different task or loses half the requirements |

## 2. Specificity — executability

Can this prompt produce a result without follow-up questions.

| Score | Sign |
|---|---|
| 5 | Input, output format and quality criteria are there; no "do it well" wording |
| 3 | The format is there, the criteria are vague |
| 1 | "Write a good text about X" — nothing to execute |

## 3. Technique fit — match with the technique

Is the selected technique's structure recognisable: the blocks are in place, the method is not swapped for another.

| Score | Sign |
|---|---|
| 5 | The skeleton's structure is kept and the method reads clearly (CoT — steps, few-shot — examples, contextual — "material only") |
| 3 | The method can be guessed, but half the skeleton is lost |
| 1 | CoT was picked, but the prompt is a plain request; the technique is not reflected |

## 4. Config sanity — sensible settings

Do `temperature`, `top_p` and the token limit suit the task and the technique.

| Score | Sign |
|---|---|
| 5 | The numbers are explained and match the task type (extraction — 0, ensemble — high) |
| 3 | The values are safe but not explained |
| 1 | A creative temperature for classification, or a limit that cuts the answer off |

## 5. Clean output — cleanliness

Is the prompt ready to paste as is.

| Score | Sign |
|---|---|
| 5 | No `{{placeholders}}`, meta-comments, fragments in another language, or cut-off sentences |
| 3 | One placeholder or scaffolding sentence is left |
| 1 | Half the prompt is `{{...}}` or the model explaining things to itself |

## Verdict

Mean score: **≥ 4.0 — accept**, **2.5–3.9 — revise**, **< 2.5 — reject**.
The judge must explain each score in one sentence; a score without an explanation is not accepted.

## What the rubric deliberately does not measure

- Whether the technique choice was right: that is a separate metric (`expectedHit` in the report), and it cannot
  be asked of the same judge that scores the prompt — that would be self-confirmation.
- How well a model performs with the finished prompt: that needs a run on real data (`eval/execute.ts`).
