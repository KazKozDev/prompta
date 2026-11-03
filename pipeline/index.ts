import type { Catalog, LLM, PipelineResult, PipelineTrace, TaskBrief, TechniqueChoice } from './types.ts';
import { PipelineError } from './types.ts';
import { buildBriefPrompt, parseBrief } from './brief.ts';
import { gateTechniques, getTechnique } from './catalog.ts';
import { buildSelectionPrompt, parseChoice } from './select.ts';
import { synthesizeDeterministic, synthesizeWithLLM, valuesFromBrief } from './synthesize.ts';

export interface RunOptions {
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
}

/** Полный проход: мысли → бриф → отсев → выбор → синтез. */
export async function runPipeline(opts: RunOptions): Promise<PipelineResult> {
  const mode = opts.mode ?? 'llm';
  const trace: PipelineTrace[] = [];
  const t0 = () => performance.now();
  const push = (step: string, ms: number, extra: Partial<PipelineTrace> = {}) =>
    trace.push({ step, ms: Math.round(ms), ...extra });

  let brief = opts.brief;
  if (!brief) {
    const start = t0();
    const briefPrompt = buildBriefPrompt(opts.thoughts);
    const raw = await opts.llm(briefPrompt, { temperature: 0 });
    brief = parseBrief(raw);
    push('brief', t0() - start, { prompt: briefPrompt, raw });
  } else {
    push('brief', 0, {});
  }

  const gateStart = t0();
  const { candidates, rejected } = gateTechniques(brief, opts.catalog, {
    budgetCalls: opts.budgetCalls,
    derivablePlaceholders:
      mode === 'deterministic' ? new Set(Object.keys(valuesFromBrief(brief))) : undefined,
  });
  push('gate', t0() - gateStart);
  if (candidates.length === 0) {
    const why = rejected.slice(0, 5).map((r) => `${r.key}: ${r.reason}`).join('; ');
    throw new PipelineError(`нет допустимых техник после отсева (${why})`, 'gate');
  }

  let choice: TechniqueChoice;
  if (opts.techniqueKey) {
    const forced = candidates.find((c) => c.key === opts.techniqueKey);
    if (!forced) {
      throw new PipelineError(
        `техника ${opts.techniqueKey} не прошла отсев: ${rejected.find((r) => r.key === opts.techniqueKey)?.reason ?? 'не входит в допустимые'}`,
        'select',
      );
    }
    choice = {
      key: forced.key,
      name: forced.name,
      reason: 'техника задана принудительно (сравнение техник)',
      confidence: 1,
      whyNotCheaper: 'принудительный выбор вне правила «самая дешёвая»',
    };
    push('select', 0);
  } else {
    const selectStart = t0();
    const selectPrompt = buildSelectionPrompt(brief, candidates);
    const selectRaw = await opts.llm(selectPrompt, { temperature: 0 });
    choice = parseChoice(selectRaw, candidates);
    push('select', t0() - selectStart, { prompt: selectPrompt, raw: selectRaw });
  }

  const technique = getTechnique(opts.catalog, choice.key);
  if (!technique) throw new PipelineError(`техника ${choice.key} исчезла из каталога`, 'synthesize');

  const synthStart = t0();
  const synthesis =
    mode === 'deterministic'
      ? synthesizeDeterministic(brief, technique)
      : await synthesizeWithLLM(brief, technique, opts.llm);
  push('synthesize', t0() - synthStart);

  const declared = technique.task_types ?? [];
  if (declared.length && !declared.includes(brief.task_type)) {
    synthesis.warnings.push(
      `техника заявлена для задач [${declared.join(', ')}], а бриф — ${brief.task_type}`,
    );
  }

  return { brief, choice, synthesis, rejected, trace };
}

/** Человекочитаемый отчёт для CLI и логов. */
export function formatResult(result: PipelineResult): string {
  const { brief, choice, synthesis, rejected } = result;
  const cfg = synthesis.config;
  const lines = [
    `Задача: ${brief.goal}`,
    `Тип: ${brief.task_type} | язык: ${brief.language} | цена ошибки: ${brief.stakes}`,
    `Формат: ${brief.output_format}`,
    brief.assumptions.length ? `Допущения: ${brief.assumptions.join('; ')}` : 'Допущения: нет',
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
  if (synthesis.warnings.length) lines.push('', `Предупреждения: ${synthesis.warnings.join('; ')}`);
  if (rejected.length) lines.push(`Отсеяно до выбора: ${rejected.length} техник`);
  return lines.join('\n');
}
