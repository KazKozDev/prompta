import test from 'node:test';
import assert from 'node:assert/strict';
import { parseTarget } from './target.ts';

test('parseTarget: one string names one target; absent is any LLM; anything else is refused', () => {
  assert.equal(parseTarget(undefined), undefined);
  assert.equal(parseTarget(''), undefined);
  assert.deepEqual(parseTarget('claude'), { kind: 'claude' });
  assert.deepEqual(parseTarget('hermes'), { kind: 'hermes' });
  assert.deepEqual(parseTarget('open:glm-5-3'), { kind: 'openModel', model: 'glm-5-3' });
  for (const bad of ['open:', 'open:  ', 'openModel', 'Claude', 'claude,grok']) assert.throws(() => parseTarget(bad), /Unknown target/);
  for (const bad of [true, 1, {}]) assert.throws(() => parseTarget(bad), /must be a string/);
});
