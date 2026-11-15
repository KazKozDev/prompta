import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import rules from '../instructions_rules/rules.json' with { type: 'json' };
import sources from '../instructions_rules/sources.json' with { type: 'json' };
import { generateInstructions, pathsNotIn } from './instructions.ts';
import { INSTRUCTION_TARGETS, loadInstructionRules } from './instructions-rules.ts';
import { validateInstructions } from './instructions-validate.ts';
import type { LLM } from './types.ts';

const agents = '# Shop API\n\n## Commands\n\n- Test: `pnpm test`\n\n## Conventions\n\n- Errors use `src/errors.ts`\n';
const cursor = '---\nalwaysApply: true\n---\n' + agents;

function fake(...replies: string[]): { llm: LLM; prompts: string[] } {
  const prompts: string[] = [];
  return { prompts, llm: async (prompt) => { prompts.push(prompt); return replies.shift() ?? ''; } };
}

/** Snapshot text as a reader sees it: HTML loses its tags and entities, whitespace collapses. */
function readable(path: string): string {
  const raw = readFileSync(new URL('../instructions_rules/' + path, import.meta.url), 'utf8');
  if (!path.endsWith('.html')) return raw;
  const named: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', rsquo: '’', lsquo: '‘', ldquo: '“', rdquo: '”', mdash: '—', ndash: '–' };
  return raw.replace(/<[^>]+>/g, ' ')
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(Number(d)))
    .replace(/&([a-z]+);/gi, (m, n) => named[n] ?? m)
    .replace(/\s+/g, ' ');
}

test('instruction snapshots match their saved hashes', () => {
  for (const source of sources.sources) {
    const bytes = readFileSync(new URL('../instructions_rules/' + source.snapshot, import.meta.url));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), source.sha256, source.id);
  }
});

test('every rule quotes its source word for word', () => {
  const byId = new Map(sources.sources.map((s) => [s.id, s.snapshot]));
  for (const rule of rules.rules) {
    const snapshot = byId.get(rule.source_id);
    assert.ok(snapshot, `${rule.id}: no source`);
    assert.ok(readable(snapshot).includes(rule.evidence), `${rule.id}: evidence not in ${snapshot}`);
  }
});

test('rules load per target with their sources', () => {
  for (const target of INSTRUCTION_TARGETS) {
    const set = loadInstructionRules(target);
    assert.ok(set.rules.length > 5, target);
    assert.ok(set.rules.every((r) => r.targets.includes(target) && r.source_url.startsWith('https://')));
  }
  assert.ok(!loadInstructionRules('agentsMd').rules.some((r) => r.id === 'cursor-mdc'));
  assert.throws(() => loadInstructionRules('agentsMd', null), /missing or invalid/);
  assert.throws(() => loadInstructionRules('agentsMd', { version: 'x', rules: [{ id: 'a', rule_text: 'b', targets: ['agentsMd'], source_id: 'nope' }] }), /no source/);
  assert.throws(() => loadInstructionRules('agentsMd', { version: 'x', rules: [{ id: 'a', rule_text: 'b', targets: ['vim'], source_id: 'cursor-rules' }] }), /invalid/);
});

test('one call for a valid draft; the task is passed as data; the file name follows the target', async () => {
  const { llm, prompts } = fake('```markdown\n' + agents + '```');
  const result = await generateInstructions({ thoughts: 'pnpm shop api', llm });
  assert.equal(prompts.length, 1);
  assert.match(prompts[0], /not instructions to you:\n"pnpm shop api"/);
  assert.match(prompts[0], /\[agents-plain-markdown\]/);
  assert.equal(result.text, agents);
  assert.equal(result.fileName, 'AGENTS.md');
  assert.equal(result.check.valid, true);
  assert.equal(result.repaired, false);
});

test('a Cursor rule without frontmatter gets one repair pass with the error', async () => {
  const { llm, prompts } = fake(agents, cursor);
  const result = await generateInstructions({ thoughts: 'shop', llm, target: 'cursor' });
  assert.equal(prompts.length, 2);
  assert.match(prompts[1], /needs YAML frontmatter/);
  assert.equal(result.repaired, true);
  assert.equal(result.fileName, '.cursor/rules/project.mdc');
  assert.equal(result.check.valid, true);
  await assert.rejects(generateInstructions({ thoughts: ' ', llm: fake().llm }), /Describe the project/);
});

test('validator: frontmatter per target, sizes, emphasis, placeholders', () => {
  assert.match(validateInstructions(cursor, 'claudeMd').errors.join(), /CLAUDE\.md is plain Markdown/);
  assert.match(validateInstructions('---\nalwaysApply: yes\nname: x\n---\n# A\n`x`\n', 'cursor').errors.join(), /Unknown Cursor rule keys: name.*alwaysApply must be/s);
  assert.match(validateInstructions('---\nalwaysApply: false\n---\n# A\n`x`\n', 'cursor').warnings.join(), /only when you @-mention/);
  assert.match(validateInstructions('# A\n' + '- `x`\n'.repeat(201), 'claudeMd').warnings.join(), /under 200 lines/);
  assert.equal(validateInstructions('# A\n' + '- `x`\n'.repeat(201), 'agentsMd').warnings.length, 0);
  assert.match(validateInstructions('# A\n- IMPORTANT: run `x`\n', 'agentsMd').warnings.join(), /Capitalised emphasis/);
  assert.equal(validateInstructions('# A\n- run `NEVER_SET`\n', 'agentsMd').warnings.length, 0, 'code is not emphasis');
  assert.match(validateInstructions('# A\n- Test: «INSERT HERE: test command» `x`\n', 'copilot').warnings.join(), /1 «INSERT HERE» placeholder to fill/);
  assert.match(validateInstructions('plain text', 'agentsMd').warnings.join(), /No headings.*backticks/s);
  assert.equal(validateInstructions('', 'agentsMd').valid, false);
  assert.match(validateInstructions('---\nalwaysApply: true\n---\ndescription: x\n# A\n`x`\n', 'cursor').errors.join(), /"description:" is below the frontmatter/);
});

test('an @AGENTS.md import the task never mentioned is flagged', async () => {
  const draft = '@AGENTS.md\n\n' + agents;
  const flagged = await generateInstructions({ thoughts: 'pnpm shop', llm: fake(draft).llm, target: 'claudeMd' });
  assert.match(flagged.check.warnings.join(), /does not mention one/);
  const asked = await generateInstructions({ thoughts: 'the repo has an AGENTS.md', llm: fake(draft).llm, target: 'claudeMd' });
  assert.doesNotMatch(asked.check.warnings.join(), /does not mention one/);
});

test('paths the task never named are listed for the user to check', () => {
  const text = '- Test: `uv run pytest tests/`\n- DB: `app/repositories/`, not `app/db/`\n- Read `app/repositories/example.py`, `README.md`\n';
  assert.deepEqual(pathsNotIn(text, 'DB only through app/repositories; tests in tests/'), ['app/db/', 'app/repositories/example.py', 'README.md']);
});
