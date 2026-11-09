import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { loadCatalog } from '../pipeline/catalog.ts';
import { runPipeline } from '../pipeline/index.ts';
import { apiKeyEnv, createLLM } from '../pipeline/llm.ts';
import type { Provider } from '../pipeline/llm.ts';
import { buildJudgePrompt, parseJudgement } from './judge.ts';
import { aggregate, formatReport } from './aggregate.ts';
import type { EvalTask, RunRecord } from './aggregate.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

function readEnvLocal(): Record<string, string> {
  const path = join(root, '.env.local');
  if (!existsSync(path)) return {};
  return Object.fromEntries(
    readFileSync(path, 'utf8')
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith('#') && l.includes('='))
      .map((l) => {
        const i = l.indexOf('=');
        return [l.slice(0, i).trim(), l.slice(i + 1).trim().replace(/^["']|["']$/g, '')];
      }),
  );
}

function parseArgs(argv: string[]) {
  const flags = {
    tasks: Infinity,
    repeat: 2,
    provider: 'gemini' as Provider,
    model: 'gemini-2.5-flash',
    judgeProvider: '' as Provider | '',
    judgeModel: '',
    judge2Provider: '' as Provider | '',
    judge2Model: '',
    mode: 'llm' as 'llm' | 'deterministic',
    json: false,
    quiet: false,
    ids: [] as string[],
  };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--tasks') flags.tasks = Number(argv[++i]);
    else if (a === '--repeat') flags.repeat = Number(argv[++i]);
    else if (a === '--provider') flags.provider = argv[++i] as Provider;
    else if (a === '--model') flags.model = argv[++i];
    else if (a === '--mode') flags.mode = argv[++i] as 'llm' | 'deterministic';
    else if (a === '--ids') flags.ids = argv[++i].split(',').map((s) => s.trim());
    else if (a === '--judge-provider') flags.judgeProvider = argv[++i] as Provider;
    else if (a === '--judge-model') flags.judgeModel = argv[++i];
    else if (a === '--judge2-provider') flags.judge2Provider = argv[++i] as Provider;
    else if (a === '--judge2-model') flags.judge2Model = argv[++i];
    else if (a === '--json') flags.json = true;
    else if (a === '--quiet') flags.quiet = true;
  }
  return flags;
}

async function main() {
  const flags = parseArgs(process.argv.slice(2));
  const allTasks: EvalTask[] = JSON.parse(readFileSync(join(root, 'eval', 'tasks.json'), 'utf8'));
  const selected = (flags.ids.length ? allTasks.filter((t) => flags.ids.includes(t.id)) : allTasks).slice(0, flags.tasks);

  if (selected.length === 0) {
    console.error('нет задач под фильтр');
    process.exit(2);
  }

  const catalog = loadCatalog(JSON.parse(readFileSync(join(root, 'catalog', 'catalog.json'), 'utf8')));
  const env = { ...readEnvLocal(), ...process.env } as Record<string, string>;
  const apiKey =
    apiKeyEnv(flags.provider) ? env[apiKeyEnv(flags.provider)!] : undefined;
  if (!apiKey && flags.provider !== 'ollama') {
    console.error(`нет ключа для ${flags.provider} в окружении или .env.local`);
    process.exit(2);
  }

  const keyFor = (p: Provider): string | undefined => (apiKeyEnv(p) ? env[apiKeyEnv(p)!] : undefined);

  const llm = createLLM({ provider: flags.provider, model: flags.model, apiKey });

  const judgeProvider = (flags.judgeProvider || flags.provider) as Provider;
  const judgeModel = flags.judgeModel || flags.model;
  const judgeLLM =
    judgeProvider === flags.provider && judgeModel === flags.model
      ? llm
      : createLLM({ provider: judgeProvider, model: judgeModel, apiKey: keyFor(judgeProvider) });

  if (flags.judge2Provider && !flags.judge2Model) {
    console.error('для --judge2-provider нужен --judge2-model');
    process.exit(2);
  }
  const judge2LLM = flags.judge2Provider
    ? createLLM({ provider: flags.judge2Provider as Provider, model: flags.judge2Model, apiKey: keyFor(flags.judge2Provider as Provider) })
    : null;

  if (!flags.quiet && judge2LLM) {
    process.stderr.write(`второй судья: ${flags.judge2Provider}/${flags.judge2Model}\n`);
  }
  const records: RunRecord[] = [];

  for (const task of selected) {
    for (let rep = 1; rep <= flags.repeat; rep += 1) {
      if (!flags.quiet) process.stderr.write(`· ${task.id} #${rep} … `);
      try {
        const result = await runPipeline({
          thoughts: task.thoughts,
          catalog,
          llm,
          mode: flags.mode,
          budgetCalls: task.expect.budget_calls,
        });
        const judgePrompt = buildJudgePrompt({
          thoughts: task.thoughts,
          brief: result.brief,
          choice: result.choice,
          synthesis: result.synthesis,
        });
        const judgeOnce = async () =>
          parseJudgement(await judgeLLM(judgePrompt, { temperature: 0, json: true }));

        let judgement;
        try {
          judgement = await judgeOnce();
        } catch {
          judgement = await judgeOnce(); // слабые модели иногда срываются в прозу — один повтор
        }

        const warnings = [...result.synthesis.warnings];
        let judgement2;
        if (judge2LLM) {
          try {
            judgement2 = parseJudgement(await judge2LLM(judgePrompt, { temperature: 0, json: true }));
          } catch (e) {
            warnings.push(`второй судья не ответил: ${e instanceof Error ? e.message : String(e)}`);
          }
        }

        records.push({
          ok: true,
          taskId: task.id,
          repeat: rep,
          techniqueKey: result.choice.key,
          confidence: result.choice.confidence,
          prompt: result.synthesis.prompt,
          warnings,
          judgement,
          judgement2,
        });
        if (!flags.quiet) process.stderr.write(`${result.choice.key} ${judgement.total}\n`);
      } catch (e) {
        const error = e instanceof Error ? e.message : String(e);
        records.push({ ok: false, taskId: task.id, repeat: rep, error });
        if (!flags.quiet) process.stderr.write(`ошибка: ${error.slice(0, 140)}\n`);
      }
    }
  }

  const report = aggregate(records, selected);
  console.log(flags.json ? JSON.stringify({ report, records }, null, 2) : formatReport(report));

  if (report.failures === report.runs) process.exit(1);
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;

if (isMain) {
  main().catch((e) => {
    console.error('ошибка:', e instanceof Error ? e.message : e);
    process.exit(1);
  });
}
