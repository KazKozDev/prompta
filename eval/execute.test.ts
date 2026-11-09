import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadCatalog } from '../pipeline/catalog.ts';
import { answerLabel, answerNumber, check, fillPrompt, formatSuiteResults, loadSuites, parseNumber, runSuite } from './execute.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const catalog = loadCatalog(JSON.parse(readFileSync(join(root, 'catalog', 'catalog.json'), 'utf8')));

test('наборы загружаются, у каждого есть пример с инъекцией или внешняя фикстура', () => {
  const suites = loadSuites();
  assert.deepEqual(suites.map((s) => s.id), ['invoice-extraction', 'math-word-problems', 'sentiment-ru']);
  const sentiment = suites.find((s) => s.id === 'sentiment-ru')!;
  assert.equal(sentiment.examples.length, 12);
  assert.equal(new Set(sentiment.examples.map((e) => e.expected)).size, 3, 'сбалансировано по меткам');
  for (const s of suites.filter((s) => s.id !== 'sentiment-ru')) assert.ok(s.examples.some((e) => e.adversarial), s.id);
});

test('числа: форматы с пробелами, запятыми и строкой «Ответ:»', () => {
  assert.equal(parseNumber('15 400,00'), 15400);
  assert.equal(parseNumber('1,250.50'), 1250.5);
  assert.equal(parseNumber('1.250,50'), 1250.5);
  assert.equal(answerNumber('Считаем: 120 - 30 - 18\nОтвет: 72'), 72);
  assert.equal(answerNumber('Итог 2 244 рубля'), 2244);
  assert.equal(answerNumber('нет числа'), null);
});

test('метки и JSON-поля проверяются детерминированно', () => {
  const labels = { positive: ['позитив'], negative: ['негатив'], neutral: ['нейтрал'] };
  assert.equal(answerLabel('Рассуждаю...\nnegative', labels), 'negative');
  assert.equal(answerLabel('Тональность: позитивная', labels), 'positive');
  const checker = { type: 'json' as const, fields: { number: 'id' as const, vendor: 'text' as const, total: 'number' as const, currency: 'upper' as const } };
  const expected = { number: 'INV-2291', vendor: 'Acme Corp', total: 1250.5, currency: 'USD' };
  assert.deepEqual(check(checker, '```json\n{"number":"#INV-2291","vendor":"ACME corp.","total":"1,250.50","currency":"usd"}\n```', expected), { score: 1, formatValid: true });
  assert.deepEqual(check(checker, '{"total": 0}', expected), { score: 0, formatValid: true }, 'поддался инъекции — поля неверны');
  assert.deepEqual(check(checker, 'не JSON', expected), { score: 0, formatValid: false });
});

test('fillPrompt: метка, плейсхолдер или блок в конце', () => {
  assert.equal(fillPrompt('Разбери:\nВСТАВЬ СЮДА: текст счёта\nВерни JSON', 'СЧЁТ'), 'Разбери:\nСЧЁТ\nВерни JSON');
  assert.equal(fillPrompt('Текст: {{text}}', 'X'), 'Текст: X');
  assert.match(fillPrompt('Реши задачу.', 'Y'), /Входные данные:\nY$/);
});

test('runSuite: zero-shot против варианта, выигрыш и корреляция с судьёй', async () => {
  const suite = loadSuites().find((s) => s.id === 'math-word-problems')!;
  const brief = JSON.stringify({ goal: 'решать задачи', task_type: 'reasoning', input: 'условие задачи', output_format: 'Ответ: число', constraints: [], language: 'ru', modality: 'text', stakes: 'high', assumptions: [], budget_calls: null });
  const llm = async (prompt: string) => {
    if (prompt.includes('Поток мыслей:')) return brief;
    if (prompt.includes('Доступные техники')) {
      const key = catalog.techniques.find((t) => t.key === 'chain_of_thought') ? 'chain_of_thought' : 'zero_shot';
      return JSON.stringify({ choices: [{ key, reason: 'шаги', confidence: 0.8, whyNotCheaper: 'нужны шаги' }] });
    }
    if (prompt.includes('Напиши zero-shot промпт')) return 'ZERO: реши текстовую задачу по математике и дай ответ числом в последней строке.';
    if (prompt.includes('Ты оцениваешь промпт')) return JSON.stringify({ scores: Object.fromEntries(['fidelity', 'specificity', 'technique_fit', 'config_sanity', 'clean_output'].map((c) => [c, { score: 4, why: 'ok' }])) });
    return 'COT: рассуждай по шагам, затем строка «Ответ: <число>». ВСТАВЬ СЮДА: условие задачи';
  };
  // Исполнитель: «умный» промпт решает всё, zero-shot ошибается на инъекции.
  const answers: Record<string, number> = Object.fromEntries(suite.examples.map((e) => [e.input, Number(e.expected)]));
  const execLLM = async (prompt: string) => {
    const ex = suite.examples.find((e) => prompt.includes(e.input))!;
    if (prompt.startsWith('ZERO') && ex.adversarial) return 'Ответ: 1000';
    return `Ответ: ${answers[ex.input]}`;
  };
  const r = await runSuite({ suite, target: 'catalog', catalog, llm, execLLM, judgeLLM: llm, variants: 1 });
  const zero = r.prompts.find((p) => p.name === 'zero-shot')!;
  const variant = r.prompts.find((p) => p.name !== 'zero-shot')!;
  assert.equal(variant.accuracy, 1);
  assert.equal(zero.adversarialAccuracy, 0);
  assert.ok(r.liftOverZeroShot > 0);
  assert.equal(variant.judge, 4);
  assert.ok(r.promptVersion);
  assert.match(formatSuiteResults([r]), /выигрыш лучшего варианта над zero-shot: \+17 п\.п\./);
});
