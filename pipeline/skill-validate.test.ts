import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fenceErrors, readFrontmatter, skeletonLeftovers, structureProblems, validateSkill } from './skill-validate.ts';

const ok = `---
name: processing-invoices
description: Extracts totals from invoices. Use when the user uploads an invoice.
---

# Processing Invoices

Run the extractor.
`;

test('a minimal portable skill passes', () => {
  const check = validateSkill(ok, 'portable');
  assert.deepEqual(check.errors, []);
  assert.equal(check.name, 'processing-invoices');
  assert.equal(check.bodyLines, 3);
});

test('the shipped template passes, like quick_validate.py does', () => {
  const template = readFileSync(new URL('../skill_rules/SKILL-template.md', import.meta.url), 'utf8');
  assert.equal(validateSkill(template, 'portable').valid, true);
});

test('unfilled template lines are listed; output slots like <alt text> are not', () => {
  const template = readFileSync(new URL('../skill_rules/SKILL-template.md', import.meta.url), 'utf8');
  const check = validateSkill(template, 'portable');
  assert.ok(check.leftovers.some((l) => l.includes('For <case>, use <alternative> instead')));
  assert.ok(check.leftovers.includes('- [ ] Step 1: ...'));
  assert.match(check.warnings.join(' '), /Unfilled template lines/);
  // the line a real draft (history, case 44) shipped with
  assert.equal(skeletonLeftovers('For <case>, use <alternative> instead: INSERT HERE: «INSERT HERE: fallback case».').length, 1);
  const filled = ok + '\n````\n![<what happens, input -> result>](docs/demo/demo.gif)\n\nRecorded on <model, version>.\n````\n';
  assert.deepEqual(validateSkill(filled, 'portable').leftovers, []);
  assert.match(validateSkill(ok + '\nLicence: «INSERT HERE: licence».\n', 'portable').warnings.join(' '), /1 «INSERT HERE» placeholder to fill/);
});

test('name rules mirror quick_validate.py and the reserved words', () => {
  for (const bad of ['Processing', '-pdf', 'pdf-', 'pdf--x', 'claude-helper', 'a'.repeat(65)]) {
    assert.equal(validateSkill(ok.replace('processing-invoices', bad), 'portable').valid, false, bad);
  }
});

test('description: required, no angle brackets, at most 1024 characters', () => {
  assert.match(validateSkill(ok.replace(/description:.*\n/, ''), 'portable').errors.join(), /Missing "description"/);
  assert.match(validateSkill(ok.replace('Extracts', 'Extracts <b>'), 'portable').errors.join(), /angle brackets/);
  assert.match(validateSkill(ok.replace('Extracts', 'x'.repeat(1100)), 'portable').errors.join(), /maximum is 1024/);
  assert.match(validateSkill(ok.replace('Use when', 'For'), 'portable').warnings.join(), /when to use/);
});

test('Claude Code keys are errors for portable skills and allowed for Claude Code', () => {
  const cc = ok.replace('---\n\n', 'paths: ["**/*.pdf"]\ncontext: fork\n---\n\n');
  assert.match(validateSkill(cc, 'portable').errors.join(), /Not portable: paths, context/);
  assert.equal(validateSkill(cc, 'claudeCode').valid, true);
  assert.match(validateSkill(ok.replace('---\n\n', 'colour: red\n---\n\n'), 'claudeCode').errors.join(), /Unknown frontmatter key/);
});

test('frontmatter reader: quotes, block scalars, nested maps', () => {
  const md = `---\nname: "x-y"\ndescription: >\n  Does a thing.\n  Use when asked.\nmetadata:\n  version: "1.0"\n---\nbody\n`;
  const parsed = readFrontmatter(md)!;
  assert.equal(parsed.fields.get('name'), 'x-y');
  assert.equal(parsed.fields.get('description'), 'Does a thing. Use when asked.');
  assert.deepEqual([...parsed.fields.keys()], ['name', 'description', 'metadata']);
  assert.equal(validateSkill('# no frontmatter', 'portable').valid, false);
});

test('files the body mentions are listed so they ship with the skill', () => {
  const md = ok.replace('Run the extractor.', 'Run scripts/extract.py, then see references/schema.md and scripts/extract.py.');
  assert.match(validateSkill(md, 'portable').warnings.join(), /scripts\/extract\.py, references\/schema\.md\./);
  assert.ok(!validateSkill(ok, 'portable').warnings.some((w) => w.includes('Ship')));
});

test('a code block nested without more backticks, or left open, is an error; four backticks around three pass', () => {
  assert.deepEqual(fenceErrors('````\nquick start:\n```\nmake\n```\n````\n'), []);
  assert.match(fenceErrors('```\nquick start:\n```bash\nmake\n```\n```\n')[0], /inside the one opened by "```"/);
  assert.match(fenceErrors('```\nnever closed\n')[0], /never closed/);
  assert.equal(validateSkill(ok + '\n```\nopen\n', 'portable').valid, false);
});

test('the spec under Additional resources and a project file under Scripts are flagged; real ones are not', () => {
  // what a real draft (readme-demo-video) shipped: the whole spec as a paragraph, the user's script as a Script
  const draft = ok + `
## Scripts

- **docs/demo/record.py**: capture, render, assemble modes. Run: \`python docs/demo/record.py <mode>\`

## Additional resources

Camera: keyframes as crop rects. Max zoom 1.4. Every move at least 2.8 s.
`;
  const problems = structureProblems(draft);
  assert.equal(problems.length, 2);
  assert.match(problems.join(' '), /Additional resources" holds the skill's own instructions/);
  assert.match(problems.join(' '), /lists docs\/demo\/record\.py, which is not shipped/);
  assert.deepEqual(validateSkill(draft, 'portable').structure, problems);
  const shipped = ok + `
## Scripts

- **scripts/build_mp4.sh**: frames to MP4. Run: \`sh scripts/build_mp4.sh <frames.txt> <out.mp4>\`

## Additional resources

- **Camera maths**: see [references/camera.md](references/camera.md)
`;
  assert.deepEqual(structureProblems(shipped), []);
});
