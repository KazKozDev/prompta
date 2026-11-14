import { test } from 'node:test';
import assert from 'node:assert/strict';

import { fnv1a, PROMPT_SET, promptVersion } from './prompt-version.ts';

test('fnv1a matches the published FNV-1a 32-bit vectors', () => {
  assert.equal(fnv1a(''), '811c9dc5');
  assert.equal(fnv1a('a'), 'e40c292c');
  assert.equal(fnv1a('foobar'), 'bf9cf968');
});

test('fnv1a pads to eight hex digits and tells close texts apart', () => {
  assert.match(fnv1a('prompt'), /^[0-9a-f]{8}$/);
  assert.notEqual(fnv1a('Use ONLY the material below.'), fnv1a('Use ONLY the material below!'));
});

test('promptVersion is the manual label plus the source hash, stable within a run', () => {
  const version = promptVersion();
  assert.match(version, new RegExp(`^${PROMPT_SET}\\+[0-9a-f]{8}$`));
  assert.equal(promptVersion(), version);
});
