import test from 'node:test';
import assert from 'node:assert/strict';
import { buildClarifyPrompt, clarifySection, generateClarify, parseClarify } from './clarify.ts';
import { buildSkillPrompt } from './skill.ts';
import { buildAgentPrompt } from './agent.ts';
import { buildInstructionsPrompt, generateInstructions } from './instructions.ts';
import type { LLM } from './types.ts';

test('clarify: questions with defaults and assumptions are read from a model answer or the window', () => {
  const parsed = parseClarify('```json\n{"questions":[{"question":"Язык README?","default":"английский"},"Лицензия?",{"x":1}],"assumptions":["без бейджей",""]}\n```');
  assert.deepEqual(parsed, {
    questions: [{ question: 'Язык README?', default: 'английский' }, { question: 'Лицензия?' }],
    assumptions: ['без бейджей'],
  });
  assert.deepEqual(parseClarify({ questions: [{ question: 'Q', default: 'A' }], assumptions: ['x'], extra: 1 }), {
    questions: [{ question: 'Q', default: 'A' }], assumptions: ['x'],
  });
  assert.deepEqual(parseClarify(null), { questions: [], assumptions: [] });
});

test('clarify: each kind asks about its own gaps, and the request goes in as data', () => {
  assert.match(buildClarifyPrompt('skill', 'readme'), /should trigger/);
  assert.match(buildClarifyPrompt('instructions', 'repo'), /test and lint commands/);
  assert.match(buildClarifyPrompt('agent', 'reviewer'), /one job/);
  assert.match(buildClarifyPrompt('skill', 'say "hi"'), /"say \\"hi\\""/);
});

test('clarify: a model that cannot answer in JSON gives undefined after one retry, not an error', async () => {
  let calls = 0;
  const llm: LLM = async () => { calls++; return 'no json here'; };
  assert.equal(await generateClarify('skill', 'x', llm), undefined);
  assert.equal(calls, 2);
});

test('clarify: answers, assumptions and open questions reach every file prompt', () => {
  const clarify = { questions: [{ question: 'Test command?', default: 'npm test' }, { question: 'Node version?' }], assumptions: ['monorepo'] };
  const section = clarifySection(clarify);
  assert.match(section, /"answer":"npm test"/);
  assert.match(section, /"open_questions":\["Node version\?"\]/);
  assert.match(section, /INSERT HERE/);
  assert.equal(clarifySection({ questions: [], assumptions: [] }), '');
  assert.equal(clarifySection(undefined), '');
  for (const prompt of [
    buildSkillPrompt('task', [], 'portable', clarify),
    buildAgentPrompt('task', [], 'claudeCode', clarify),
    buildInstructionsPrompt('task', [], 'agentsMd', clarify),
  ]) {
    assert.ok(prompt.endsWith(section), 'the answers follow the task');
  }
  assert.ok(!buildSkillPrompt('task', [], 'portable').includes('Decisions for'));
});

test('clarify: a path given as an answer is not flagged as invented', async () => {
  const file = '# AGENTS.md\n\n## Commands\n\n- Test: `scripts/test.sh`\n';
  const llm: LLM = async () => file;
  const clarify = { questions: [{ question: 'Test command?', default: 'scripts/test.sh' }], assumptions: [] };
  const withAnswer = await generateInstructions({ thoughts: 'a repo', llm, target: 'agentsMd', clarify });
  const without = await generateInstructions({ thoughts: 'a repo', llm, target: 'agentsMd' });
  assert.ok(!withAnswer.check.warnings.some((w) => w.includes('scripts/test.sh')));
  assert.ok(without.check.warnings.some((w) => w.includes('scripts/test.sh')));
  assert.deepEqual(withAnswer.clarify, clarify);
  assert.equal(without.clarify, undefined);
});
