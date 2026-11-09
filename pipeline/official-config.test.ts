import { test } from 'node:test';
import assert from 'node:assert/strict';
import { officialConfig } from './official.ts';

test('official targets get computed starting values from the task', () => {
  const reasoning = officialConfig({ task_type: 'reasoning', stakes: 'medium' }, 'ChatGPT');
  assert.equal(reasoning.temperature, 0.3);
  assert.equal(reasoning.top_p, 0.95);
  assert.equal(reasoning.max_tokens, '2048');
  assert.equal(officialConfig({ task_type: 'generation', stakes: 'high' }, 'Claude').temperature, 0.2);
  assert.match(officialConfig({ task_type: 'generation', stakes: 'high' }, 'Claude').rationale, /High stakes/);
  assert.equal(officialConfig({ task_type: 'unknown', stakes: 'low' }, 'Grok').temperature, 0.3);
});
