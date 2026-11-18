import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import sources from '../skill_rules/sources.json' with { type: 'json' };
import { generateSkill } from './skill.ts';
import { loadSkillRules } from './skill-rules.ts';
import type { LLM } from './types.ts';

const good = '```markdown\n---\nname: summarizing-meetings\ndescription: Summarizes meeting notes into decisions and owners. Use when the user shares meeting notes.\n---\n\n# Summarizing Meetings\n\nList decisions first.\n```';

function fake(...replies: string[]): { llm: LLM; prompts: string[]; options: unknown[] } {
  const prompts: string[] = [];
  const options: unknown[] = [];
  return { prompts, options, llm: async (prompt, o) => { prompts.push(prompt); options.push(o); return replies.shift() ?? ''; } };
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
  const { llm, prompts, options } = fake(good);
  const result = await generateSkill({ thoughts: 'summarize my meeting notes', llm });
  assert.equal(prompts.length, 1);
  // No output cap: a thinking model spends it thinking and the file comes back empty or cut (history, case 44).
  assert.deepEqual(options[0], { temperature: 0.3 });
  assert.match(prompts[0], /never drop a requirement or a figure/);
  assert.match(prompts[0], /Each topic of the task gets its own ## section/);
  assert.match(prompts[0], /is a\nWorkflow step that says what to write, not a Script/);
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

test('a draft with an unfilled template line gets the repair pass that names it', async () => {
  const leftover = good.replace('List decisions first.', 'For <case>, use <alternative> instead.\n\nList decisions first.');
  const { llm, prompts } = fake(leftover, good);
  const result = await generateSkill({ thoughts: 'notes', llm });
  assert.equal(prompts.length, 2);
  assert.match(prompts[1], /"For <case>, use <alternative> instead\." is a template line left unfilled/);
  assert.equal(result.repaired, true);
  assert.deepEqual(result.check.leftovers, []);
});

test('a still-invalid repair is returned with its errors, not hidden', async () => {
  const bad = good.replace('summarizing-meetings', 'Bad Name');
  const result = await generateSkill({ thoughts: 'notes', llm: fake(bad, bad).llm });
  assert.equal(result.check.valid, false);
  assert.ok(result.check.errors.length > 0);
  await assert.rejects(generateSkill({ thoughts: '  ', llm: fake().llm }), /Describe the skill/);
});

test('a draft with the spec under Additional resources gets the repair pass that says where it goes', async () => {
  const misplaced = good.replace('List decisions first.', 'List decisions first.\n\n## Additional resources\n\nOwners: one per decision.');
  const { llm, prompts } = fake(misplaced, good);
  const result = await generateSkill({ thoughts: 'notes', llm });
  assert.equal(prompts.length, 2);
  assert.match(prompts[1], /Give each topic its own ## section after Workflow/);
  assert.equal(result.repaired, true);
  assert.deepEqual(result.check.structure, []);
});
