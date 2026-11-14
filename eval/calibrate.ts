import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { loadCatalog } from '../pipeline/catalog.ts';
import { runPipeline } from '../pipeline/index.ts';
import { createLLMFromEnv } from '../pipeline/llm.ts';
import type { Provider } from '../pipeline/llm.ts';
import type { TaskBrief } from '../pipeline/types.ts';
import { buildJudgePrompt, parseJudgement } from './judge.ts';
import type { Judgement } from './judge.ts';
import { correlate } from './stats.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

export type Label = 'positive' | 'negative' | 'neutral';

export interface Example {
  id: string;
  text: string;
  label: Label;
}

/** The label from a free-form model answer: the last line first, else the last mention. */
export function parseLabel(answer: string): Label | null {
  const patterns: [RegExp, Label][] = [
    [/positi|положит|позитив/i, 'positive'],
    [/negati|отрицат|негатив/i, 'negative'],
    [/neutral|нейтрал/i, 'neutral'],
  ];
  const scan = (text: string, strategy: 'first' | 'last'): Label | null => {
    let best: { idx: number; label: Label } | null = null;
    for (const [re, label] of patterns) {
      const m = text.match(re);
      if (!m || m.index === undefined) continue;
      const idx = strategy === 'first' ? m.index : text.length - m.index;
      if (!best || (strategy === 'first' ? idx < best.idx : idx < best.idx)) best = { idx, label };
    }
    return best?.label ?? null;
  };

  const lines = answer.trim().split('\n').map((l) => l.trim()).filter(Boolean);
  const tail = lines.slice(-1)[0] ?? '';
  const fromTail = scan(tail, 'first');
  if (fromTail) return fromTail;
  // Not found at the end: scan the whole answer and take the last mention as the result.
  const reversed = [...patterns].reverse();
  let last: { idx: number; label: Label } | null = null;
  for (const [re, label] of reversed) {
    const matches = [...answer.matchAll(new RegExp(re.source, 'gi'))];
    const m = matches.at(-1);
    if (!m || m.index === undefined) continue;
    if (!last || m.index > last.idx) last = { idx: m.index, label };
  }
  return last?.label ?? null;
}

/** Picking hard examples: a cheap model gets them wrong or gives no label. */
export async function screenHard(
  examples: Example[],
  ask: (prompt: string) => Promise<string>,
  limit: number,
): Promise<Example[]> {
  const hard: Example[] = [];
  for (const example of examples) {
    const answer = await ask(
      `Determine the sentiment of the text. Answer with one word: positive, negative or neutral.\n\nText: ${example.text}\nAnswer:`,
    );
    const label = parseLabel(answer);
    if (label !== example.label) hard.push(example);
    if (hard.length >= limit) break;
  }
  return hard;
}

export const CALIBRATION_BRIEF: TaskBrief = {
  goal: 'determine the sentiment of the text: positive, negative or neutral',
  task_type: 'classification',
  input: 'a short text in Russian',
  output_format: 'one word: positive, negative or neutral',
  constraints: ['a one-word answer', 'no explanations'],
  language: 'ru',
  modality: 'text',
  stakes: 'high',
  assumptions: [],
  budget_calls: 1,
};

/** Brief variations: the same task type, different format strictness. */
export const BRIEF_VARIANTS: { name: string; brief: TaskBrief }[] = [
  {
    name: 'strict',
    brief: CALIBRATION_BRIEF,
  },
  {
    name: 'minimal',
    brief: {
      ...CALIBRATION_BRIEF,
      goal: 'determine whether the text is positive, negative or neutral',
      output_format: 'one word',
      constraints: [],
    },
  },
  {
    name: 'json',
    brief: {
      ...CALIBRATION_BRIEF,
      goal: 'classify the sentiment of the text',
      output_format: 'JSON {"label": "positive|negative|neutral"}',
      constraints: ['JSON only, no explanations'],
    },
  },
];

export interface TechniqueResult {
  techniqueKey: string;
  judge1: number;
  judge2: number | null;
  panel: number;
  accuracy: number;
  correct: number;
  total: number;
  errors: number;
  judged1: Judgement;
  judged2: Judgement | null;
}

export interface CalibrationReport {
  examples: number;
  results: TechniqueResult[];
  correlation: ReturnType<typeof correlate>;
  best: { byAccuracy: string; byJudge: string; agree: boolean };
}

export function buildCalibrationReport(results: TechniqueResult[], examples: number): CalibrationReport {
  const corr = correlate(
    results.map((r) => r.panel),
    results.map((r) => r.accuracy),
  );
  const byAccuracy = [...results].sort((a, b) => b.accuracy - a.accuracy)[0];
  const byJudge = [...results].sort((a, b) => b.panel - a.panel)[0];
  return {
    examples,
    results,
    correlation: corr,
    best: {
      byAccuracy: byAccuracy?.techniqueKey ?? '—',
      byJudge: byJudge?.techniqueKey ?? '—',
      agree: byAccuracy?.techniqueKey === byJudge?.techniqueKey,
    },
  };
}

export function formatCalibration(report: CalibrationReport): string {
  const pct = (x: number) => `${Math.round(x * 100)}%`;
  const rows = report.results.map((r) => {
    const judge2 = r.judge2 === null ? '  — ' : r.judge2.toFixed(2);
    return `  ${r.techniqueKey.padEnd(24)} judge1 ${r.judge1.toFixed(2)} | judge2 ${judge2} | panel ${r.panel.toFixed(2)} | accuracy ${pct(r.accuracy)} (${r.correct}/${r.total})`;
  });
  return [
    `Calibration on labelled data: ${report.examples} examples, ${report.results.length} prompts`,
    '',
    ...rows,
    '',
    `Correlation "panel ↔ accuracy": Spearman ${report.correlation.spearman}, Pearson ${report.correlation.pearson} (n=${report.correlation.n}, ${report.correlation.reliability})`,
    `Best by accuracy: ${report.best.byAccuracy} | best by judge: ${report.best.byJudge} | ${report.best.agree ? 'agree' : 'DISAGREE'}`,
    '',
    'What it means: if the judge ranks prompts the same way as real accuracy does, it can be trusted.',
    'With n<8 this is a pilot, not statistics: a direction, not a verdict.',
  ].join('\n');
}

function readEnvLocal(): Record<string, string> {
  const path = join(root, '.env.local');
  if (!existsSync(path)) return {};
  return Object.fromEntries(
    readFileSync(path, 'utf8')
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith('#') && l.includes('='))
      .map((l) => {
        const i = l.indexOf('=');
        return [l.slice(0, i).trim(), l.slice(i + 1).trim().replace(/^["']|["']$/g, '')];
      }),
  );
}

async function main() {
  const argv = process.argv.slice(2);
  const flag = (name: string, def: string) => {
    const i = argv.indexOf(name);
    return i === -1 ? def : argv[i + 1];
  };

  const techniques = flag('--techniques', 'zero_shot,few_shot,system_prompting,chain_of_thought').split(',').map((s) => s.trim());
  const limit = Number(flag('--examples', '18'));
  const provider = flag('--provider', 'ollama') as Provider;
  const model = flag('--model', 'glm-5.3:cloud');
  const hard = argv.includes('--hard');
  const variants = Math.max(1, Number(flag('--variants', '1')));
  const screenModel = flag('--screen-model', 'qwen3:8b');
  const hardLimit = Math.max(3, Number(flag('--hard-limit', '10')));
  // Prompt execution can move to a fast model: generation and judges stay in the cloud.
  const execProvider = flag('--exec-provider', '') as Provider | '';
  const execModel = flag('--exec-model', '');
  const judge2Provider = flag('--judge2-provider', '') as Provider | '';
  const judge2Model = flag('--judge2-model', '');

  const data = JSON.parse(readFileSync(join(root, 'eval', 'data', 'sentiment-ru.json'), 'utf8')) as { examples: Example[] };
  const examples = data.examples.slice(0, limit);
  const catalog = loadCatalog(JSON.parse(readFileSync(join(root, 'catalog', 'catalog.json'), 'utf8')));

  const env = { ...readEnvLocal(), ...process.env } as Record<string, string>;
  const llm = createLLMFromEnv(provider, model, env);
  const judge2LLM = judge2Provider ? createLLMFromEnv(judge2Provider, judge2Model, env) : null;
  const execLLM = execProvider
    ? createLLMFromEnv(execProvider, execModel || model, env)
    : llm;
  if (execProvider) process.stderr.write(`prompt execution: ${execProvider}/${execModel || model}\n`);

  let pool = examples;
  if (hard) {
    process.stderr.write(`· picking hard examples with ${provider}/${screenModel} (up to ${examples.length}) … `);
    const screenLLM = createLLMFromEnv(provider, screenModel, env);
    pool = await screenHard(examples, (p) => screenLLM(p, { temperature: 0 }), hardLimit);
    process.stderr.write(`${pool.length} left\n`);
    if (pool.length < 3) {
      process.stderr.write('too few hard examples — the task is too easy for calibration\n');
    }
  }

  const results: TechniqueResult[] = [];

  const combos = techniques.flatMap((tech) =>
    BRIEF_VARIANTS.slice(0, variants).map((v) => ({ tech, variant: v })),
  );

  for (const { tech: techniqueKey, variant } of combos) {
    const label = variants > 1 ? `${techniqueKey}/${variant.name}` : techniqueKey;
    process.stderr.write(`· ${label}: generating the prompt … `);
    const run = await runPipeline({ thoughts: 'calibration', catalog, llm, brief: variant.brief, techniqueKey });
    const prompt = run.synthesis.prompt;

    const judgePrompt = buildJudgePrompt({
      thoughts: 'determine the sentiment of short Russian texts',
      brief: variant.brief,
      choice: run.choice,
      synthesis: run.synthesis,
    });
    const judged1 = parseJudgement(await llm(judgePrompt, { temperature: 0 }));
    const judged2 = judge2LLM ? parseJudgement(await judge2LLM(judgePrompt, { temperature: 0 })) : null;
    process.stderr.write('scored, running the examples … ');

    let correct = 0;
    let errors = 0;
    for (const example of pool) {
      try {
        const answer = await execLLM(`${prompt}\n\nText: ${example.text}\nAnswer:`, { temperature: 0 });
        const label = parseLabel(answer);
        if (label === null) errors += 1;
        else if (label === example.label) correct += 1;
      } catch {
        errors += 1;
      }
    }

    const panel = judged2 ? (judged1.total + judged2.total) / 2 : judged1.total;
    results.push({
      techniqueKey: label,
      judge1: judged1.total,
      judge2: judged2 ? judged2.total : null,
      panel: Number(panel.toFixed(2)),
      accuracy: Number((correct / pool.length).toFixed(2)),
      correct,
      total: pool.length,
      errors,
      judged1,
      judged2,
    });
    process.stderr.write(`accuracy ${correct}/${pool.length}\n`);
  }

  const report = buildCalibrationReport(results, pool.length);
  console.log(argv.includes('--json') ? JSON.stringify(report, null, 2) : formatCalibration(report));
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;

if (isMain) {
  main().catch((e) => {
    console.error('error:', e instanceof Error ? e.message : e);
    process.exit(1);
  });
}
