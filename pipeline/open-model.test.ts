import test from 'node:test';
import assert from 'node:assert/strict';
import { loadOpenModel } from './open-model.ts';
import { runPipeline } from './index.ts';
import manifest from '../open_model_prompt_guides/manifest.json' with { type: 'json' };

test('all fifteen prompting targets load pinned and verified model-specific sources', () => {
  for (const model of manifest.models) {
    const loaded = loadOpenModel(model.id);
    assert.equal(loaded.model.revision, model.revision);
    assert.ok(loaded.rule.rule_text.length > 100);
    assert.ok(loaded.rule.source_url.includes(model.revision));
  }
  assert.throws(() => loadOpenModel('../../outside'), /Unknown prompting model/);
});
test('open-model target reaches synthesis, retains provenance and excludes other providers', async () => {
  let instructions = '';
  const opts = { thoughts: 'Classify 2, 3, 4 by parity', openModel: 'gemma-4-31b', catalog: { version: 'test', techniques: [] }, variants: 1,
    llm: async (prompt: string) => {
      instructions = prompt;
      return JSON.stringify({ brief: { goal: 'Classify integers', task_type: 'classification', input: '2, 3, 4', output_format: 'JSON', constraints: [], language: 'en', modality: 'text', stakes: 'low', assumptions: [], budget_calls: null },
        variants: [{ prompt: 'Classify the integers 2, 3, 4 by parity. Return JSON with even and odd arrays.', rule_ids: ['model-source'] }] });
    } };
  const result = await runPipeline(opts);
  assert.ok(instructions.includes('Exact target: Gemma 4 31B IT'));
  assert.ok(!instructions.includes('no exact target model is selected'));
  assert.equal(result.openModelGuidance?.rules[0].source_url, loadOpenModel(opts.openModel).rule.source_url);
  assert.equal(result.alternatives?.length, 0);
  await assert.rejects(runPipeline({ ...opts, grokOnly: true }), /Choose only one target/);
  await assert.rejects(runPipeline({ ...opts, techniqueKey: 'zero_shot' }), /requires synthesis/);
});
