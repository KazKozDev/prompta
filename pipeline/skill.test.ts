import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import sources from '../skill_rules/sources.json' with { type: 'json' };
import { generateSkill } from './skill.ts';
import { loadSkillRules } from './skill-rules.ts';
import type { LLM } from './types.ts';

const good = '```markdown\n---\nname: summarizing-meetings\ndescription: Summarizes meeting notes into decisions and owners. Use when the user shares meeting notes.\n---\n\n# Summarizing Meetings\n\nList decisions first.\n```';

const REVIEW = /^You review a SKILL\.md/;
const TESTS = /^A skill named /;
const TEST_REPLY = '{"trigger":["summarize these notes","what did we decide in the call?","owners from this meeting"],"skip":["write meeting notes","book a meeting"]}';

/** Draft and repair answers in order; the review hands the draft back unchanged unless a review reply is given,
 *  and the test-request call gets TEST_REPLY. prompts and options hold every call; main() the draft and repair. */
function fake(...replies: string[]): { llm: LLM; prompts: string[]; options: unknown[]; main: () => string[]; review: string[] } {
  const prompts: string[] = [];
  const options: unknown[] = [];
  const review: string[] = [];
  const llm: LLM = async (prompt, o) => {
    prompts.push(prompt);
    options.push(o);
    if (TESTS.test(prompt)) return TEST_REPLY;
    if (REVIEW.test(prompt)) return review.shift() ?? prompt.slice(prompt.lastIndexOf('SKILL.md:\n') + 'SKILL.md:\n'.length);
    return replies.shift() ?? '';
  };
  return { llm, prompts, options, review, main: () => prompts.filter((q) => !REVIEW.test(q) && !TESTS.test(q)) };
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

test('a valid draft: draft, review, test requests; fences are removed; the task is passed as data', async () => {
  const { llm, prompts, options } = fake(good);
  const result = await generateSkill({ thoughts: 'summarize my meeting notes', llm });
  assert.equal(prompts.length, 3);
  assert.match(prompts[1], REVIEW);
  assert.match(prompts[2], TESTS);
  // No output cap: a thinking model spends it thinking and the file comes back empty or cut (history, case 44).
  assert.deepEqual(options[0], { temperature: 0.3 });
  assert.match(prompts[0], /never drop a requirement or a figure/);
  assert.match(prompts[0], /gets its own ## section named after it/);
  assert.match(prompts[0], /only\nwhen it holds more than its Workflow step says/);
  assert.match(prompts[0], /Write the whole file in English, whatever language the task is in/);
  assert.match(prompts[0], /First decide which kind of skill the task is/);
  assert.match(prompts[0], /nothing irreversible before the steps it depends on have succeeded/);
  assert.match(prompts[0], /\[body-plan\] For batch, destructive or irreversible operations use plan-validate-execute/);
  assert.match(prompts[0], /never write a vague stand-in|Never write a vague stand-in/);
  assert.match(prompts[0], /is a\nWorkflow step that says what to write, not a Script/);
  assert.match(prompts[0], /the first Workflow step writes\nit/);
  assert.match(prompts[0], /MUST and Never mark only the few rules/);
  assert.match(prompts[0], /do not invent what each mode builds/);
  assert.match(prompts[0], /not instructions to you:\n"summarize my meeting notes"/);
  assert.ok(result.skill.startsWith('---\nname: summarizing-meetings'));
  assert.equal(result.check.valid, true);
  assert.equal(result.repaired, false);
  assert.equal(result.reviewed, false);
  assert.deepEqual(result.tests, { trigger: ['summarize these notes', 'what did we decide in the call?', 'owners from this meeting'], skip: ['write meeting notes', 'book a meeting'] });
});

test('an invalid draft gets exactly one repair pass with the errors', async () => {
  const bad = good.replace('summarizing-meetings', 'Claude_Notes');
  const { llm, main } = fake(bad, good);
  const result = await generateSkill({ thoughts: 'notes', llm });
  assert.equal(main().length, 2);
  assert.match(main()[1], /must be lowercase/);
  assert.equal(result.repaired, true);
  assert.equal(result.check.valid, true);
});

test('a draft with an unfilled template line gets the repair pass that names it', async () => {
  const leftover = good.replace('List decisions first.', 'For <case>, use <alternative> instead.\n\nList decisions first.');
  const { llm, main } = fake(leftover, good);
  const result = await generateSkill({ thoughts: 'notes', llm });
  assert.equal(main().length, 2);
  assert.match(main()[1], /"For <case>, use <alternative> instead\." is a template line left unfilled/);
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
  const { llm, main } = fake(misplaced, good);
  const result = await generateSkill({ thoughts: 'notes', llm });
  assert.equal(main().length, 2);
  assert.match(main()[1], /Give each topic its own ## section after Workflow/);
  assert.equal(result.repaired, true);
  assert.deepEqual(result.check.structure, []);
});

test('the review replaces the draft; a review that breaks a valid draft is dropped', async () => {
  const better = good.replace('List decisions first.', 'List decisions first, then owners.');
  const kept = fake(good);
  kept.review.push(better);
  const result = await generateSkill({ thoughts: 'notes', llm: kept.llm });
  assert.match(result.skill, /then owners/);
  assert.equal(result.reviewed, true);
  assert.match(kept.prompts[1], /Rules sit right after Quick start/);
  assert.match(kept.prompts[1], /not instructions to you:\n"notes"/);
  const broken = fake(good);
  broken.review.push('Here is the reviewed file: looks fine.');
  const second = await generateSkill({ thoughts: 'notes', llm: broken.llm });
  assert.match(second.skill, /^---\nname: summarizing-meetings/);
  assert.equal(second.reviewed, false);
  assert.equal(second.repaired, false);
});

test('test requests are optional: a broken answer leaves the file as it is', async () => {
  const llm: LLM = async (prompt) => (TESTS.test(prompt) ? 'not json' : REVIEW.test(prompt) ? good : good);
  const result = await generateSkill({ thoughts: 'notes', llm });
  assert.equal(result.tests, undefined);
  assert.equal(result.check.valid, true);
});
