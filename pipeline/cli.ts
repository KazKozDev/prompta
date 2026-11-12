import { resolveExecutionCapabilities } from './prompt-defaults.ts';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { loadCatalog } from './catalog.ts';
import { runPipeline, formatResult } from './index.ts';
import { createLLMFromEnv, PROVIDERS } from './llm.ts';
import type { Provider } from './llm.ts';

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
  const flags = { budget: null as number | null, deterministic: false, json: false, provider: 'gemini' as Provider, model: 'gemini-2.5-flash' };
  let executionProfile = 'universal';
  let agentCapabilities: string[] = [];
  const words: string[] = [];
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--budget') flags.budget = Number(argv[++i]);
    else if (a === '--deterministic') flags.deterministic = true;
    else if (a === '--json') flags.json = true;
    else if (a === '--provider') flags.provider = argv[++i] as Provider;
    else if (a === '--model') flags.model = argv[++i];
    else if (a === '--execution-profile') executionProfile = argv[++i] ?? '';
    else if (a === '--agent-capabilities') agentCapabilities = (argv[++i] ?? '').split(',');
    else words.push(a);
  }
  return { flags, executionProfile, agentCapabilities, thoughts: words.join(' ').trim() };
}

async function main() {
  const { flags, executionProfile, agentCapabilities, thoughts } = parseArgs(process.argv.slice(2));
  if (!thoughts) {
    console.error('использование: node pipeline/cli.ts "поток мыслей" [--budget 3] [--deterministic] [--json] [--provider gemini|openai|ollama|anthropic|xai] [--model ...] [--execution-profile universal|web|local|agent] [--agent-capabilities web,files,code,integrations]');
    process.exit(2);
  }

  const executionCapabilities = resolveExecutionCapabilities(executionProfile, agentCapabilities);
  const catalog = loadCatalog(JSON.parse(readFileSync(join(root, 'catalog', 'catalog.json'), 'utf8')));
  const env = { ...readEnvLocal(), ...process.env } as Record<string, string>;
  if (!PROVIDERS.includes(flags.provider)) {
    console.error(`неизвестный провайдер ${flags.provider}: ${PROVIDERS.join(', ')}`);
    process.exit(2);
  }


  let llm;
  try {
    llm = createLLMFromEnv(flags.provider, flags.model, env);
  } catch (e) {
    console.error(e instanceof Error ? e.message : String(e));
    process.exit(2);
  }
  const result = await runPipeline({
    thoughts,
    catalog,
    llm,
    mode: flags.deterministic ? 'deterministic' : 'llm',
    budgetCalls: flags.budget,
    executionCapabilities,
  });

  console.log(flags.json ? JSON.stringify(result, null, 2) : formatResult(result));
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;

if (isMain) {
  main().catch((e) => {
    console.error('ошибка:', e instanceof Error ? e.message : e);
    process.exit(1);
  });
}
