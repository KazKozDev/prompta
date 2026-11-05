import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadCatalog } from '../pipeline/catalog.ts';
import { runPipeline } from '../pipeline/index.ts';
import { createLLM } from '../pipeline/llm.ts';
import { generateManualPrompt } from '../pipeline/manual.ts';
import type { Provider } from '../pipeline/llm.ts';

/** Мост для десктопного UI: JSON на stdin → JSON на stdout. Никаких аргументов, чтобы не мучиться с кавычками. */

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

interface BridgeRequest {
  thoughts: string;
  provider?: Provider;
  model?: string;
  apiKey?: string;
  deterministic?: boolean;
  budgetCalls?: number | null;
  /** Список техник для выпадающего меню в UI. */
  listTechniques?: boolean;
  /** Принудительно собрать промпт по методике конкретной техники. */
  manualTechnique?: string;
  /** Сколько вариантов техник предложить (1–3). */
  variants?: number;
}

async function main() {
  const raw = readFileSync(0, 'utf8');
  const req = JSON.parse(raw) as BridgeRequest;

  if (!req.thoughts || !req.thoughts.trim()) {
    throw new Error('Enter your thoughts');
  }

  const provider = req.provider ?? 'ollama';
  const model = req.model ?? '';
  if (!model) throw new Error('Choose a model');
  if (provider !== 'ollama' && !req.apiKey) throw new Error(`An API key is required for ${provider}`);

  const catalog = loadCatalog(JSON.parse(readFileSync(join(root, 'catalog', 'catalog.json'), 'utf8')));

  if (req.listTechniques) {
    const ready = catalog.techniques
      .filter(
        (t) =>
          ['ready', 'procedure'].includes(t.status) &&
          ['technique', 'prompt_type', 'procedure'].includes(t.kind),
      )
      .map((t) => ({
        key: t.key,
        name: t.name,
        category: t.category,
        status: t.status,
        // Подсказка в одну фразу: первое предложение when_to_use без хвоста.
        hint: t.when_to_use.split(/[.;]/)[0].trim().slice(0, 90),
      }));
    process.stdout.write(JSON.stringify({ ok: true, techniques: ready }));
    return;
  }

  const llm = createLLM({ provider, model, apiKey: req.apiKey });

  if (req.manualTechnique) {
    const technique = catalog.techniques.find((t) => t.key === req.manualTechnique);
    if (!technique) throw new Error(`Unknown technique: ${req.manualTechnique}`);

    if (technique.status === 'procedure') {
      process.stdout.write(
        JSON.stringify({
          ok: true,
          procedure: {
            technique: { key: technique.key, name: technique.name, category: technique.category },
            steps: technique.procedure ?? [],
            when_to_use: technique.when_to_use,
            source_ref: technique.source_ref,
          },
        }),
      );
      return;
    }

    if (!technique.template) throw new Error(`${technique.key}: No synthesis template`);

    if (req.deterministic) throw new Error('Manual technique selection requires LLM synthesis. Disable Skip LLM synthesis.');
    const prompt = await generateManualPrompt(req.thoughts, technique, llm);

    process.stdout.write(
      JSON.stringify({
        ok: true,
        manual: {
          technique: { key: technique.key, name: technique.name, category: technique.category },
          prompt,
          config: technique.config,
          source_ref: technique.source_ref,
        },
      }),
    );
    return;
  }

  const result = await runPipeline({
    thoughts: req.thoughts,
    catalog,
    llm,
    mode: req.deterministic ? 'deterministic' : 'llm',
    budgetCalls: req.budgetCalls ?? null,
    variants: req.variants ?? 3,
  });

  process.stdout.write(JSON.stringify({ ok: true, result }));
}

main().catch((e) => {
  process.stdout.write(JSON.stringify({ ok: false, error: e instanceof Error ? e.message : String(e) }));
  process.exitCode = 1;
});
