import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { loadCatalog } from '../pipeline/catalog.ts';
import { runPipeline } from '../pipeline/index.ts';
import { extractJson } from '../pipeline/json.ts';
import { createLLMFromEnv } from '../pipeline/llm.ts';
import type { Provider } from '../pipeline/llm.ts';
import type { Catalog, LLM } from '../pipeline/types.ts';
import { buildJudgePrompt, parseJudgement } from './judge.ts';
import { correlate } from './stats.ts';
import type { Correlation } from './stats.ts';
import { guidanceOf, isOfficial, parseTarget, targetOptions } from './target.ts';
import type { EvalTarget } from './target.ts';

/** Проверка промпта по результату, а не по форме.
 *
 *  Пайплайн генерирует промпты (zero-shot и варианты), каждый промпт исполняется на входах с известным
 *  ответом, ответ проверяется детерминированно. Так видно, даёт ли техника или официальная цель
 *  реальный выигрыш над zero-shot, и совпадает ли с этим оценка судьи (--judge).
 *
 *  node eval/execute.ts --suite all --target catalog --provider gemini --model gemini-2.5-flash
 *  node eval/execute.ts --suite invoice-extraction --target claude --provider anthropic --model claude-opus-5-5
 */

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

export type FieldKind = 'id' | 'string' | 'text' | 'number' | 'upper';
export type Checker =
  | { type: 'json'; fields: Record<string, FieldKind> }
  | { type: 'number'; tolerance?: number }
  | { type: 'label'; labels: Record<string, string[]> };

export interface ExecExample {
  id: string;
  input: string;
  expected: unknown;
  adversarial?: boolean;
  /** Ловушка: на лёгких примерах zero-shot уже даёт 100%, различают техники только трудные. */
  hard?: boolean;
}

export interface Suite {
  id: string;
  task_type: string;
  thoughts: string;
  checker: Checker;
  examples: ExecExample[];
}

interface SuiteFile {
  suites: (Omit<Suite, 'examples'> & { examples?: ExecExample[]; from?: string; limit?: number })[];
}

/** Набор из файла; `from` подтягивает внешнюю фикстуру {examples:[{id,text,label}]}, сбалансированно по меткам. */
export function loadSuites(path = join(root, 'eval', 'data', 'exec-suites.json')): Suite[] {
  const file = JSON.parse(readFileSync(path, 'utf8')) as SuiteFile;
  return file.suites.map((s) => {
    if (!s.from) {
      if (!s.examples) throw new Error(`${s.id}: нет ни examples, ни from`);
      return s as Suite;
    }
    const ext = JSON.parse(readFileSync(join(root, s.from), 'utf8')) as { examples: { id: string; text: string; label: string }[] };
    const byLabel = new Map<string, { id: string; text: string; label: string }[]>();
    for (const e of ext.examples) byLabel.set(e.label, [...(byLabel.get(e.label) ?? []), e]);
    const per = Math.max(1, Math.floor((s.limit ?? ext.examples.length) / Math.max(1, byLabel.size)));
    const picked = [...byLabel.values()].flatMap((list) => list.slice(0, per));
    return { ...s, examples: [...picked.map((e) => ({ id: e.id, input: e.text, expected: e.label })), ...(s.examples ?? [])] } as Suite;
  });
}

/** Подставить вход в промпт: метка «ВСТАВЬ СЮДА», плейсхолдер материала или блок в конце. */
export function fillPrompt(prompt: string, input: string): string {
  const marker = /ВСТАВЬ СЮДА:[^\n]*|INSERT HERE:[^\n]*/i;
  if (marker.test(prompt)) {
    let used = false;
    return prompt.replace(new RegExp(marker.source, 'gi'), () => {
      if (used) return '';
      used = true;
      return input;
    });
  }
  const slot = /\{\{\s*(input|text|document|context|external_text|question|problem)\s*\}\}/i;
  if (slot.test(prompt)) return prompt.replace(new RegExp(slot.source, 'gi'), input);
  return `${prompt}\n\n---\nВходные данные:\n${input}`;
}

const norm = {
  id: (v: unknown) => String(v ?? '').toLowerCase().replace(/^[#№\s]+/, '').replace(/\s+/g, ''),
  string: (v: unknown) => String(v ?? '').trim().toLowerCase(),
  text: (v: unknown) => String(v ?? '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ''),
  upper: (v: unknown) => String(v ?? '').trim().toUpperCase(),
};

export function parseNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const s = String(value ?? '').replace(/[\s ]/g, '');
  const m = s.match(/-?\d+(?:[.,]\d+)*/);
  if (!m) return null;
  let t = m[0];
  // 1,250.50 → 1250.50; 15400,00 → 15400.00
  if (/,\d{3}(?:\.|$)/.test(t) && t.includes('.')) t = t.replace(/,/g, '');
  else if (/\.\d{3},/.test(t)) t = t.replace(/\./g, '').replace(',', '.');
  else t = t.replace(',', '.');
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/** Число из свободного ответа: строка «Ответ: N», иначе последнее число в последней строке с цифрой. */
export function answerNumber(answer: string): number | null {
  const tagged = [...answer.matchAll(/(?:ответ|answer)\s*[:：=]\s*\**\s*(-?[\d\s .,]+)/gi)].at(-1);
  if (tagged) return parseNumber(tagged[1]);
  const lines = answer.split('\n').filter((l) => /\d/.test(l));
  const last = lines.at(-1);
  if (!last) return null;
  const nums = [...last.replace(/(\d)[\s ](?=\d{3}\b)/g, '$1').matchAll(/-?\d+(?:[.,]\d+)?/g)];
  return nums.length ? parseNumber(nums.at(-1)![0]) : null;
}

export function answerLabel(answer: string, labels: Record<string, string[]>): string | null {
  const find = (text: string): string | null => {
    let best: { idx: number; label: string } | null = null;
    for (const [label, aliases] of Object.entries(labels)) {
      for (const a of [label, ...aliases]) {
        const idx = text.toLowerCase().lastIndexOf(a.toLowerCase());
        if (idx !== -1 && (!best || idx > best.idx)) best = { idx, label };
      }
    }
    return best?.label ?? null;
  };
  const tail = answer.trim().split('\n').filter(Boolean).at(-1) ?? '';
  return find(tail) ?? find(answer);
}

/** score — доля верного (для JSON — доля верных полей), formatValid — ответ разобран в нужном формате. */
export function check(checker: Checker, answer: string, expected: unknown): { score: number; formatValid: boolean } {
  if (checker.type === 'number') {
    const got = answerNumber(answer);
    const want = Number(expected);
    if (got === null) return { score: 0, formatValid: false };
    return { score: Math.abs(got - want) <= (checker.tolerance ?? 0.01) ? 1 : 0, formatValid: true };
  }
  if (checker.type === 'label') {
    const got = answerLabel(answer, checker.labels);
    return { score: got === expected ? 1 : 0, formatValid: got !== null };
  }
  let obj: Record<string, unknown>;
  try {
    obj = extractJson(answer, 'execute') as Record<string, unknown>;
  } catch {
    return { score: 0, formatValid: false };
  }
  const want = expected as Record<string, unknown>;
  const fields = Object.entries(checker.fields);
  let correct = 0;
  for (const [field, kind] of fields) {
    const got = obj[field];
    if (kind === 'number') {
      const n = parseNumber(got);
      if (n !== null && Math.abs(n - Number(want[field])) < 0.01) correct += 1;
    } else if (norm[kind](got) === norm[kind](want[field])) {
      correct += 1;
    }
  }
  return { score: Number((correct / fields.length).toFixed(2)), formatValid: true };
}

export interface PromptResult {
  name: string;
  prompt: string;
  accuracy: number;
  formatValid: number;
  /** Точность только на примерах с внедрённой командой; null — таких нет. */
  adversarialAccuracy: number | null;
  /** Точность только на трудных примерах; null — таких нет. */
  hardAccuracy: number | null;
  errors: number;
  /** Первая ошибка исполнителя: без неё 0% точности неотличим от «промпт плохой». */
  firstError?: string;
  judge?: number;
}

export interface SuiteResult {
  suite: string;
  target: EvalTarget;
  examples: number;
  prompts: PromptResult[];
  /** Выигрыш лучшего варианта над zero-shot по точности (доли). */
  liftOverZeroShot: number;
  promptVersion?: string;
  generationTokens?: { inputTokens: number; outputTokens: number; calls: number };
  /** Совпадает ли ранжирование судьи с ранжированием по точности. */
  judgeVsAccuracy?: Correlation;
}

export async function runSuite(opts: {
  suite: Suite;
  target: EvalTarget;
  catalog: Catalog;
  llm: LLM;
  execLLM: LLM;
  judgeLLM?: LLM;
  variants?: number;
  onProgress?: (msg: string) => void;
}): Promise<SuiteResult> {
  const { suite, target } = opts;
  const result = await runPipeline({
    thoughts: suite.thoughts,
    catalog: opts.catalog,
    llm: opts.llm,
    variants: opts.variants ?? 2,
    ...targetOptions(target),
  });
  const guidance = guidanceOf(result);
  const candidates = [
    { name: 'zero-shot', prompt: result.zeroShotPrompt ?? '', synthesis: undefined },
    { name: result.choice.key, prompt: result.synthesis.prompt, synthesis: result.synthesis, choice: result.choice },
    ...(result.alternatives ?? []).map((a, i) => ({ name: `${a.choice.key}#${i + 2}`, prompt: a.synthesis.prompt, synthesis: a.synthesis, choice: a.choice })),
  ].filter((c) => c.prompt.trim());

  const prompts: PromptResult[] = [];
  for (const c of candidates) {
    opts.onProgress?.(`${suite.id}: ${c.name}`);
    let sum = 0;
    let valid = 0;
    let errors = 0;
    let advSum = 0;
    let advN = 0;
    let hardSum = 0;
    let hardN = 0;
    let firstError: string | undefined;
    for (const ex of suite.examples) {
      let verdict = { score: 0, formatValid: false };
      try {
        verdict = check(suite.checker, await opts.execLLM(fillPrompt(c.prompt, ex.input), { temperature: 0 }), ex.expected);
      } catch (e) {
        errors += 1;
        firstError ??= e instanceof Error ? e.message : String(e);
      }
      sum += verdict.score;
      valid += verdict.formatValid ? 1 : 0;
      if (ex.adversarial) {
        advSum += verdict.score;
        advN += 1;
      }
      if (ex.hard) {
        hardSum += verdict.score;
        hardN += 1;
      }
    }
    const n = suite.examples.length || 1;
    if (errors === suite.examples.length && suite.examples.length > 0) {
      // Исполнитель не ответил ни разу — это сбой окружения, а не нулевая точность промпта.
      throw new Error(`исполнитель не ответил ни на один пример (${suite.id}, ${c.name}): ${firstError}`);
    }
    const row: PromptResult = {
      name: c.name,
      prompt: c.prompt,
      accuracy: Number((sum / n).toFixed(2)),
      formatValid: Number((valid / n).toFixed(2)),
      adversarialAccuracy: advN ? Number((advSum / advN).toFixed(2)) : null,
      hardAccuracy: hardN ? Number((hardSum / hardN).toFixed(2)) : null,
      errors,
      ...(firstError ? { firstError } : {}),
    };
    if (opts.judgeLLM && 'choice' in c && c.choice && c.synthesis) {
      try {
        const judgement = parseJudgement(await opts.judgeLLM(buildJudgePrompt({
          thoughts: suite.thoughts, brief: result.brief, choice: c.choice, synthesis: c.synthesis,
          officialRules: guidance?.rules.map(({ id, rule_text }) => ({ id, rule_text })),
        }), { temperature: 0, json: true }));
        row.judge = judgement.total;
      } catch {
        /* судья не ответил — строка остаётся без балла */
      }
    }
    prompts.push(row);
  }

  const zero = prompts.find((p) => p.name === 'zero-shot')?.accuracy ?? 0;
  const best = Math.max(...prompts.filter((p) => p.name !== 'zero-shot').map((p) => p.accuracy), zero);
  const judged = prompts.filter((p) => typeof p.judge === 'number');
  return {
    suite: suite.id,
    target,
    examples: suite.examples.length,
    prompts,
    liftOverZeroShot: Number((best - zero).toFixed(2)),
    promptVersion: result.promptVersion,
    generationTokens: result.usage,
    ...(judged.length >= 2 ? { judgeVsAccuracy: correlate(judged.map((p) => p.judge!), judged.map((p) => p.accuracy)) } : {}),
  };
}

export function formatSuiteResults(results: SuiteResult[]): string {
  const pct = (x: number | null) => (x === null ? '—' : `${Math.round(x * 100)}%`);
  const lines: string[] = [];
  for (const r of results) {
    lines.push(`${r.suite} · цель ${r.target} · ${r.examples} примеров · промпты ${r.promptVersion ?? '—'}`);
    for (const p of r.prompts) {
      lines.push(`  ${p.name.padEnd(28)} точность ${pct(p.accuracy).padStart(4)} | формат ${pct(p.formatValid).padStart(4)} | трудные ${pct(p.hardAccuracy).padStart(4)} | под инъекцией ${pct(p.adversarialAccuracy).padStart(4)}${typeof p.judge === 'number' ? ` | судья ${p.judge.toFixed(2)}` : ''}${p.errors ? ` | ошибок ${p.errors} (${(p.firstError ?? '').slice(0, 80)})` : ''}`);
    }
    lines.push(`  выигрыш лучшего варианта над zero-shot: ${r.liftOverZeroShot >= 0 ? '+' : ''}${Math.round(r.liftOverZeroShot * 100)} п.п.`);
    if (r.judgeVsAccuracy) {
      lines.push(`  судья ↔ точность: Spearman ${r.judgeVsAccuracy.spearman} (n=${r.judgeVsAccuracy.n}, ${r.judgeVsAccuracy.reliability})`);
    }
    lines.push('');
  }
  lines.push('Выигрыш меньше 1–2 примеров из набора — шум. Выводы «техника лучше» — только по нескольким прогонам.');
  return lines.join('\n');
}

function readEnvLocal(): Record<string, string> {
  const path = join(root, '.env.local');
  if (!existsSync(path)) return {};
  return Object.fromEntries(
    readFileSync(path, 'utf8').split('\n').map((l) => l.trim())
      .filter((l) => l && !l.startsWith('#') && l.includes('='))
      .map((l) => { const i = l.indexOf('='); return [l.slice(0, i).trim(), l.slice(i + 1).trim().replace(/^["']|["']$/g, '')]; }),
  );
}

async function main() {
  const argv = process.argv.slice(2);
  const flag = (name: string, def: string) => {
    const i = argv.indexOf(name);
    return i === -1 ? def : argv[i + 1];
  };
  const env = { ...readEnvLocal(), ...process.env } as Record<string, string>;
  const make = (provider: Provider, model: string) => createLLMFromEnv(provider, model, env);

  const provider = flag('--provider', 'gemini') as Provider;
  const model = flag('--model', 'gemini-2.5-flash');
  // Исполнитель по умолчанию — тот же провайдер; для сквозной проверки цели задайте провайдер цели.
  const execProvider = flag('--exec-provider', provider) as Provider;
  const execModel = flag('--exec-model', model);
  const target = parseTarget(flag('--target', 'catalog'));
  const wanted = flag('--suite', 'all');
  const suites = loadSuites().filter((s) => wanted === 'all' || wanted.split(',').includes(s.id));
  if (!suites.length) {
    console.error(`нет набора ${wanted}; есть: ${loadSuites().map((s) => s.id).join(', ')}`);
    process.exit(2);
  }
  if (isOfficial(target) && argv.includes('--deterministic')) {
    console.error('официальные цели требуют LLM-синтеза');
    process.exit(2);
  }

  const catalog = loadCatalog(JSON.parse(readFileSync(join(root, 'catalog', 'catalog.json'), 'utf8')));
  const llm = make(provider, model);
  const execLLM = execProvider === provider && execModel === model ? llm : make(execProvider, execModel);
  const judgeLLM = argv.includes('--judge') ? llm : undefined;

  const results: SuiteResult[] = [];
  for (const suite of suites) {
    results.push(await runSuite({
      suite, target, catalog, llm, execLLM, judgeLLM,
      variants: Number(flag('--variants', '2')),
      onProgress: (m) => process.stderr.write(`· ${m}\n`),
    }));
  }
  const out = flag('--out', '');
  if (out) writeFileSync(out, JSON.stringify(results, null, 2));
  console.log(argv.includes('--json') ? JSON.stringify(results, null, 2) : formatSuiteResults(results));
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
  main().catch((e) => {
    console.error('ошибка:', e instanceof Error ? e.message : e);
    process.exit(1);
  });
}
