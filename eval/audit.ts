import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadCatalog } from '../pipeline/catalog.ts';
import { buildManualPrompt } from '../pipeline/manual.ts';
import { apiKeyEnv, createLLM } from '../pipeline/llm.ts';
import type { Provider } from '../pipeline/llm.ts';

/** Проверка, что промпт реально построен по методике техники, а не переписан шаблоном.
 *
 *  Для каждой техники ищем обязательные структурные признаки и присутствие контекста задачи.
 *  Это эвристика: она ловит «техника не отражена», но не измеряет глубину применения.
 *
 *  Запуск: node eval/audit.ts --provider ollama --model minimax-m3.1-flash:cloud
 */

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

const THOUGHTS = 'надо разобрать заметки со встречи: вытащить задачи, ответственных и сроки, собрать в таблицу, ошибаться нельзя';

const CHECKS: Record<string, { label: string; must: RegExp[] }> = {
  chain_of_thought: { label: 'шаги рассуждения', must: [/шаг|пошагов|step/i, /рассужд|reason|scratchpad|цепоч/i] },
  few_shot: { label: 'примеры вход→выход', must: [/input:/i, /output:/i] },
  tree_of_thoughts: { label: 'ветвление, оценка, откат', must: [/вариант|candidate|ветк/i, /оцен|score|балл/i] },
  tabular_cot: { label: 'таблица', must: [/\|.*\|/s] },
  contextual_prompting: { label: 'только по материалу + ссылки', must: [/только|only/i, /источник|cite|\[\d\]|материал/i] },
  self_consistency: { label: 'несколько прогонов, голосование', must: [/независим|несколько|multiple|разн/i, /большинств|majority|соглас/i] },
};

async function main() {
  const argv = process.argv.slice(2);
  const flag = (name: string, def: string) => {
    const i = argv.indexOf(name);
    return i === -1 ? def : argv[i + 1];
  };

  const provider = flag('--provider', 'ollama') as Provider;
  const model = flag('--model', 'minimax-m3.1-flash:cloud');
  const keyName = apiKeyEnv(provider);
  const llm = createLLM({ provider, model, apiKey: keyName ? process.env[keyName] : undefined });

  const catalog = loadCatalog(JSON.parse(readFileSync(join(root, 'catalog', 'catalog.json'), 'utf8')));
  let failed = 0;

  for (const [key, check] of Object.entries(CHECKS)) {
    const technique = catalog.techniques.find((t) => t.key === key);
    if (!technique) {
      console.log(`${key.padEnd(22)} — нет в каталоге`);
      failed += 1;
      continue;
    }

    const prompt = (await llm(buildManualPrompt(THOUGHTS, technique), { temperature: 0.3 })).trim();
    const marks = check.must.map((re) => re.test(prompt));
    const context = /заметк|встреч|задач/i.test(prompt);
    const ok = marks.every(Boolean) && context;
    if (!ok) failed += 1;

    console.log(
      `${key.padEnd(22)} ${ok ? 'OK  ' : 'FAIL'} признаки ${marks.map((m) => (m ? '✓' : '✗')).join('')}` +
        ` | контекст ${context ? '✓' : '✗'} | длина ${String(prompt.length).padStart(5)} | ${check.label}`,
    );
  }

  console.log(failed ? `\nпровалов: ${failed}` : '\nвсе проверки пройдены');
  if (failed) process.exitCode = 1;
}

main().catch((e) => {
  console.error('ошибка:', e instanceof Error ? e.message : e);
  process.exit(1);
});
