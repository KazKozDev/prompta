import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { loadChatGPTRules, runChatGPTPipeline } from './chatgpt.ts';
import { loadGeminiRules, runGeminiPipeline } from './gemini.ts';
import chatgptRules from '../chatgpt_prompt_rules/rules.json' with { type: 'json' };
import chatgptSources from '../chatgpt_prompt_rules/sources.json' with { type: 'json' };
import geminiRules from '../gemini_prompt_rules/rules.json' with { type: 'json' };
import geminiSources from '../gemini_prompt_rules/sources.json' with { type: 'json' };
import { runPipeline } from './index.ts';
import { isOfficialSourceUrl } from './official.ts';
import type { OfficialTarget } from './official.ts';

const cases = [
  { target: 'chatgpt' as const, flag: 'chatgptOnly' as const, key: 'chatgptGuidance' as const, label: 'ChatGPT', load: loadChatGPTRules, run: runChatGPTPipeline, rules: chatgptRules, sources: chatgptSources },
  { target: 'gemini' as const, flag: 'geminiOnly' as const, key: 'geminiGuidance' as const, label: 'Gemini', load: loadGeminiRules, run: runGeminiPipeline, rules: geminiRules, sources: geminiSources },
];
const brief = { goal: 'Classify integers by parity', task_type: 'classification', input: '2, 3, 4', output_format: 'JSON', constraints: [], language: 'en', modality: 'text', stakes: 'low', assumptions: [], budget_calls: null };
function reply(count = 1, rule = 'output-schema') {
  return JSON.stringify({ brief, variants: Array.from({ length: count }, (_, index) => ({
    prompt: `Classify only the integers 2, 3, 4 as even or odd and return JSON. Flag missing values. Format variant ${index + 1}.`,
    rule_ids: ['clear', 'uncertainty', rule],
  })) });
}

for (const item of cases) {
  test(`${item.label}: saved snapshots, rules, sections, and source hashes agree`, () => {
    const active = item.load();
    assert.ok(active.rules.filter((r) => r.application === 'prompt').length >= 25);
    assert.ok(active.rules.every((r) => r.status === 'active'));
    for (const source of item.sources.sources) {
      const bytes = readFileSync(fileURLToPath(new URL(`../${item.target}_prompt_rules/${source.snapshot}`, import.meta.url)));
      assert.equal(createHash('sha256').update(bytes).digest('hex'), source.sha256);
      assert.ok(isOfficialSourceUrl(source.url, item.target));
      for (const section of source.sections) assert.ok(bytes.toString('utf8').split('\n')[section.line - 1].includes(section.title));
    }
    for (const rule of item.rules.rules) {
      const source = item.sources.sources.find((s) => s.id === rule.source_id)!;
      assert.equal(rule.source_sha256, source.sha256);
      assert.ok(source.sections.some((s) => s.title === rule.source_section && s.url === rule.source_url));
    }
  });

  test(`${item.label}: rejects missing, stale, or cross-provider rule bundles`, () => {
    assert.throws(() => item.load(null), /missing or invalid/);
    assert.throws(() => item.load({ ...item.rules, rules: [] }), /Required/);
    const modified = structuredClone(item.rules);
    modified.rules[0].source_url = 'https://platform.claude.com/docs/rules';
    assert.throws(() => item.load(modified), /verified official source/);
    modified.rules[0] = { ...item.rules.rules[0], source_sha256: 'changed' };
    assert.throws(() => item.load(modified), /verified official source/);
  });

  test(`${item.label}: routes five variants without reading the generic catalog`, async () => {
    let request = '';
    const catalog = { version: 'unused', get techniques(): never { throw new Error('Generic catalog accessed'); } };
    const result = await runPipeline({ thoughts: 'Synthetic parity test', catalog, [item.flag]: true, variants: 5,
      llm: async (prompt) => { request = prompt; return reply(5); } });
    assert.match(request, new RegExp(`targeted at ${item.label}`));
    assert.ok(!request.includes('"id":"legacy-prefill"'));
    assert.ok(!request.includes('"id":"structured-api"'));
    assert.equal(result.choice.key, `${item.target}_official`);
    assert.equal(result.alternatives?.length, 4);
    const guidance = result[item.key]!;
    assert.equal(guidance.variants.length, 5);
    assert.equal(guidance.evidence_status, 'model-reported');
    assert.equal(guidance.rule_set_version, item.rules.version);
    assert.ok(guidance.rules.every((r) => isOfficialSourceUrl(r.source_url, item.target)));
    assert.equal(Object.keys(result).filter((key) => key.endsWith('Guidance')).length, 1);
  });

  test(`${item.label}: one retry repairs malformed JSON; unknown source IDs never pass`, async () => {
    let calls = 0;
    const result = await item.run({ thoughts: 'Synthetic parity', llm: async () => ++calls === 1 ? '{}' : reply() });
    assert.equal(calls, 2);
    assert.ok(result[item.key]);
    await assert.rejects(item.run({ thoughts: 'Synthetic parity', llm: async () => reply(1, 'invented-provider-rule') }), /unknown official rule IDs/);
    await assert.rejects(item.run({ thoughts: 'Synthetic parity', llm: async () => reply(1, 'structured-api') }), /unknown official rule IDs/);
    await assert.rejects(item.run({ thoughts: '', llm: async () => reply() }), /Enter your thoughts/);
  });
}

test('official target modes reject simultaneous selection and generic synthesis bypasses', async () => {
  const base = { thoughts: 'Synthetic parity', catalog: { version: 'unused', techniques: [] }, llm: async () => { throw new Error('Must not call model'); } };
  for (const flags of [{ claudeOnly: true, chatgptOnly: true }, { claudeOnly: true, geminiOnly: true }, { chatgptOnly: true, geminiOnly: true }]) {
    await assert.rejects(runPipeline({ ...base, ...flags }), /Choose only one target/);
  }
  for (const item of cases) {
    for (const extra of [{ mode: 'deterministic' as const }, { techniqueKey: 'zero_shot' }]) {
      await assert.rejects(runPipeline({ ...base, [item.flag]: true, ...extra }), /cannot use a generic technique/);
    }
  }
});

test('source links reject lookalike domains, embedded credentials, and local URLs for every target', () => {
  for (const target of ['claude', 'chatgpt', 'gemini'] as OfficialTarget[]) {
    for (const url of ['file:///private/secret', 'javascript:alert(1)', 'https://developers.openai.com.evil.example/docs', 'https://aistudio.google.com.evil.example/docs', 'https://user:password@developers.openai.com/api/docs']) {
      assert.equal(isOfficialSourceUrl(url, target), false);
    }
  }
});


for (const item of cases) {
  test(`${item.label}: desktop example and topic instructions accompany real validation progress`, async () => {
    const updates: number[] = [];
    const result = await runPipeline({ thoughts: 'Classify integers', catalog: { version: 'test', techniques: [] },
      [item.flag]: true, oneShot: true, onProgress: (percent) => updates.push(percent),
      llm: async (prompt) => {
        assert.match(prompt, /Begin the final prompt with one short, relevant worked example/);
        assert.match(prompt, /brief.topic/);
        assert.deepEqual(updates, [20]);
        return reply();
      } });
    assert.ok(result[item.key]);
    assert.ok(result.zeroShotPrompt?.includes(brief.goal));
    assert.equal(result.alternatives?.length ?? 0, 0);
    assert.deepEqual(updates, [20, 95]);
  });
}

test('Hermes Agent routes through saved guidance and preserves the revised brief', async () => {
  const revised = { ...brief, modality: 'text' as const, stakes: 'low' as const, assumptions: ['Treat zero as even'] };
  const prompts: string[] = [];
  const result = await runPipeline({
    thoughts: 'Classify the input numbers',
    brief: revised,
    catalog: { version: 'test', techniques: [] },
    hermesOnly: true,
    executionCapabilities: { web: 'available' },
    llm: async (prompt) => {
      prompts.push(prompt);
      if (prompt.includes('Напиши zero-shot')) return 'Classify the supplied integers and return the results as JSON.';
      return JSON.stringify({ variants: [{
        prompt: 'Classify each supplied integer by parity and return the labels as JSON.',
        rule_ids: ['tips'],
      }] });
    },
  });
  assert.deepEqual(result.brief.assumptions, revised.assumptions);
  assert.equal(result.hermesGuidance?.rules[0].id, 'tips');
  assert.equal(result.synthesis.config.temperature, null);
  assert.ok(prompts.every((prompt) => prompt.includes(revised.assumptions[0]) && prompt.includes('"web":"available"')));
});
