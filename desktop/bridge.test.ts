import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

/** E2E границы процесса: Python/UI зовёт мост именно так — JSON на stdin, JSON на stdout. */

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const bridge = join(root, 'desktop', 'bridge.ts');

function call(payload: unknown): { ok: boolean; data: Record<string, unknown>; stderr: string } {
  const result = spawnSync(process.execPath, [bridge], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    timeout: 60_000,
    cwd: root,
  });
  return {
    ok: result.status === 0,
    data: JSON.parse(result.stdout || '{}') as Record<string, unknown>,
    stderr: result.stderr ?? '',
  };
}

test('мост: Enter your thoughts возвращает ошибку, а не падает', () => {
  const { data } = call({ thoughts: '   ', model: 'dummy' });
  assert.equal(data.ok, false);
  assert.match(String(data.error), /Enter your thoughts/);
});

test('мост: без модели просит её указать', () => {
  const { data } = call({ thoughts: 'сделай что-нибудь' });
  assert.equal(data.ok, false);
  assert.match(String(data.error), /model/);
});

test('мост: список техник содержит и готовые, и процедуры', () => {
  const { data } = call({ thoughts: 'x', model: 'dummy', listTechniques: true });
  const techniques = data.techniques as { key: string; status: string }[];
  assert.ok(Array.isArray(techniques));
  assert.ok(techniques.length >= 80, `техник мало: ${techniques.length}`);
  assert.ok(techniques.some((t) => t.status === 'ready'));
  assert.ok(techniques.some((t) => t.status === 'procedure'));
});

test('мост: процедура возвращает шаги, а не промпт', () => {
  const { data } = call({
    thoughts: 'отбери похожие примеры',
    provider: 'ollama',
    model: 'dummy',
    manualTechnique: 'icl_knn_selection',
  });
  const procedure = data.procedure as { steps: string[] };
  assert.equal(data.ok, true);
  assert.ok(Array.isArray(procedure.steps));
  assert.ok(procedure.steps.length >= 3);
  assert.equal(data.manual, undefined);
});

test('мост: ручная техника не игнорирует запрет LLM-синтеза', () => {
  const { data } = call({ thoughts: 'синтетический тест', model: 'dummy', manualTechnique: 'zero_shot', deterministic: true });
  assert.equal(data.ok, false);
  assert.match(String(data.error), /Disable Skip/);
});
