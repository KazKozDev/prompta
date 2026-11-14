# Eval baselines

This directory holds the reports `eval/regress.ts` compares a fresh result with: `catalog.json`,
`claude.json` and so on, one per target.

- They are created and updated by a live run with the same provider and model as the one being compared:
  `node eval/regress.ts --current report.json --baseline eval/baselines/<target>.json --update`.
- Update a baseline deliberately: after improving the prompts or changing the model/judge, not to
  "silence" a red run.
- The report records `promptVersions` and `judgeVersion`: they show which prompt version produced the scores.
