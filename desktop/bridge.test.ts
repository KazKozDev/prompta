import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

/** E2E process boundary: Python/UI calls the bridge exactly like this — JSON on stdin, JSON on stdout. */

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const bridge = join(root, 'desktop', 'bridge.ts');

function call(payload: unknown): { ok: boolean; data: Record<string, unknown>; stderr: string } {
  const result = spawnSync(process.execPath, [bridge], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    timeout: 60_000,
    cwd: root,
  });
  return {
    ok: result.status === 0,
    data: JSON.parse(result.stdout || '{}') as Record<string, unknown>,
    stderr: result.stderr ?? '',
  };
}

test('bridge: Enter your thoughts returns an error instead of crashing', () => {
  const { data } = call({ thoughts: '   ', model: 'dummy' });
  assert.equal(data.ok, false);
  assert.match(String(data.error), /Enter your thoughts/);
});

test('bridge: without a model it asks to specify one', () => {
  const { data } = call({ thoughts: 'сделай что-нибудь' });
  assert.equal(data.ok, false);
  assert.match(String(data.error), /model/);
});

test('bridge: technique list contains both ready and procedure ones', () => {
  const { data } = call({ thoughts: 'x', model: 'dummy', listTechniques: true });
  const techniques = data.techniques as { key: string; status: string; sources: { title: string; url: string; reference: string }[] }[];
  assert.ok(Array.isArray(techniques));
  assert.ok(techniques.length >= 80, `few techniques: ${techniques.length}`);
  for (const technique of techniques) {
    assert.ok(technique.sources.length > 0, technique.key);
    for (const source of technique.sources) {
      const url = new URL(source.url);
      assert.equal(url.protocol, 'https:');
      assert.ok(['archive.org', 'arxiv.org'].includes(url.hostname));
      assert.ok(source.title && source.reference);
    }
  }
  assert.ok(techniques.some((t) => t.status === 'ready'));
  assert.ok(techniques.some((t) => t.status === 'procedure'));
});

test('bridge: procedure returns steps, not a prompt', () => {
  const { data } = call({
    thoughts: 'отбери похожие примеры',
    provider: 'ollama',
    model: 'dummy',
    manualTechnique: 'icl_knn_selection',
  });
  const procedure = data.procedure as { steps: string[] };
  assert.equal(data.ok, true);
  assert.ok(Array.isArray(procedure.steps));
  assert.ok(procedure.steps.length >= 3);
  assert.equal(data.manual, undefined);
  assert.match(String((data.procedure as { zeroShotPrompt: string }).zeroShotPrompt), /отбери похожие примеры/);
});

test('bridge: every answer says how each attached file reached the model', () => {
  const small = [{ path: 'README.md', content: '# Shop' }, { path: 'src/app.py', content: 'def main(): pass' }];
  const fit = call({ thoughts: 'отбери похожие примеры', provider: 'ollama', model: 'dummy', manualTechnique: 'icl_knn_selection', files: small });
  assert.equal(fit.data.ok, true, JSON.stringify(fit.data));
  assert.deepEqual(fit.data.filesUsed, { 'README.md': 'whole', 'src/app.py': 'whole' });
  const big = (i: number) => ({ path: `notes/n${i}.txt`, content: `note ${i} ${'x'.repeat(20_000)}` });
  const many = call({ thoughts: 'отбери похожие примеры', provider: 'ollama', model: 'dummy', manualTechnique: 'icl_knn_selection', files: [small[0], ...Array.from({ length: 40 }, (_, i) => big(i))] });
  const used = many.data.filesUsed as Record<string, string>;
  assert.equal(used['README.md'], 'whole');
  assert.equal(used['notes/n0.txt'], 'outline', 'its start');
  assert.ok(Object.values(used).includes('tree'), 'forty long files do not all fit');
  assert.equal(call({ thoughts: 'отбери похожие примеры', provider: 'ollama', model: 'dummy', manualTechnique: 'icl_knn_selection' }).data.filesUsed, undefined);
});

test('bridge: manual technique does not ignore the LLM-synthesis ban', () => {
  const { data } = call({ thoughts: 'синтетический тест', model: 'dummy', manualTechnique: 'zero_shot', deterministic: true });
  assert.equal(data.ok, false);
  assert.match(String(data.error), /Disable Skip/);
});

test('bridge: Claude-only mode rejects manual and deterministic bypasses', () => {
  for (const extra of [{ manualTechnique: 'zero_shot' }, { deterministic: true }]) {
    const { data } = call({ thoughts: 'Synthetic parity test', model: 'dummy', claudeOnly: true, ...extra });
    assert.equal(data.ok, false);
    assert.match(String(data.error), /Claude mode/);
  }
});

test('bridge: all official modes reject conflicting flags, wrong types, and manual bypasses', () => {
  for (const extra of [
    { claudeOnly: true, chatgptOnly: true }, { chatgptOnly: true, geminiOnly: true },
    { chatgptOnly: 'true' }, { geminiOnly: 1 },
    { chatgptOnly: true, manualTechnique: 'zero_shot' }, { geminiOnly: true, manualTechnique: 'zero_shot' },
    { chatgptOnly: true, deterministic: true }, { geminiOnly: true, deterministic: true },
    { grokOnly: 'true' }, { grokOnly: true, claudeOnly: true },
    { grokOnly: true, manualTechnique: 'zero_shot' }, { grokOnly: true, deterministic: true },
  ]) {
    const { data } = call({ thoughts: 'Synthetic parity test', model: 'dummy', ...extra });
    assert.equal(data.ok, false);
    assert.match(String(data.error), /only one target|must be a boolean|cannot use a generic technique|cannot use a generic manual technique/);
  }
});


test('bridge: live progress stays on stderr and preserves the final JSON protocol', () => {
  const { data, stderr } = call({ thoughts: 'Select nearby examples', model: 'dummy',
    manualTechnique: 'icl_knn_selection', reportProgress: true });
  assert.equal(data.ok, true);
  assert.match(stderr, /PROMPTA_PROGRESS /);
  const update = JSON.parse(stderr.split('\n').find((line) => line.startsWith('PROMPTA_PROGRESS '))!.slice('PROMPTA_PROGRESS '.length));
  assert.equal(update.percent, 10);
  assert.equal(update.stage, 'Technique loaded');
});

test('bridge: several techniques — input validation before the model call', () => {
  const cases: [Record<string, unknown>, RegExp][] = [
    [{ manualTechniques: ['zero_shot'] }, /2–100 distinct/],
    [{ manualTechniques: ['zero_shot', 'zero_shot'] }, /2–100 distinct/],
    [{ manualTechniques: ['zero_shot', 42] }, /2–100 distinct/],
    [{ manualTechniques: ['zero_shot', 'few_shot'], manualTechnique: 'zero_shot' }, /2–100 distinct/],
    [{ manualTechniques: ['zero_shot', 'no_such_technique'] }, /Unknown technique/],
    [{ manualTechniques: ['zero_shot', 'icl_knn_selection'] }, /procedure and cannot be combined/],
    [{ manualTechniques: ['zero_shot', 'few_shot'], deterministic: true }, /requires LLM synthesis/],
    [{ manualTechniques: ['zero_shot', 'few_shot'], claudeOnly: true }, /cannot use generic manual techniques/],
  ];
  for (const [extra, error] of cases) {
    const { data } = call({ thoughts: 'синтетический тест', model: 'dummy', ...extra });
    assert.equal(data.ok, false, JSON.stringify(extra));
    assert.match(String(data.error), error, JSON.stringify(extra));
  }
});

test('bridge: "Select all" — more than 10 techniques pass validation, more than 100 do not', () => {
  const many = Array.from({ length: 101 }, (_, i) => `t${i}`);
  assert.match(String(call({ thoughts: 'x', model: 'dummy', manualTechniques: many }).data.error), /2–100 distinct/);
  const twelve = ['zero_shot', 'few_shot', 'system_prompting', 'role_prompting', 'contextual_prompting', 'prompt_chaining',
    'step_back_prompting', 'chain_of_thought', 'self_consistency', 'tree_of_thoughts', 'react', 'no_such'];
  assert.match(String(call({ thoughts: 'x', model: 'dummy', manualTechniques: twelve }).data.error), /Unknown technique: no_such/);
});

test('bridge: skill requests reject unknown surfaces and prompt targets before calling a model', () => {
  for (const payload of [
    { thoughts: 'x', model: 'dummy', skill: 'web' },
    { thoughts: 'x', model: 'dummy', skill: 'portable', claudeOnly: true },
    { thoughts: 'x', model: 'dummy', skill: 'portable', manualTechnique: 'few_shot' },
  ]) {
    const { data } = call(payload);
    assert.equal(data.ok, false);
    assert.match(String(data.error), /skill/i);
  }
});

test('bridge: instruction requests reject unknown targets, prompt targets and skills before calling a model', () => {
  for (const payload of [
    { thoughts: 'x', model: 'dummy', instructions: 'vim' },
    { thoughts: 'x', model: 'dummy', instructions: 'agentsMd', chatgptOnly: true },
    { thoughts: 'x', model: 'dummy', instructions: 'cursor', manualTechnique: 'few_shot' },
    { thoughts: 'x', model: 'dummy', instructions: 'claudeMd', skill: 'portable' },
  ]) {
    const { data } = call(payload);
    assert.equal(data.ok, false);
    assert.match(String(data.error), /instructions/i);
  }
});

test('bridge: agent requests reject unknown targets, prompt targets and other file modes before calling a model', () => {
  for (const payload of [
    { thoughts: 'x', model: 'dummy', agent: 'vim' },
    { thoughts: 'x', model: 'dummy', agent: 'codex', claudeOnly: true },
    { thoughts: 'x', model: 'dummy', agent: 'cursor', manualTechnique: 'few_shot' },
    { thoughts: 'x', model: 'dummy', agent: 'claudeCode', instructions: 'agentsMd' },
  ]) {
    const { data } = call(payload);
    assert.equal(data.ok, false);
    assert.match(String(data.error), /agent/i);
  }
});

test('bridge: project files without text or in invalid shape are rejected', () => {
  for (const files of ['README.md', [{ path: 'a.md' }], [{ path: '', content: 'x' }], Array.from({ length: 201 }, (_, i) => ({ path: `${i}.md`, content: 'x' })), Array.from({ length: 6 }, (_, i) => ({ path: `${i}.md`, content: 'x'.repeat(900_000) }))]) {
    const { data } = call({ thoughts: 'опиши проект', model: 'dummy', instructions: 'agentsMd', files });
    assert.equal(data.ok, false);
    assert.match(String(data.error), /files|file needs|MB of text/);
  }
});

test('bridge: file modes ask what is open first; Rebuild with the edited answers makes no clarify call', async () => {
  const { createServer } = await import('node:http');
  const { spawn } = await import('node:child_process');
  const prompts: string[] = [];
  const server = createServer((req, res) => {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      const prompt = String(JSON.parse(body).prompt);
      prompts.push(prompt);
      const answer = prompt.includes('First list what the request leaves open')
        ? JSON.stringify({ questions: [{ question: 'Which language?', default: 'English' }], assumptions: ['no badges'] })
        : '---\nname: writing-readmes\ndescription: Writes READMEs. Use when the user asks for a README.\n---\n\n# Writing READMEs\n\nWrite it.\n';
      res.end(JSON.stringify({ response: answer }));
    });
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address() as { port: number };
  const run = (payload: unknown) => new Promise<Record<string, any>>((resolve) => {
    const child = spawn(process.execPath, [bridge], { cwd: root });
    let out = '';
    child.stdout.on('data', (chunk) => { out += chunk; });
    child.on('close', () => resolve(JSON.parse(out || '{}')));
    child.stdin.end(JSON.stringify(payload));
  });
  try {
    const base = { thoughts: 'a README skill', provider: 'ollama', model: 'synthetic', baseUrl: `http://127.0.0.1:${port}`, skill: 'portable' };
    const first = await run(base);
    assert.equal(first.ok, true, JSON.stringify(first));
    assert.equal(prompts.length, 2, 'one clarify call, then the file');
    assert.deepEqual(first.skill.clarify, { questions: [{ question: 'Which language?', default: 'English' }], assumptions: ['no badges'] });
    assert.match(prompts[1], /"answer":"English"/);
    prompts.length = 0;
    const edited = { questions: [{ question: 'Which language?', default: 'Russian' }], assumptions: [] };
    const rebuilt = await run({ ...base, clarify: edited });
    assert.equal(rebuilt.ok, true, JSON.stringify(rebuilt));
    assert.equal(prompts.length, 1, 'Rebuild writes the file only');
    assert.match(prompts[0], /"answer":"Russian"/);
    assert.deepEqual(rebuilt.skill.clarify, edited);
  } finally {
    server.close();
  }
});
