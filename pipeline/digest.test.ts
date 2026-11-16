import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';

import { BRIEF_CHARS, digestFiles, rankFiles, shrink } from './digest.ts';
import type { DigestFile } from './digest.ts';

const BUDGET = 24_000;
const PER_FILE = 8_000;

test('digest: a short file is shown whole, a long one by its outline', () => {
  const small = { path: 'a.md', content: '# A\nshort' };
  assert.deepEqual(shrink(small, 100), { header: '=== a.md ===', body: '# A\nshort', use: 'whole' });
  const long = { path: 'guide.md', content: `# Guide\nWhat it is.\n\n${'filler text. '.repeat(400)}\n\n## Install\nRun it:\n\n\`\`\`bash\nnpm install\n\`\`\`\n\n${'more text. '.repeat(400)}` };
  const shown = shrink(long, 600);
  assert.equal(shown.use, 'outline');
  assert.match(shown.header, /^=== guide\.md \(outline of \d+ lines\) ===$/);
  assert.match(shown.body, /# Guide\nWhat it is\./);
  assert.match(shown.body, /## Install/);
  assert.match(shown.body, /npm install/);
  assert.ok(shown.body.length <= 600);
});

test('digest: code keeps its signatures, not its bodies', () => {
  const code = [
    '"""Billing: invoices and refunds."""',
    'import os',
    '',
    'class Invoice:',
    '    def total(self, tax: float) -> float:',
    ...Array.from({ length: 200 }, (_, i) => `        value_${i} = compute(${i})`),
    '        return 0',
    '',
    'def refund(invoice: Invoice, reason: str) -> None:',
    '    if reason:',
    '        pass',
  ].join('\n');
  const shown = shrink({ path: 'billing.py', content: code }, 400);
  assert.match(shown.body, /Billing: invoices and refunds/);
  assert.match(shown.body, /^class Invoice:$/m);
  assert.match(shown.body, /def total\(self, tax: float\) -> float:/);
  assert.match(shown.body, /^def refund\(invoice: Invoice, reason: str\) -> None:$/m);
  assert.doesNotMatch(shown.body, /value_|if reason/);
});

test('digest: TypeScript exports and class methods, no local consts or control flow', () => {
  const code = [
    "import { x } from './x.ts';",
    'export const LIMIT = 10;',
    'export function build(request: string): string {',
    '  const local = 1;',
    '  if (local) {',
    ...Array.from({ length: 300 }, (_, i) => `    call(${i});`),
    '  }',
    '}',
    'export class Store {',
    '  async load(id: string): Promise<void> {',
    '  }',
    '}',
  ].join('\n');
  const body = shrink({ path: 'src/store.ts', content: code }, 500).body;
  for (const line of ['export const LIMIT = 10;', 'export function build(request: string): string {', 'export class Store {', '  async load(id: string): Promise<void> {']) {
    assert.ok(body.includes(line), `missing: ${line}`);
  }
  assert.doesNotMatch(body, /const local|if \(local|call\(/);
});

test('digest: package.json keeps its name and scripts, makefile its targets', () => {
  const pkg = JSON.stringify({ name: 'demo', scripts: { test: 'node --test', build: 'tsc' }, dependencies: Object.fromEntries(Array.from({ length: 300 }, (_, i) => [`dep-${i}`, '^1.0.0'])) }, null, 2);
  const body = shrink({ path: 'package.json', content: pkg }, 300).body;
  assert.match(body, /name: "demo"/);
  assert.match(body, /scripts\.test: "node --test"/);
  assert.match(body, /scripts\.build: "tsc"/);
  const make = `build:\n\tgo build ./...\n${'\t# step\n'.repeat(300)}test: build\n\tgo test ./...\n`;
  const makeBody = shrink({ path: 'Makefile', content: make }, 200).body;
  assert.match(makeBody, /^build:$/m);
  assert.match(makeBody, /^test: build$/m);
});

test('digest: a kind without an outline keeps its start', () => {
  const shown = shrink({ path: 'notes.txt', content: `BEGIN ${'x'.repeat(5_000)} END` }, 1_000);
  assert.match(shown.header, /\(start of 1 lines\)/);
  assert.match(shown.body, /^BEGIN x+\n\[…rest of the file omitted…\]$/);
});

test('digest: README and manifests outrank code and docs, which outrank data and tests', () => {
  const files = ['tests/test_app.py', 'rules/data.json', 'src/app.py', 'docs/guide.md', 'package.json', 'README.md'].map((path) => ({ path, content: 'x' }));
  const order = rankFiles('anything', files).map((i) => files[i]!.path);
  assert.deepEqual(order, ['package.json', 'README.md', 'src/app.py', 'docs/guide.md', 'rules/data.json', 'tests/test_app.py']);
});

test('digest: the root README beats a nested one and a fixture, whatever the request names', () => {
  const files = ['rules/snapshots/repo/AGENTS.md', 'docs/api/README.md', 'pkg/README.md', 'README.md'].map((path) => ({ path, content: 'x' }));
  const order = rankFiles('write AGENTS.md', files).map((i) => files[i]!.path);
  assert.deepEqual(order, ['README.md', 'pkg/README.md', 'docs/api/README.md', 'rules/snapshots/repo/AGENTS.md']);
});

test('digest: a long prose document keeps its opening text, not only its headings', () => {
  const prose = Array.from({ length: 120 }, (_, i) => `Paragraph ${i} explains one more part of the specification in plain words.`).join('\n\n');
  const shown = shrink({ path: 'spec.md', content: `# Spec\n\n${prose}\n\n## Appendix\nLast words.` }, PER_FILE);
  assert.ok(shown.body.length >= PER_FILE * 0.8, `only ${shown.body.length} characters kept`);
  assert.ok(shown.body.startsWith('# Spec\nParagraph 0 explains'));
  assert.match(shown.body, /## Appendix/, 'every heading stays');
});

test('digest: claude.ts and agents.py are code, CLAUDE.md and AGENTS.md are key files', () => {
  const files = ['pipeline/claude.ts', 'agents.py', 'CLAUDE.md', 'AGENTS.md'].map((path) => ({ path, content: 'x' }));
  const order = rankFiles('x', files).map((i) => files[i]!.path);
  assert.deepEqual(order.slice(0, 2), ['CLAUDE.md', 'AGENTS.md']);
});

test('digest: within a kind, the files the request names come first', () => {
  const files = [{ path: 'src/users.py', content: 'x' }, { path: 'src/billing.py', content: 'x' }, { path: 'src/report.py', content: 'mentions billing' }];
  const order = rankFiles('write a skill for billing refunds', files).map((i) => files[i]!.path);
  assert.deepEqual(order, ['src/billing.py', 'src/report.py', 'src/users.py']);
});

test('digest: many files stay within the budget, each listed in the tree', () => {
  const files: DigestFile[] = Array.from({ length: 150 }, (_, i) => ({
    path: `src/module_${String(i).padStart(3, '0')}.py`,
    content: `def handler_${i}(event):\n${'    work()\n'.repeat(400)}`,
  }));
  const { text, uses } = digestFiles('x', files, BUDGET, PER_FILE);
  assert.ok(text.length <= BUDGET, `digest too long: ${text.length}`);
  assert.match(text, /^=== file tree \(150 files\) ===\nsrc\/module_000\.py · 401 lines/);
  assert.match(text, /def handler_0\(event\):/);
  assert.ok(uses.filter((use) => use === 'outline').length > 50, 'most files get at least their outline');
});

test('digest: room left after every outline lets the best files grow', () => {
  const big = (path: string, tag: string) => ({ path, content: `# ${tag}\n\n${Array.from({ length: 300 }, (_, i) => `## ${tag} part ${i}\nText ${i}.`).join('\n\n')}` });
  const { text, uses } = digestFiles('x', [big('docs/b.md', 'Beta'), big('README.md', 'Alpha')], BUDGET, PER_FILE);
  assert.deepEqual(uses, ['outline', 'outline']);
  const readme = text.slice(text.indexOf('=== README.md'));
  assert.ok(text.indexOf('=== README.md') < text.indexOf('=== docs/b.md'), 'README first');
  assert.ok(readme.indexOf('=== docs/b.md') > BRIEF_CHARS * 2, 'README grew past the brief size');
});

test('digest: prompta itself, every source file attached, keeps the facts a skill needs', () => {
  const root = new URL('../', import.meta.url);
  const read = (path: string): DigestFile => ({ path, content: readFileSync(new URL(path, root), 'utf8') });
  const sources = [
    ...readdirSync(new URL('pipeline/', root)).filter((n) => n.endsWith('.ts')).map((n) => `pipeline/${n}`),
    ...readdirSync(new URL('desktop/', root)).filter((n) => n.endsWith('.py')).map((n) => `desktop/${n}`),
  ];
  const files = [...sources.map(read), read('package.json'), read('README.md')];
  const { text, uses } = digestFiles('write AGENTS.md for this repository', files, BUDGET, PER_FILE);
  assert.ok(text.length <= BUDGET);
  assert.match(text, /"test": "node --test/, 'package.json scripts');
  assert.match(text, /npm run pipeline -- /, 'a README command block');
  assert.match(text, /## Quick start/, 'README headings');
  assert.match(text, /export async function generateInstructions\(/, 'a pipeline signature');
  const shownTests = files.filter((file, i) => /(\.test\.ts|\/test_[^/]+\.py)$/.test(file.path) && uses[i] !== 'tree');
  assert.deepEqual(shownTests, [], 'tests come last: no room is left for them here');
  assert.match(text, new RegExp(`file tree \\(${files.length} files\\)`));
  const readme = text.slice(text.indexOf('=== README.md'), text.indexOf('\n\n=== ', text.indexOf('=== README.md')));
  assert.ok(readme.length > 5_000, `the README gets its full share, not a brief: ${readme.length}`);
});
