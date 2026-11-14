import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { auditPrompt, CHECKS } from './audit.ts';
import { loadCatalog } from '../pipeline/catalog.ts';

test('every audited technique exists in the catalog', () => {
  const catalog = loadCatalog(JSON.parse(readFileSync(new URL('../catalog/catalog.json', import.meta.url), 'utf8')));
  const keys = new Set(catalog.techniques.map((t) => t.key));
  for (const key of Object.keys(CHECKS)) assert.ok(keys.has(key), key);
});

test('a prompt with the method and the task passes', () => {
  const prompt = 'Разбери заметки со встречи. Think step by step and show your reasoning before the table.';
  assert.deepEqual(auditPrompt('chain_of_thought', prompt), { marks: [true, true], context: true, ok: true });
});

test('a rewritten template without the method fails on its signs', () => {
  const result = auditPrompt('few_shot', 'Вытащи задачи из заметок со встречи в таблицу.');
  assert.deepEqual(result.marks, [false, false]);
  assert.equal(result.ok, false);
});

test('a prompt that lost the task fails on context', () => {
  const result = auditPrompt('tabular_cot', 'Fill the table: | step | result |');
  assert.equal(result.marks.every(Boolean), true);
  assert.equal(result.context, false);
  assert.equal(result.ok, false);
});

test('an unknown technique is an error, not a silent pass', () => {
  assert.throws(() => auditPrompt('no_such_technique', 'x'), /no audit check/);
});
