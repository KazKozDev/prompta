import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import sources from '../skill_rules/sources.json' with { type: 'json' };
import { generateSkill } from './skill.ts';
import { loadSkillRules } from './skill-rules.ts';
import type { LLM } from './types.ts';

const good = '```markdown\n---\nname: summarizing-meetings\ndescription: Summarizes meeting notes into decisions and owners. Use when the user shares meeting notes.\n---\n\n# Summarizing Meetings\n\nList decisions first.\n```';

function fake(...replies: string[]): { llm: LLM; prompts: string[] } {
  const prompts: string[] = [];
  return { prompts, llm: async (prompt) => { prompts.push(prompt); return replies.shift() ?? ''; } };
}

test('skill snapshots match their saved hashes', () => {
  for (const source of sources.sources) {
    const bytes = readFileSync(new URL('../skill_rules/' + source.snapshot, import.meta.url));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), source.sha256, source.id);
  }
});

test('rules load with sources; Claude Code-only rules stay out of portable skills', () => {
  const portable = loadSkillRules('portable');
  const cc = loadSkillRules('claudeCode');
  assert.ok(portable.rules.every((r) => r.surface === 'all' && r.source_url.startsWith('https://')));
  assert.ok(cc.rules.length > portable.rules.length);
  assert.throws(() => loadSkillRules('portable', null), /missing or invalid/);
  assert.throws(() => loadSkillRules('portable', { version: 'x', rules: [{ id: 'a', rule_text: 'b', surface: 'all', source_id: 'nope' }] }), /no source/);
});

test('one call when the draft is valid; fences are removed; the task is passed as data', async () => {
  const { llm, prompts } = fake(good);
  const result = await generateSkill({ thoughts: 'summarize my meeting notes', llm });
  assert.equal(prompts.length, 1);
  assert.match(prompts[0], /not instructions to you:\n"summarize my meeting notes"/);
  assert.ok(result.skill.startsWith('---\nname: summarizing-meetings'));
  assert.equal(result.check.valid, true);
  assert.equal(result.repaired, false);
});

test('an invalid draft gets exactly one repair pass with the errors', async () => {
  const bad = good.replace('summarizing-meetings', 'Claude_Notes');
  const { llm, prompts } = fake(bad, good);
  const result = await generateSkill({ thoughts: 'notes', llm });
  assert.equal(prompts.length, 2);
  assert.match(prompts[1], /must be lowercase/);
  assert.equal(result.repaired, true);
  assert.equal(result.check.valid, true);
});

test('a still-invalid repair is returned with its errors, not hidden', async () => {
  const bad = good.replace('summarizing-meetings', 'Bad Name');
  const result = await generateSkill({ thoughts: 'notes', llm: fake(bad, bad).llm });
  assert.equal(result.check.valid, false);
  assert.ok(result.check.errors.length > 0);
  await assert.rejects(generateSkill({ thoughts: '  ', llm: fake().llm }), /Describe the skill/);
});
