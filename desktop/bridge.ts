import { buildZeroShotPrompt } from '../pipeline/zero-shot.ts';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadCatalog } from '../pipeline/catalog.ts';
import { runPipeline } from '../pipeline/index.ts';
import { extractJson } from '../pipeline/json.ts';
import { createLLM } from '../pipeline/llm.ts';
import { generateManualPrompt } from '../pipeline/manual.ts';
import type { Provider } from '../pipeline/llm.ts';
import techniqueSources from '../catalog/source-links.json' with { type: 'json' };

/** Мост для десктопного UI: JSON на stdin → JSON на stdout. Никаких аргументов, чтобы не мучиться с кавычками. */

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

interface BridgeRequest {
  thoughts: string;
  reportProgress?: boolean;
  oneShot?: boolean;
  provider?: Provider;
  model?: string;
  apiKey?: string;
  deterministic?: boolean;
  claudeOnly?: boolean;
  chatgptOnly?: boolean;
  geminiOnly?: boolean;
  grokOnly?: boolean;
  openModel?: string;
  budgetCalls?: number | null;
  /** Список техник для выпадающего меню в UI. */
  listTechniques?: boolean;
  /** Принудительно собрать промпт по методике конкретной техники. */
  manualTechnique?: string;
  /** Сколько вариантов техник предложить (1–5). */
  variants?: number;
}

async function main() {
  const raw = readFileSync(0, 'utf8');
  const req = JSON.parse(raw) as BridgeRequest;

  if (!req.thoughts || !req.thoughts.trim()) {
    throw new Error('Enter your thoughts');
  }

  for (const key of ['claudeOnly', 'chatgptOnly', 'geminiOnly', 'grokOnly'] as const) {
    if (req[key] !== undefined && typeof req[key] !== 'boolean') throw new Error(`${key} must be a boolean.`);
  }
  if ([req.claudeOnly, req.chatgptOnly, req.geminiOnly, req.grokOnly, req.openModel].filter(Boolean).length > 1) throw new Error('Choose only one target: Claude, ChatGPT, Gemini, or Grok.');

  if (req.openModel !== undefined && (typeof req.openModel !== 'string' || !req.openModel.trim())) throw new Error('Invalid target model.');
  const provider = req.provider ?? 'ollama';
  const model = req.model ?? '';
  if (!model) throw new Error('Choose a model');
  if (provider !== 'ollama' && !req.apiKey) throw new Error(`An API key is required for ${provider}`);

  const onProgress = req.reportProgress === true
    ? (percent: number, stage: string) => process.stderr.write(`PROMPTA_PROGRESS ${JSON.stringify({ percent, stage })}\n`)
    : undefined;
  const oneShot = req.oneShot !== false;
  const officialMode = req.claudeOnly || req.chatgptOnly || req.geminiOnly || req.grokOnly || req.openModel;
  const catalog = officialMode && !req.listTechniques ? { version: 'official-only', techniques: [] } : loadCatalog(JSON.parse(readFileSync(join(root, 'catalog', 'catalog.json'), 'utf8')));

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
        sources: (techniqueSources as Record<string, { title: string; url: string; reference: string }[]>)[t.key] ?? [],
        // Подсказка в одну фразу: первое предложение when_to_use без хвоста.
        hint: t.when_to_use.split(/[.;]/)[0].trim().slice(0, 90),
      }));
    process.stdout.write(JSON.stringify({ ok: true, techniques: ready }));
    return;
  }

  const llm = createLLM({ provider, model, apiKey: req.apiKey });

  if (officialMode && req.manualTechnique) {
    const target = req.claudeOnly ? 'Claude' : req.chatgptOnly ? 'ChatGPT' : req.geminiOnly ? 'Gemini' : req.grokOnly ? 'Grok' : 'Open-weight model';
    throw new Error(`${target} mode cannot use a generic manual technique.`);
  }

  if (req.manualTechnique) {
    onProgress?.(10, 'Technique loaded');
    const technique = catalog.techniques.find((t) => t.key === req.manualTechnique);
    if (!technique) throw new Error(`Unknown technique: ${req.manualTechnique}`);

    if (technique.status === 'procedure') {
      process.stdout.write(
        JSON.stringify({
          ok: true,
          procedure: {
            zeroShotPrompt: buildZeroShotPrompt(req.thoughts),
            technique: { key: technique.key, name: technique.name, category: technique.category },
            steps: technique.procedure ?? [],
            when_to_use: technique.when_to_use,
            source_ref: technique.source_ref,
            topic: technique.name,
          },
        }),
      );
      return;
    }

    if (!technique.template) throw new Error(`${technique.key}: No synthesis template`);

    if (req.deterministic) throw new Error('Manual technique selection requires LLM synthesis. Disable Skip LLM synthesis.');
    const prompt = await generateManualPrompt(req.thoughts, technique, llm, oneShot);
    onProgress?.(85, 'Prompt ready');
    let topic: string | undefined;
    try {
      const raw = await llm(`Name the task below with a natural concise 2–6 word topic in the user's language. Do not clip a sentence. Return JSON {"topic":"..."}. Task data: ${JSON.stringify(req.thoughts)}`, { temperature: 0, json: true });
      const data = extractJson(raw, 'topic') as { topic?: unknown };
      if (typeof data?.topic === 'string' && data.topic.trim().length <= 80) topic = data.topic.trim();
    } catch { /* A missing title must not discard a completed prompt. */ }
    onProgress?.(95, 'Topic ready');

    process.stdout.write(
      JSON.stringify({
        ok: true,
        manual: {
          zeroShotPrompt: buildZeroShotPrompt(req.thoughts),
          topic,
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
    onProgress,
    oneShot,
    thoughts: req.thoughts,
    claudeOnly: req.claudeOnly === true,
    chatgptOnly: req.chatgptOnly === true,
    geminiOnly: req.geminiOnly === true,
    grokOnly: req.grokOnly === true,
    openModel: req.openModel,
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
