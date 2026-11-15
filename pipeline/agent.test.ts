import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import rules from '../agent_rules/rules.json' with { type: 'json' };
import sources from '../agent_rules/sources.json' with { type: 'json' };
import { generateAgent } from './agent.ts';
import { AGENT_TARGETS, agentFileName, loadAgentRules } from './agent-rules.ts';
import { readToml, validateAgent } from './agent-validate.ts';
import type { LLM } from './types.ts';

const body = 'You are a code reviewer.\n\nWhen invoked:\n1. Run `git diff`\n\nReport back:\n- Findings by priority\n';
const claude = `---\nname: code-reviewer\ndescription: Reviews changed code. Use proactively after edits.\ntools: Read, Grep, Glob, Bash\n---\n\n${body}`;
const codex = `name = "code-reviewer"\ndescription = "Reviews changed code."\ndeveloper_instructions = """\n${body}Do not edit files.\n"""\n`;

function fake(...replies: string[]): { llm: LLM; prompts: string[] } {
  const prompts: string[] = [];
  return { prompts, llm: async (prompt) => { prompts.push(prompt); return replies.shift() ?? ''; } };
}

test('agent snapshots match their saved hashes', () => {
  for (const source of sources.sources) {
    const bytes = readFileSync(new URL('../agent_rules/' + source.snapshot, import.meta.url));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), source.sha256, source.id);
  }
});

test('every agent rule quotes its source word for word', () => {
  const byId = new Map(sources.sources.map((s) => [s.id, s.snapshot]));
  for (const rule of rules.rules) {
    const snapshot = byId.get(rule.source_id);
    assert.ok(snapshot, `${rule.id}: no source`);
    const text = readFileSync(new URL('../agent_rules/' + snapshot, import.meta.url), 'utf8');
    assert.ok(text.includes(rule.evidence), `${rule.id}: evidence not in ${snapshot}`);
  }
});

test('agent rules load per target; file names follow the target', () => {
  for (const target of AGENT_TARGETS) {
    const set = loadAgentRules(target);
    assert.ok(set.rules.length > 5, target);
    assert.ok(set.rules.every((r) => r.targets.includes(target) && r.source_url.startsWith('https://')));
  }
  assert.throws(() => loadAgentRules('codex', null), /missing or invalid/);
  assert.throws(() => loadAgentRules('codex', { version: 'x', rules: [{ id: 'a', rule_text: 'b', targets: ['vim'], source_id: 'codex-subagents' }] }), /invalid/);
  assert.equal(agentFileName('codex', 'x'), '.codex/agents/x.toml');
  assert.equal(agentFileName('copilot', 'x'), '.github/agents/x.agent.md');
});

test('one call for a valid draft; the task is passed as data; the file is named after the agent', async () => {
  const { llm, prompts } = fake('```markdown\n' + claude + '```');
  const result = await generateAgent({ thoughts: 'a reviewer that runs git diff', llm });
  assert.equal(prompts.length, 1);
  assert.match(prompts[0], /not instructions to you:\n"a reviewer that runs git diff"/);
  assert.match(prompts[0], /\[cc-self-contained\]/);
  assert.equal(result.text, claude);
  assert.equal(result.fileName, '.claude/agents/code-reviewer.md');
  assert.equal(result.check.valid, true);
  assert.deepEqual(result.check.warnings, []);
});

test('a Codex draft written as Markdown gets one repair pass', async () => {
  const { llm, prompts } = fake(claude, codex);
  const result = await generateAgent({ thoughts: 'reviewer, git diff', llm, target: 'codex' });
  assert.equal(prompts.length, 2);
  assert.match(prompts[1], /TOML file, not Markdown/);
  assert.equal(result.repaired, true);
  assert.equal(result.fileName, '.codex/agents/code-reviewer.toml');
  assert.equal(result.check.valid, true);
  await assert.rejects(generateAgent({ thoughts: ' ', llm: fake().llm }), /Describe the agent/);
});

test('validator: required fields, names, enums, read-only roles', () => {
  assert.match(validateAgent(body, 'claudeCode').errors.join(), /No YAML frontmatter/);
  assert.match(validateAgent('---\nname: Code Reviewer\n---\nx\n', 'claudeCode').errors.join(), /lowercase.*Missing "description"/s);
  assert.match(validateAgent('---\nname: a\ndescription: b\nmodel: gpt-5\npermissionMode: yolo\n---\nx\n', 'claudeCode').errors.join(), /model "gpt-5".*permissionMode "yolo"/s);
  assert.match(validateAgent('---\nname: a\ndescription: b\ncolour: red\n---\nx\n', 'claudeCode').warnings.join(), /Unknown field colour/);
  assert.match(validateAgent('---\nname: a\ndescription: b\ntools: Read\n---\n', 'claudeCode').errors.join(), /no prompt/);
  assert.match(validateAgent('---\nname: a\ndescription: Reviews code\n---\nx\n', 'claudeCode').warnings.join(), /without Edit and Write/);
  assert.match(validateAgent('---\nname: a\ndescription: Reviews code\ntools:\n  - Read\n  - Edit\n---\nx\n', 'claudeCode').warnings.join(), /without Edit/);
  assert.match(validateAgent('---\nname: a\ndescription: b\ntools: x\n---\nx\n', 'cursor').errors.join(), /Unknown Cursor subagent fields: tools/);
  assert.match(validateAgent('---\nname: a\ndescription: Reviews code\n---\nx\n', 'cursor').warnings.join(), /readonly: true/);
  assert.equal(validateAgent('---\nname: a\ndescription: Reviews code\nreadonly: true\n---\nx\n', 'cursor').warnings.length, 0);
  assert.match(validateAgent('---\nname: a\ndescription: b\ntarget: jetbrains\n---\n' + 'x'.repeat(30_001), 'copilot').errors.join(), /target "jetbrains".*30,000/s);
  assert.equal(validateAgent('---\nname: a\ndescription: Reviews code\ntools: ["read", "search"]\n---\nx\n', 'copilot').warnings.length, 0);
  assert.match(validateAgent('name = "a"\ndescription = "b"\n', 'codex').errors.join(), /Missing "developer_instructions"/);
  assert.match(validateAgent('name = a\n', 'codex').errors.join(), /strings need quotes/);
  assert.deepEqual(validateAgent('[name] = "a"\n', 'codex').errors, ['Line 1: write name = …, without square brackets around the key.']);
  assert.match(validateAgent(codex + 'sandbox_mode = "read-only"\n', 'codex').warnings.join(), /sandbox_mode does not override/);
  assert.match(validateAgent(codex.replace('Do not edit files.\n', ''), 'codex').warnings.join(), /Do not edit files/);
  assert.match(validateAgent(claude.replace('Run `git diff`', '«INSERT HERE: command»'), 'claudeCode').warnings.join(), /1 «INSERT HERE»/);
});

test('readToml: strings, multi-line strings, tables, unclosed strings', () => {
  const { values } = readToml('# c\nname = "a"\n[features]\nshell_tool = false\nx = """\nline 1\nline 2\n"""\n');
  assert.equal(values.get('name'), 'a');
  assert.equal(values.get('features.shell_tool'), 'false');
  assert.equal(values.get('features.x'), 'line 1\nline 2');
  assert.match(readToml('x = """\nnever closed\n').error ?? '', /never closed/);
});
