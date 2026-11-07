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
  const techniques = data.techniques as { key: string; status: string; sources: { title: string; url: string; reference: string }[] }[];
  assert.ok(Array.isArray(techniques));
  assert.ok(techniques.length >= 80, `техник мало: ${techniques.length}`);
  for (const technique of techniques) {
    assert.ok(technique.sources.length > 0, technique.key);
    for (const source of technique.sources) {
      const url = new URL(source.url);
      assert.equal(url.protocol, 'https:');
      assert.ok(['archive.org', 'arxiv.org'].includes(url.hostname));
      assert.ok(source.title && source.reference);
    }
  }
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
  assert.match(String((data.procedure as { zeroShotPrompt: string }).zeroShotPrompt), /отбери похожие примеры/);
});

test('мост: ручная техника не игнорирует запрет LLM-синтеза', () => {
  const { data } = call({ thoughts: 'синтетический тест', model: 'dummy', manualTechnique: 'zero_shot', deterministic: true });
  assert.equal(data.ok, false);
  assert.match(String(data.error), /Disable Skip/);
});

test('bridge: Claude-only mode rejects manual and deterministic bypasses', () => {
  for (const extra of [{ manualTechnique: 'zero_shot' }, { deterministic: true }]) {
    const { data } = call({ thoughts: 'Synthetic parity test', model: 'dummy', claudeOnly: true, ...extra });
    assert.equal(data.ok, false);
    assert.match(String(data.error), /Claude mode/);
  }
});

test('bridge: all official modes reject conflicting flags, wrong types, and manual bypasses', () => {
  for (const extra of [
    { claudeOnly: true, chatgptOnly: true }, { chatgptOnly: true, geminiOnly: true },
    { chatgptOnly: 'true' }, { geminiOnly: 1 },
    { chatgptOnly: true, manualTechnique: 'zero_shot' }, { geminiOnly: true, manualTechnique: 'zero_shot' },
    { chatgptOnly: true, deterministic: true }, { geminiOnly: true, deterministic: true },
    { grokOnly: 'true' }, { grokOnly: true, claudeOnly: true },
    { grokOnly: true, manualTechnique: 'zero_shot' }, { grokOnly: true, deterministic: true },
  ]) {
    const { data } = call({ thoughts: 'Synthetic parity test', model: 'dummy', ...extra });
    assert.equal(data.ok, false);
    assert.match(String(data.error), /only one target|must be a boolean|cannot use a generic technique|cannot use a generic manual technique/);
  }
});


test('bridge: live progress stays on stderr and preserves the final JSON protocol', () => {
  const { data, stderr } = call({ thoughts: 'Select nearby examples', model: 'dummy',
    manualTechnique: 'icl_knn_selection', reportProgress: true });
  assert.equal(data.ok, true);
  assert.match(stderr, /PROMPTA_PROGRESS /);
  const update = JSON.parse(stderr.split('\n').find((line) => line.startsWith('PROMPTA_PROGRESS '))!.slice('PROMPTA_PROGRESS '.length));
  assert.equal(update.percent, 10);
  assert.equal(update.stage, 'Technique loaded');
});
