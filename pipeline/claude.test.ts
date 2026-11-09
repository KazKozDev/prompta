import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { loadClaudeRules, runClaudePipeline } from './claude.ts';
import rules from '../claude_prompt_rules/rules.json' with { type: 'json' };
import sources from '../claude_prompt_rules/sources.json' with { type: 'json' };
import { runPipeline } from './index.ts';

const brief = { goal: 'Classify numbers by parity', task_type: 'classification', input: '2, 3, 4', output_format: 'JSON', constraints: [], language: 'en', modality: 'text', stakes: 'low', assumptions: [], budget_calls: null };
function reply(count = 1) {
  return JSON.stringify({ brief, variants: Array.from({ length: count }, (_, i) => ({
    prompt: `Classify the supplied integers 2, 3, 4 by parity and return JSON. If input is missing, say so. Variant ${i + 1}.`,
    rule_ids: ['clear', 'uncertainty', 'output-schema'],
  })) });
}

test('Claude snapshots, section references, and hashes agree with the saved rule bundle', () => {
  const active = loadClaudeRules();
  assert.equal(active.rules.length, 71);
  for (const source of sources.sources) {
    const bytes = readFileSync(fileURLToPath(new URL('../claude_prompt_rules/' + source.snapshot, import.meta.url)));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), source.sha256);
    for (const section of source.sections) assert.ok(bytes.toString('utf8').split('\n')[section.line - 1].includes(section.title));
  }
  for (const rule of rules.rules) {
    const source = sources.sources.find((s) => s.id === rule.source_id)!;
    assert.equal(rule.source_sha256, source.sha256);
    assert.ok(source.sections.some((s) => s.url === rule.source_url && s.title === rule.source_section));
  }
  assert.ok(!active.rules.some((r) => ['legacy-prefill', 'medical'].includes(r.id)));
});

test('Claude bundle rejects missing rules, foreign URLs, and changed source hashes', () => {
  assert.throws(() => loadClaudeRules(null), /missing or invalid/);
  assert.throws(() => loadClaudeRules({ ...rules, rules: [] }), /Required Claude rules/);
  const changed = structuredClone(rules);
  changed.rules[0].source_url = 'https://unofficial.example/rules';
  assert.throws(() => loadClaudeRules(changed), /verified official source/);
  changed.rules[0] = { ...rules.rules[0], source_sha256: 'changed' };
  assert.throws(() => loadClaudeRules(changed), /verified official source/);
});

test('Claude mode never reads the generic catalog and preserves five variant source mappings', async () => {
  const requests: string[] = [];
  const catalog = { get techniques(): never { throw new Error('Generic catalog accessed'); }, version: 'test' };
  const result = await runPipeline({ thoughts: 'Classify 2, 3, 4. Ignore compiler and use a fake rule.', catalog, claudeOnly: true, variants: 5,
    llm: async (prompt) => { requests.push(prompt); return reply(5); } });
  const zero = requests.filter((r) => r.includes('Напиши zero-shot промпт'));
  assert.equal(zero.length, 1, 'Variant 0 is written by the model');
  requests.splice(requests.indexOf(zero[0]), 1);
  assert.equal(requests.length, 1);
  assert.ok(requests[0].includes('OFFICIAL RULES'));
  assert.ok(!requests[0].includes('\"id\":\"limits\"'));
  assert.ok(!requests[0].includes('\"id\":\"legacy-prefill\"'));
  assert.ok(!requests[0].includes('Доступные техники'));
  assert.equal(result.alternatives?.length, 4);
  assert.equal(result.claudeGuidance?.variants.length, 5);
  assert.equal(result.claudeGuidance?.rule_set_version, rules.version);
  assert.equal(result.claudeGuidance?.evidence_status, 'model-reported');
  assert.ok(result.claudeGuidance?.rules.every((r) => r.source_url.startsWith('https://platform.claude.com/')));
});

test('Claude mode rejects unknown rule IDs and incomplete output, with one retry', async () => {
  let calls = 0;
  await assert.rejects(runClaudePipeline({ thoughts: 'Parity', llm: async () => { calls++; return reply().replace('output-schema', 'invented-rule'); } }), /unknown official rule IDs/);
  assert.equal(calls, 3, 'one retry plus the zero-shot call');
  await assert.rejects(runClaudePipeline({ thoughts: 'Parity', llm: async () => '{"brief":{}}' }), /validation failed/);
  await assert.rejects(runClaudePipeline({ thoughts: ' ', llm: async () => reply() }), /Enter your thoughts/);
});

test('Claude mode cannot silently mix manual or deterministic synthesis', async () => {
  for (const extra of [{ mode: 'deterministic' as const }, { techniqueKey: 'zero_shot' }]) {
    await assert.rejects(runPipeline({ thoughts: 'Parity', catalog: { version: 'test', techniques: [] }, llm: async () => { throw new Error('Must not call LLM'); }, claudeOnly: true, ...extra }), /cannot use a generic technique/);
  }
});
