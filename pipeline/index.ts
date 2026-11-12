import { applyPromptDefaults } from './prompt-defaults.ts';
import { buildZeroShotPrompt, generateZeroShotPrompt } from './zero-shot.ts';
import type { Catalog, ExecutionCapabilities, LLM, PipelineResult, PipelineTrace, TaskBrief, TechniqueChoice } from './types.ts';
import { PipelineError } from './types.ts';
import { briefAssumptions, buildBriefPrompt, parseBrief } from './brief.ts';
import { gateTechniques, getTechnique } from './catalog.ts';
import { buildSelectionPrompt, parseChoices } from './select.ts';
import { synthesizeDeterministic, synthesizeWithLLM, valuesFromBrief } from './synthesize.ts';
import { meterLLM } from './llm.ts';
import { sanitizeBrief } from './injection.ts';
import { promptVersion } from './prompt-version.ts';

export interface RunOptions {
  oneShot?: boolean;
  executionCapabilities?: ExecutionCapabilities;
  /** Completed pipeline stages, not an estimate of elapsed time. */
  onProgress?: (percent: number, stage: string) => void;
  claudeOnly?: boolean;
  chatgptOnly?: boolean;
  geminiOnly?: boolean;
  grokOnly?: boolean;
  hermesOnly?: boolean;
  openModel?: string;
  thoughts: string;
  catalog: Catalog;
  llm: LLM;
  /** 'llm' — модель доводит шаблон; 'deterministic' — только подстановка, без вызова. */
  mode?: 'llm' | 'deterministic';
  budgetCalls?: number | null;
  /** Готовый бриф — чтобы прогонять стадии 2–3 отдельно (тесты, отладка). */
  brief?: TaskBrief;
  /** Принудительно выбрать технику, минуя стадию выбора (калибровка, сравнение техник). */
  techniqueKey?: string;
  /** Сколько вариантов предложить: 1 — только лучший, 2–3 — с альтернативами. */
  variants?: number;
}

/** Полный проход: мысли → бриф → отсев → выбор → синтез. К результату добавляются расход
 *  токенов за все стадии и отпечаток версии внутренних промптов. */
export async function runPipeline(opts: RunOptions): Promise<PipelineResult> {
  const meter = meterLLM(opts.llm);
  const result = await dispatch({ ...opts, llm: meter.llm });
  // With a model, the writer works the brief's checks into each prompt; offline there is no writer, so they are appended.
  if (opts.mode === 'deterministic') {
    const withDefaults = (prompt: string) => applyPromptDefaults(prompt, result.brief, opts.executionCapabilities);
    if (result.zeroShotPrompt) result.zeroShotPrompt = withDefaults(result.zeroShotPrompt);
    result.synthesis.prompt = withDefaults(result.synthesis.prompt);
    for (const alternative of result.alternatives ?? []) {
      alternative.synthesis.prompt = withDefaults(alternative.synthesis.prompt);
    }
  }
  return { ...result, usage: meter.usage(), promptVersion: promptVersion() };
}

async function dispatch(opts: RunOptions): Promise<PipelineResult> {
  if ([opts.claudeOnly, opts.chatgptOnly, opts.geminiOnly, opts.grokOnly, opts.hermesOnly, opts.openModel].filter(Boolean).length > 1) {
    throw new PipelineError('Choose only one target.', 'target');
  }
  if (opts.hermesOnly) {
    if (opts.mode === 'deterministic' || opts.techniqueKey) throw new PipelineError('Hermes Agent requires LLM synthesis without a generic technique.', 'hermes');
    const { runHermesPipeline } = await import('./hermes.ts');
    return runHermesPipeline(opts);
  }
  if (opts.openModel) {
    if (opts.mode === 'deterministic' || opts.techniqueKey) throw new PipelineError('Model-specific prompting requires synthesis without a generic technique.', 'target');
    const { runOpenModelPipeline } = await import('./open-model.ts');
    return runOpenModelPipeline({ ...opts, openModel: opts.openModel });
  }
  if (opts.grokOnly) {
    if (opts.mode === 'deterministic' || opts.techniqueKey) throw new PipelineError('Grok mode requires LLM synthesis and cannot use a generic technique.', 'target');
    const { runGrokPipeline } = await import('./grok.ts');
    return runGrokPipeline(opts);
  }
  if (opts.chatgptOnly || opts.geminiOnly) {
    const label = opts.chatgptOnly ? 'ChatGPT' : 'Gemini';
    if (opts.mode === 'deterministic' || opts.techniqueKey) throw new PipelineError(`${label} mode requires LLM synthesis and cannot use a generic technique.`, 'target');
    if (opts.chatgptOnly) {
      const { runChatGPTPipeline } = await import('./chatgpt.ts');
      return runChatGPTPipeline(opts);
    }
    const { runGeminiPipeline } = await import('./gemini.ts');
    return runGeminiPipeline(opts);
  }
  if (opts.claudeOnly) {
    if (opts.mode === 'deterministic' || opts.techniqueKey) throw new PipelineError('Claude mode requires LLM synthesis and cannot use a generic technique.', 'claude');
    const { runClaudePipeline } = await import('./claude.ts');
    return runClaudePipeline(opts);
  }
  const mode = opts.mode ?? 'llm';
  const trace: PipelineTrace[] = [];
  const t0 = () => performance.now();
  const push = (step: string, ms: number, extra: Partial<PipelineTrace> = {}) =>
    trace.push({ step, ms: Math.round(ms), ...extra });

  /** Слабые модели иногда ломают JSON — один повтор с напоминанием о схеме. */
  async function askJson<T>(prompt: string, parse: (raw: string) => T): Promise<{ value: T; raw: string }> {
    let lastError: unknown;
    let raw = '';
    for (let attempt = 1; attempt <= 2; attempt += 1) {
      const suffix =
        attempt === 1
          ? ''
          : `\n\nПредыдущий ответ не разобрался (${lastError instanceof Error ? lastError.message : 'ошибка'}). Верни строго JSON по схеме, без пояснений.`;
      raw = await opts.llm(prompt + suffix, { temperature: 0, json: true });
      try {
        return { value: parse(raw), raw };
      } catch (e) {
        lastError = e;
      }
    }
    throw lastError;
  }

  let brief = opts.brief;
  if (!brief) {
    const start = t0();
    const briefPrompt = buildBriefPrompt(opts.thoughts);
    const { value, raw } = await askJson(briefPrompt, parseBrief);
    brief = value;
    push('brief', t0() - start, { prompt: briefPrompt, raw });
  } else {
    push('brief', 0, {});
  }

  const cleaned = sanitizeBrief(brief, opts.thoughts);
  brief = cleaned.brief;
  const injectionRemoved = cleaned.removed;
  opts.onProgress?.(20, 'Brief ready');
  const gateStart = t0();
  const { candidates, rejected } = gateTechniques(brief, opts.catalog, {
    budgetCalls: opts.budgetCalls,
    executionCapabilities: opts.executionCapabilities,
    derivablePlaceholders:
      mode === 'deterministic' ? new Set(Object.keys(valuesFromBrief(brief))) : undefined,
  });
  push('gate', t0() - gateStart);
  if (candidates.length === 0) {
    const why = rejected.slice(0, 5).map((r) => `${r.key}: ${r.reason}`).join('; ');
    throw new PipelineError(`No eligible techniques after filtering (${why})`, 'gate');
  }

  opts.onProgress?.(30, 'Techniques filtered');
  let choice: TechniqueChoice;
  let choices: TechniqueChoice[] = [];
  if (opts.techniqueKey) {
    const forced = candidates.find((c) => c.key === opts.techniqueKey);
    if (!forced) {
      throw new PipelineError(
        `Technique ${opts.techniqueKey} did not pass filtering: ${rejected.find((r) => r.key === opts.techniqueKey)?.reason ?? 'Not eligible'}`,
        'select',
      );
    }
    choice = {
      key: forced.key,
      name: forced.name,
      reason: 'Technique selected explicitly for comparison',
      confidence: 1,
      whyNotCheaper: 'Explicit selection overrides the cheapest-technique rule',
    };
    choices = [choice];
    push('select', 0);
  } else {
    const selectStart = t0();
    const variants = Math.min(5, Math.max(1, opts.variants ?? 1));
    const selectPrompt = buildSelectionPrompt(brief, candidates, variants);
    const parsed = await askJson(selectPrompt, (raw) => parseChoices(raw, candidates));
    choices = parsed.value.slice(0, variants);
    choice = choices[0];
    push('select', t0() - selectStart, { prompt: selectPrompt, raw: parsed.raw });
  }

  opts.onProgress?.(40, 'Technique selected');
  let completed = 0;
  const synthStart = t0();
  // Варианты независимы — собираем параллельно, чтобы 3 промпта не ждались по очереди.
  // Variant 0 is written by the model too, in parallel with the technique variants.
  const zeroShot = mode === 'deterministic'
    ? Promise.resolve({ prompt: buildZeroShotPrompt(opts.thoughts, brief), byModel: false })
    : generateZeroShotPrompt(opts.thoughts, brief, opts.llm, opts.executionCapabilities);
  const built = await Promise.all(
    choices.map(async (item) => {
      const technique = getTechnique(opts.catalog, item.key);
      if (!technique) throw new PipelineError(`Technique ${item.key} is missing from the catalog`, 'synthesize');
      const synthesis =
        mode === 'deterministic'
          ? synthesizeDeterministic(brief, technique)
          : await synthesizeWithLLM(brief, technique, opts.llm, opts.oneShot, opts.executionCapabilities);
      if (mode === 'deterministic' && opts.oneShot) {
        synthesis.warnings.push('The opening one-shot example requires LLM synthesis and is omitted in offline mode.');
      }
      completed += 1;
      opts.onProgress?.(40 + Math.round(55 * completed / choices.length), `Variants ready: ${completed}/${choices.length}`);
      return { choice: item, technique, synthesis };
    }),
  );
  push('synthesize', t0() - synthStart);

  const primary = built[0];
  const synthesis = primary.synthesis;

  for (const item of built) {
    if (injectionRemoved.length) {
      item.synthesis.warnings.push(`Requirements taken from injected instructions were dropped: ${injectionRemoved.join('; ')}`);
    }
    if (item.choice.cheapestOverride) {
      item.synthesis.warnings.push(
        `A more expensive technique was selected (${item.choice.key}) without justification`,
      );
    }
    const declared = item.technique.task_types ?? [];
    if (declared.length && !declared.includes(brief.task_type)) {
      item.synthesis.warnings.push(
        `Technique is intended for [${declared.join(', ')}], but the task is ${brief.task_type}`,
      );
    }
  }

  const alternatives = built.slice(1).map((item) => ({
    choice: item.choice,
    synthesis: item.synthesis,
  }));

  return {
    zeroShotPrompt: (await zeroShot).prompt,
    brief,
    choice,
    synthesis,
    alternatives: alternatives.length ? alternatives : undefined,
    rejected,
    trace,
  };
}

/** Человекочитаемый отчёт для CLI и логов. */
export function formatResult(result: PipelineResult): string {
  const { brief, choice, synthesis, rejected } = result;
  const cfg = synthesis.config;
  const lines = [
    `Задача: ${brief.goal}`,
    `Тип: ${brief.task_type} | язык: ${brief.language} | цена ошибки: ${brief.stakes}`,
    `Формат: ${brief.output_format}`,
    briefAssumptions(brief).length ? `Допущения: ${briefAssumptions(brief).join('; ')}` : 'Допущения: нет',
    '',
    'Zero-shot · базовый промпт:',
    result.zeroShotPrompt ?? buildZeroShotPrompt('', brief),
    '',
    `Техника: ${choice.name} (${choice.key}), уверенность ${(choice.confidence * 100).toFixed(0)}%`,
    `Почему: ${choice.reason}`,
    `Почему не дешевле: ${choice.whyNotCheaper}`,
    '',
    'Промпт:',
    synthesis.prompt,
    '',
    `Конфиг: temperature=${cfg.temperature ?? '—'}, top_p=${cfg.top_p ?? '—'}, max_tokens=${cfg.max_tokens}`,
    `Обоснование: ${cfg.rationale}`,
  ];
  if (result.usage) {
    lines.push(`Расход: ${result.usage.calls} вызовов, токены ${result.usage.inputTokens} → ${result.usage.outputTokens}`);
  }
  if (result.promptVersion) lines.push(`Версия промптов: ${result.promptVersion}`);
  if (synthesis.warnings.length) lines.push('', `Предупреждения: ${synthesis.warnings.join('; ')}`);
  if (rejected.length) lines.push(`Отсеяно до выбора: ${rejected.length} техник`);
  return lines.join('\n');
}
