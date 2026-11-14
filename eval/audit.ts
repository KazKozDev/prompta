import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadCatalog } from '../pipeline/catalog.ts';
import { buildManualPrompt } from '../pipeline/manual.ts';
import { createLLMFromEnv } from '../pipeline/llm.ts';
import type { Provider } from '../pipeline/llm.ts';

/** Checks that a prompt is really built with the technique's method, not just a rewritten template.
 *
 *  For each technique, look for the mandatory structural signs and for the task context.
 *  It is a heuristic: it catches "the technique is not reflected" but does not measure how deeply it is applied.
 *
 *  Run: node eval/audit.ts --provider ollama --model minimax-m3.1-flash:cloud
 */

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

const THOUGHTS = 'надо разобрать заметки со встречи: вытащить задачи, ответственных и сроки, собрать в таблицу, ошибаться нельзя';

const CHECKS: Record<string, { label: string; must: RegExp[] }> = {
  chain_of_thought: { label: 'reasoning steps', must: [/шаг|пошагов|step/i, /рассужд|reason|scratchpad|цепоч/i] },
  few_shot: { label: 'input→output examples', must: [/input:/i, /output:/i] },
  tree_of_thoughts: { label: 'branching, evaluation, backtracking', must: [/вариант|candidate|ветк/i, /оцен|score|балл/i] },
  tabular_cot: { label: 'table', must: [/\|.*\|/s] },
  contextual_prompting: { label: 'material only + references', must: [/только|only/i, /источник|cite|\[\d\]|материал/i] },
  self_consistency: { label: 'several runs, voting', must: [/независим|несколько|multiple|разн/i, /большинств|majority|соглас/i] },
};

async function main() {
  const argv = process.argv.slice(2);
  const flag = (name: string, def: string) => {
    const i = argv.indexOf(name);
    return i === -1 ? def : argv[i + 1];
  };

  const provider = flag('--provider', 'ollama') as Provider;
  const model = flag('--model', 'minimax-m3.1-flash:cloud');
  const llm = createLLMFromEnv(provider, model, process.env);

  const catalog = loadCatalog(JSON.parse(readFileSync(join(root, 'catalog', 'catalog.json'), 'utf8')));
  let failed = 0;

  for (const [key, check] of Object.entries(CHECKS)) {
    const technique = catalog.techniques.find((t) => t.key === key);
    if (!technique) {
      console.log(`${key.padEnd(22)} — not in the catalog`);
      failed += 1;
      continue;
    }

    const prompt = (await llm(buildManualPrompt(THOUGHTS, technique), { temperature: 0.3 })).trim();
    const marks = check.must.map((re) => re.test(prompt));
    const context = /заметк|встреч|задач/i.test(prompt);
    const ok = marks.every(Boolean) && context;
    if (!ok) failed += 1;

    console.log(
      `${key.padEnd(22)} ${ok ? 'OK  ' : 'FAIL'} signs ${marks.map((m) => (m ? '✓' : '✗')).join('')}` +
        ` | context ${context ? '✓' : '✗'} | length ${String(prompt.length).padStart(5)} | ${check.label}`,
    );
  }

  console.log(failed ? `\nfailures: ${failed}` : '\nall checks passed');
  if (failed) process.exitCode = 1;
}

main().catch((e) => {
  console.error('error:', e instanceof Error ? e.message : e);
  process.exit(1);
});
