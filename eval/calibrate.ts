import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { loadCatalog } from '../pipeline/catalog.ts';
import { runPipeline } from '../pipeline/index.ts';
import { createLLM } from '../pipeline/llm.ts';
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

/** Метка из свободного ответа модели: сначала последняя строка, иначе последнее упоминание. */
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
  // В хвосте не нашлось — смотрим весь ответ, берём последнее упоминание как итог.
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

/** Отбор сложных примеров: дешёвая модель ошибается или не даёт метку. */
export async function screenHard(
  examples: Example[],
  ask: (prompt: string) => Promise<string>,
  limit: number,
): Promise<Example[]> {
  const hard: Example[] = [];
  for (const example of examples) {
    const answer = await ask(
      `Определи тональность текста. Ответь одним словом: positive, negative или neutral.\n\nТекст: ${example.text}\nОтвет:`,
    );
    const label = parseLabel(answer);
    if (label !== example.label) hard.push(example);
    if (hard.length >= limit) break;
  }
  return hard;
}

export const CALIBRATION_BRIEF: TaskBrief = {
  goal: 'определить тональность текста: positive, negative или neutral',
  task_type: 'classification',
  input: 'короткий текст на русском языке',
  output_format: 'одно слово: positive, negative или neutral',
  constraints: ['ответ одним словом', 'без пояснений'],
  language: 'ru',
  modality: 'text',
  stakes: 'high',
  assumptions: [],
  budget_calls: 1,
};

/** Вариации брифа: один и тот же тип задачи, разная жёсткость формата. */
export const BRIEF_VARIANTS: { name: string; brief: TaskBrief }[] = [
  {
    name: 'strict',
    brief: CALIBRATION_BRIEF,
  },
  {
    name: 'minimal',
    brief: {
      ...CALIBRATION_BRIEF,
      goal: 'определить, позитивный ли текст, негативный или нейтральный',
      output_format: 'одно слово',
      constraints: [],
    },
  },
  {
    name: 'json',
    brief: {
      ...CALIBRATION_BRIEF,
      goal: 'классифицировать тональность текста',
      output_format: 'JSON {"label": "positive|negative|neutral"}',
      constraints: ['только JSON, без пояснений'],
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
    return `  ${r.techniqueKey.padEnd(24)} судья1 ${r.judge1.toFixed(2)} | судья2 ${judge2} | панель ${r.panel.toFixed(2)} | точность ${pct(r.accuracy)} (${r.correct}/${r.total})`;
  });
  return [
    `Калибровка на размеченных данных: ${report.examples} примеров, ${report.results.length} промптов`,
    '',
    ...rows,
    '',
    `Корреляция «панель ↔ точность»: Spearman ${report.correlation.spearman}, Pearson ${report.correlation.pearson} (n=${report.correlation.n}, ${report.correlation.reliability})`,
    `Лучший по точности: ${report.best.byAccuracy} | лучший по судье: ${report.best.byJudge} | ${report.best.agree ? 'совпали' : 'РАСХОДЯТСЯ'}`,
    '',
    'Что это значит: если судья ранжирует промпты так же, как реальная точность, — ему можно верить.',
    'При n<8 это пилот, а не статистика: направление, а не приговор.',
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
  // Исполнение промптов можно вынести на быструю модель: генерация и судьи остаются в облаке.
  const execProvider = flag('--exec-provider', '') as Provider | '';
  const execModel = flag('--exec-model', '');
  const judge2Provider = flag('--judge2-provider', '') as Provider | '';
  const judge2Model = flag('--judge2-model', '');

  const data = JSON.parse(readFileSync(join(root, 'eval', 'data', 'sentiment-ru.json'), 'utf8')) as { examples: Example[] };
  const examples = data.examples.slice(0, limit);
  const catalog = loadCatalog(JSON.parse(readFileSync(join(root, 'catalog', 'catalog.json'), 'utf8')));

  const env = { ...readEnvLocal(), ...process.env } as Record<string, string>;
  const keyFor = (p: Provider) => (p === 'gemini' ? env.GEMINI_API_KEY : p === 'openai' ? env.OPENAI_API_KEY : undefined);
  const llm = createLLM({ provider, model, apiKey: keyFor(provider) });
  const judge2LLM = judge2Provider ? createLLM({ provider: judge2Provider, model: judge2Model, apiKey: keyFor(judge2Provider) }) : null;
  const execLLM = execProvider
    ? createLLM({ provider: execProvider, model: execModel || model, apiKey: keyFor(execProvider) })
    : llm;
  if (execProvider) process.stderr.write(`исполнение промптов: ${execProvider}/${execModel || model}\n`);

  let pool = examples;
  if (hard) {
    process.stderr.write(`· отбор сложных примеров через ${provider}/${screenModel} (до ${examples.length}) … `);
    const screenLLM = createLLM({ provider, model: screenModel, apiKey: keyFor(provider) });
    pool = await screenHard(examples, (p) => screenLLM(p, { temperature: 0 }), hardLimit);
    process.stderr.write(`осталось ${pool.length}\n`);
    if (pool.length < 3) {
      process.stderr.write('слишком мало сложных примеров — задача слишком лёгкая для калибровки\n');
    }
  }

  const results: TechniqueResult[] = [];

  const combos = techniques.flatMap((tech) =>
    BRIEF_VARIANTS.slice(0, variants).map((v) => ({ tech, variant: v })),
  );

  for (const { tech: techniqueKey, variant } of combos) {
    const label = variants > 1 ? `${techniqueKey}/${variant.name}` : techniqueKey;
    process.stderr.write(`· ${label}: генерация промпта … `);
    const run = await runPipeline({ thoughts: 'калибровка', catalog, llm, brief: variant.brief, techniqueKey });
    const prompt = run.synthesis.prompt;

    const judgePrompt = buildJudgePrompt({
      thoughts: 'определить тональность коротких русских текстов',
      brief: variant.brief,
      choice: run.choice,
      synthesis: run.synthesis,
    });
    const judged1 = parseJudgement(await llm(judgePrompt, { temperature: 0 }));
    const judged2 = judge2LLM ? parseJudgement(await judge2LLM(judgePrompt, { temperature: 0 })) : null;
    process.stderr.write('оценён, прогон примеров … ');

    let correct = 0;
    let errors = 0;
    for (const example of pool) {
      try {
        const answer = await execLLM(`${prompt}\n\nТекст: ${example.text}\nОтвет:`, { temperature: 0 });
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
    process.stderr.write(`точность ${correct}/${pool.length}\n`);
  }

  const report = buildCalibrationReport(results, pool.length);
  console.log(argv.includes('--json') ? JSON.stringify(report, null, 2) : formatCalibration(report));
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;

if (isMain) {
  main().catch((e) => {
    console.error('ошибка:', e instanceof Error ? e.message : e);
    process.exit(1);
  });
}
