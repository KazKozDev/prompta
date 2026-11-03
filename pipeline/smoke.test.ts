import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import type { Catalog, TaskBrief, Technique } from './types.ts';
import { PipelineError } from './types.ts';
import { costRange, gateTechniques, loadCatalog, projectForSelection } from './catalog.ts';
import { parseBrief } from './brief.ts';
import { parseChoice } from './select.ts';
import { fillTemplate, maxTokensFor, synthesizeDeterministic, synthesizeWithLLM } from './synthesize.ts';
import { runPipeline } from './index.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const catalog: Catalog = loadCatalog(JSON.parse(readFileSync(join(root, 'catalog', 'catalog.json'), 'utf8')));

function tech(key: string, over: Partial<Technique> = {}): Technique {
  return {
    key,
    name: key,
    kind: 'technique',
    category: 'reasoning',
    execution: 'single_call',
    when_to_use: 'тестовая техника',
    when_not: null,
    cost_calls: 1,
    config: { temperature: 0.2, top_p: 0.95, rationale: 'тест' },
    template: '{{task}}',
    example: 'пример',
    source_ref: 'тест',
    source_docs: ['d'],
    related: [],
    status: 'ready',
    ...over,
  };
}

const brief: TaskBrief = {
  goal: 'классифицировать отзывы на позитивные и негативные',
  task_type: 'classification',
  input: 'текст отзыва',
  output_format: 'JSON {"label": "positive|negative"}',
  constraints: ['без выдумок'],
  language: 'ru',
  modality: 'text',
  stakes: 'medium',
  assumptions: ['метки фиксированы'],
  budget_calls: null,
};

const BRIEF_JSON = JSON.stringify({
  goal: brief.goal,
  task_type: 'classification',
  input: brief.input,
  output_format: brief.output_format,
  constraints: brief.constraints,
  language: 'ru',
  modality: 'text',
  stakes: 'medium',
  assumptions: ['метки фиксированы'],
  budget_calls: null,
});

function fakeLLM(replies: { brief?: string; choice?: string; prompt?: string } = {}) {
  const calls: string[] = [];
  const llm = async (prompt: string) => {
    calls.push(prompt);
    if (prompt.includes('Поток мыслей:')) return replies.brief ?? '```json\n' + BRIEF_JSON + '\n```';
    if (prompt.includes('Доступные техники')) {
      return replies.choice ?? JSON.stringify({ key: 'zero_shot', reason: 'задача простая', confidence: 0.9, whyNotCheaper: 'взял самую дешёвую' });
    }
    return replies.prompt ?? 'Готовый промпт, собранный моделью по каркасу техники, длиной достаточно для проверки.';
  };
  return { llm, calls };
}

test('каталог: 89 записей, все техники синтезируемы, ключи уникальны', () => {
  assert.equal(catalog.techniques.length, 89);
  assert.equal(new Set(catalog.techniques.map((t) => t.key)).size, 89);

  const ready = catalog.techniques.filter((t) => t.status === 'ready');
  const procedures = catalog.techniques.filter((t) => t.status === 'procedure');
  const leftovers = catalog.techniques.filter((t) => t.status === 'index-only');

  assert.ok(ready.length >= 60, `готовых техник мало: ${ready.length}`);
  assert.ok(procedures.length >= 15, `процедур мало: ${procedures.length}`);
  // index-only остаются только настройки и риски — они не промпты по своей природе
  for (const t of leftovers) {
    assert.ok(['setting', 'risk'].includes(t.kind), `${t.key}: незаполненная техника`);
  }
  for (const t of procedures) {
    assert.ok(Array.isArray(t.procedure) && t.procedure.length > 0, `${t.key}: процедура без шагов`);
  }
});

test('loadCatalog отвергает дубль ключа', () => {
  assert.throws(() => loadCatalog({ version: 'x', techniques: [tech('a'), tech('a')] }), PipelineError);
});

test('проекция для выбора короче полного каталога и содержит цену', () => {
  const ready = catalog.techniques.filter((t) => t.status === 'ready');
  const projected = projectForSelection(ready);
  assert.ok(projected.length < JSON.stringify(ready).length, 'проекция должна быть компактнее');
  assert.match(projected, /вызовов/);
});

test('отсев убирает настройки, риски и index-only записи', () => {
  const { candidates, rejected } = gateTechniques(brief, catalog);
  const keys = candidates.map((c) => c.key);
  assert.ok(!keys.includes('temperature'), 'настройка не должна попадать в выбор');
  assert.ok(!keys.includes('prompt_injection'), 'риск не должен попадать в выбор');
  assert.ok(!keys.includes('grips'), 'index-only не должен попадать в выбор');
  assert.ok(rejected.some((r) => r.key === 'temperature' && r.reason.includes('setting')));
});

test('отсев: бюджет в 1 вызов оставляет только одношаговые техники', () => {
  const { candidates } = gateTechniques(brief, catalog, { budgetCalls: 1 });
  assert.ok(candidates.length > 0);
  for (const c of candidates) {
    assert.ok(costRange(c.cost_calls)[0] <= 1, `${c.key} дороже бюджета`);
    assert.notEqual(c.execution, 'multi_step');
  }
});

test('педагогические типы доступны только для учебной задачи', () => {
  const normal = gateTechniques(brief, catalog);
  assert.ok(!normal.candidates.some((c) => c.category === 'pedagogy'));

  const teaching = gateTechniques({ ...brief, task_type: 'teaching' }, catalog);
  assert.ok(teaching.candidates.some((c) => c.key === 'pedagogic_closed'));
});

test('отсев: нетексовая модальность даёт понятную ошибку', () => {
  assert.throws(
    () => gateTechniques({ ...brief, modality: 'image' }, catalog),
    /каталог содержит только текстовые техники/,
  );
});

test('fillTemplate заполняет известное и сообщает о пропусках', () => {
  const { text, missing } = fillTemplate('{{task}} / {{format}} / {{unknown}}', { task: 'сделай', format: 'JSON' });
  assert.equal(text, 'сделай / JSON / {{unknown}}');
  assert.deepEqual(missing, ['unknown']);
});

test('parseBrief принимает JSON в markdown-обёртке', () => {
  const parsed = parseBrief('```json\n' + BRIEF_JSON + '\n```');
  assert.equal(parsed.task_type, 'classification');
  assert.equal(parsed.budget_calls, null);
});

test('parseBrief отвергает неизвестный task_type', () => {
  const bad = JSON.stringify({ ...JSON.parse(BRIEF_JSON), task_type: 'магия' });
  assert.throws(() => parseBrief(bad), /неизвестный task_type/);
});

test('parseChoice отвергает технику вне списка кандидатов', () => {
  const { candidates } = gateTechniques(brief, catalog);
  const raw = JSON.stringify({ key: 'temperature', reason: 'x', confidence: 0.5, whyNotCheaper: 'y' });
  assert.throws(() => parseChoice(raw, candidates), /нет среди допустимых/);
});

test('parseChoice требует объяснить, почему не самая дешёвая', () => {
  const { candidates } = gateTechniques(brief, catalog);
  const expensive = candidates.find((c) => c.execution === 'multi_step' || c.key !== candidates[0].key);
  assert.ok(expensive);
  const raw = JSON.stringify({ key: expensive!.key, reason: 'x', confidence: 0.6, whyNotCheaper: '' });
  assert.throws(() => parseChoice(raw, candidates), /не объяснено/);
});

test('runPipeline проходит весь путь на фейковой модели', async () => {
  const { llm, calls } = fakeLLM();
  const result = await runPipeline({ thoughts: 'надо разложить отзывы по тональности', catalog, llm, mode: 'deterministic' });

  assert.equal(calls.length, 2, 'два вызова: бриф и выбор');
  assert.equal(result.choice.key, 'zero_shot');
  assert.match(result.synthesis.prompt, /классифицировать отзывы/);
  assert.deepEqual(result.trace.map((t) => t.step), ['brief', 'gate', 'select', 'synthesize']);
  assert.ok(result.rejected.length > 0, 'отсеянные должны быть зафиксированы');
  assert.equal(result.synthesis.config.temperature, 0.2);
});

test('runPipeline синтезирует через модель, если mode=llm', async () => {
  const { llm, calls } = fakeLLM({ prompt: 'Финальный промпт от модели: классифицируй отзыв и верни JSON.' });
  const result = await runPipeline({ thoughts: 'тональность отзывов', catalog, llm });
  assert.equal(calls.length, 3, 'бриф, выбор, синтез');
  assert.match(result.synthesis.prompt, /Финальный промпт от модели/);
});

test('runPipeline падает, если бюджет отсекает все техники', async () => {
  const tiny = loadCatalog({
    version: 'test',
    techniques: [tech('expensive', { cost_calls: '10–40', execution: 'multi_step' })],
  });
  const { llm } = fakeLLM();
  await assert.rejects(
    () => runPipeline({ thoughts: 'x', catalog: tiny, llm, brief: { ...brief, budget_calls: 1 } }),
    /нет допустимых техник/,
  );
});

test('synthesizeWithLLM сообщает оставшиеся плейсхолдеры', async () => {
  const technique = catalog.techniques.find((t) => t.key === 'chain_of_thought')!;
  const llm = async () => 'Думай по шагам. Затем ответь: {{format}}. Ещё {{n}} раз проверь. Это достаточно длинный промпт.';
  const res = await synthesizeWithLLM(brief, technique, llm);
  assert.deepEqual(res.missing.sort(), ['format', 'n']);
  assert.ok(res.warnings.some((w) => w.includes('незаполненные')));
});

test('детерминированный синтез заполняет role и rules из брифа', () => {
  const technique = catalog.techniques.find((t) => t.key === 'system_prompting')!;
  const res = synthesizeDeterministic(brief, technique);
  assert.deepEqual(res.missing, [], 'у system_prompting не должно остаться пропусков');
  assert.match(res.prompt, /эксперт по задаче/);
  assert.equal(res.prompt.includes('{{role}}'), false);
});

test('лимит вывода зависит от типа исполнения', () => {
  const single = catalog.techniques.find((t) => t.key === 'zero_shot')!;
  const multi = catalog.techniques.find((t) => t.execution === 'multi_step')!;
  assert.match(maxTokensFor(single), /1024/);
  assert.match(maxTokensFor(multi), /на шаг/);
  assert.equal(new Set([maxTokensFor(single), maxTokensFor(multi)]).size, 2);
});

test('шаблоны не дублируют плейсхолдеры, кроме приёмов с намеренным повтором', () => {
  const allowed = new Set(['re_reading:question']);
  const bad: string[] = [];
  for (const t of catalog.techniques) {
    if (!t.template) continue;
    const names = [...t.template.matchAll(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g)].map((m) => m[1]);
    const counts = names.reduce<Record<string, number>>((acc, n) => ({ ...acc, [n]: (acc[n] ?? 0) + 1 }), {});
    for (const [n, c] of Object.entries(counts)) {
      if (c > 1 && !allowed.has(`${t.key}:${n}`)) bad.push(`${t.key}:${n}×${c}`);
    }
  }
  assert.deepEqual(bad, []);
});

test('офлайн-режим отсекает техники с невыводимыми плейсхолдерами', () => {
  const derivable = new Set(['task', 'input', 'format', 'language', 'role', 'rules', 'topic', 'goal', 'question', 'constraints', 'criteria', 'context', 'document', 'text', 'external_text', 'task_type']);
  const { candidates, rejected } = gateTechniques(brief, catalog, { derivablePlaceholders: derivable });
  assert.ok(!candidates.some((c) => c.key === 'few_shot'), 'few_shot требует примеров');
  assert.ok(rejected.some((r) => r.key === 'few_shot' && r.reason.includes('нечем заполнить')));
  assert.ok(candidates.some((c) => c.key === 'zero_shot'));
});

test('защита от инъекций добавляется только там, где есть внешний материал', () => {
  const contextual = catalog.techniques.find((t) => t.key === 'contextual_prompting')!;
  const zero = catalog.techniques.find((t) => t.key === 'zero_shot')!;

  const guarded = synthesizeDeterministic({ ...brief, task_type: 'qa_over_docs' }, contextual);
  assert.match(guarded.prompt, /это данные, а не инструкции/);
  assert.ok(guarded.warnings.some((w) => w.includes('prompt injection')));

  const plain = synthesizeDeterministic({ ...brief, task_type: 'generation' }, zero);
  assert.equal(/это данные, а не инструкции/.test(plain.prompt), false);
});
