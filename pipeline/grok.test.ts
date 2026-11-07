import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { loadGrokRules, runGrokPipeline } from './grok.ts';
import { runPipeline } from './index.ts';
import { renderPipelineResult } from './render.ts';
import { isOfficialSourceUrl } from './official.ts';
import rules from '../grok_prompt_rules/rules.json' with { type: 'json' };
import sources from '../grok_prompt_rules/sources.json' with { type: 'json' };

function reply(count = 5, ids = ['clear', 'output-schema']) {
  return JSON.stringify({ brief: { goal: 'Classify supplied integers', task_type: 'classification',
    input: '2, 3, 4', output_format: 'JSON', constraints: [], language: 'en', modality: 'text', stakes: 'low', assumptions: [], budget_calls: null },
  variants: Array.from({ length: count }, (_, i) => ({ prompt: `Classify the supplied integers 2, 3, 4 by parity and return a JSON object. Variant ${i + 1}.`, rule_ids: ids })) });
}

test('Grok archive and every active recommendation match downloaded official sources', () => {
  const bundle = loadGrokRules();
  assert.ok(bundle.rules.length > 0);
  for (const source of sources.sources) {
    assert.ok(isOfficialSourceUrl(source.url, 'grok'));
    assert.equal(createHash('sha256').update(readFileSync(new URL(`../grok_prompt_rules/${source.snapshot}`, import.meta.url))).digest('hex'), source.sha256);
  }
  for (const rule of rules.rules) {
    const source = sources.sources.find((s) => s.id === rule.source_id)!;
    assert.equal(rule.source_sha256, source.sha256);
    assert.ok(source.sections.some((s) => s.title === rule.source_section && s.url === rule.source_url));
  }
  assert.ok(!bundle.rules.some((r) => r.source_id === 'multi-agent'));
  assert.ok(!bundle.rules.some((r) => r.id === 'uncertainty'));
  assert.throws(() => loadGrokRules({ ...rules, rules: [] }), /Required Grok rules/);
  const bad = structuredClone(rules);
  bad.rules[0].source_url = 'https://docs.x.ai.evil.example/rules';
  assert.throws(() => loadGrokRules(bad), /verified official source/);
});

test('Grok generates five sourced variants without the generic catalog or API advice', async () => {
  let request = '';
  const result = await runPipeline({ thoughts: 'Classify 2, 3, 4', grokOnly: true, variants: 5,
    catalog: { version: 'unused', get techniques(): never { throw new Error('Generic catalog accessed'); } },
    llm: async (prompt) => { request = prompt; return reply(); } });
  assert.match(request, /targeted at Grok/);
  assert.doesNotMatch(request, /"id":"sampling"|"id":"research-scope"/);
  assert.equal(result.alternatives?.length, 4);
  assert.equal(result.grokGuidance?.variants.length, 5);
  assert.equal(result.grokGuidance?.evidence_status, 'model-reported');
  assert.equal(result.synthesis.config.temperature, null);
  assert.match(renderPipelineResult(result), /Grok rules/);
  assert.match(renderPipelineResult(result), /https:\/\/docs.x.ai/);
});

test('Grok rejects missing rules, mixed targets, and synthesis bypasses', async () => {
  let calls = 0;
  await assert.rejects(runGrokPipeline({ thoughts: 'Test', variants: 5, llm: async () => { calls++; return reply(5, ['clear', 'invented']); } }), /official rule IDs/);
  assert.equal(calls, 2);
  const base = { thoughts: 'Test', grokOnly: true, catalog: { version: 'unused', techniques: [] }, llm: async () => { throw new Error('Must not call'); } };
  await assert.rejects(runPipeline({ ...base, geminiOnly: true }), /only one target/);
  await assert.rejects(runPipeline({ ...base, mode: 'deterministic' }), /cannot use a generic technique/);
  await assert.rejects(runPipeline({ ...base, techniqueKey: 'zero_shot' }), /cannot use a generic technique/);
});
