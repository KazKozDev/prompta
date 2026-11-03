import type { Catalog, Modality, TaskBrief, Technique } from './types.ts';
import { PipelineError } from './types.ts';

/** Разбор «цены» техники: 1 | "5–10" | "3+" | "10–40" → [min, max]. */
export function costRange(cost: number | string): [number, number] {
  if (typeof cost === 'number') return [cost, cost];
  const nums = cost.match(/\d+/g)?.map(Number) ?? [];
  if (nums.length === 0) return [1, 1];
  if (nums.length === 1) return [nums[0], cost.includes('+') ? Infinity : nums[0]];
  return [nums[0], nums[1]];
}

export function loadCatalog(raw: unknown): Catalog {
  const data = raw as Partial<Catalog> | null;
  if (!data || !Array.isArray(data.techniques) || data.techniques.length === 0) {
    throw new PipelineError('каталог пуст или без поля techniques', 'catalog');
  }
  const seen = new Set<string>();
  for (const t of data.techniques) {
    if (!t.key) throw new PipelineError('запись без key', 'catalog');
    if (seen.has(t.key)) throw new PipelineError(`дубль ключа: ${t.key}`, 'catalog');
    seen.add(t.key);
    if (t.status === 'ready' && !t.template) {
      throw new PipelineError(`${t.key}: status=ready без template`, 'catalog');
    }
  }
  return { version: data.version ?? 'unknown', techniques: data.techniques };
}

export function getTechnique(catalog: Catalog, key: string): Technique | undefined {
  return catalog.techniques.find((t) => t.key === key);
}

/** Компактная проекция для промпта выбора: только то, по чему можно решать. */
export function projectForSelection(techniques: Technique[]): string {
  return techniques
    .map((t) => {
      const cost = Array.isArray(t.cost_calls) ? t.cost_calls.join('–') : String(t.cost_calls);
      // Компактно: список уже отфильтрован по типу задачи, поэтому задачи не дублируем.
      const when = t.when_to_use.slice(0, 110);
      const not = t.when_not ? ` | не подходит: ${t.when_not.slice(0, 80)}` : '';
      return `- ${t.key} (${cost} вызовов): ${when}${not}`;
    })
    .join('\n');
}

export interface GateOptions {
  /** Сколько вызовов LLM доступно на весь ответ. */
  budgetCalls?: number | null;
  /** Режим без LLM: техника допустима, только если все её плейсхолдеры выводимы из брифа. */
  derivablePlaceholders?: Set<string>;
}

function placeholdersOf(template: string): string[] {
  return [...template.matchAll(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g)].map((m) => m[1]);
}

export interface Gated {
  candidates: Technique[];
  rejected: { key: string; reason: string }[];
}

/** Детерминированный отсев ДО вызова LLM: тип записи, статус, бюджет, модальность. */
export function gateTechniques(brief: TaskBrief, catalog: Catalog, opts: GateOptions = {}): Gated {
  const budget = opts.budgetCalls ?? brief.budget_calls;
  const rejected: { key: string; reason: string }[] = [];
  const candidates: Technique[] = [];

  if (brief.modality !== 'text') {
    throw new PipelineError(
      `каталог содержит только текстовые техники, а бриф требует modality=${brief.modality}`,
      'gate',
    );
  }

  for (const t of catalog.techniques) {
    if (t.kind === 'setting' || t.kind === 'risk') {
      rejected.push({ key: t.key, reason: `kind=${t.kind}: это не техника синтеза` });
      continue;
    }
    if (t.kind === 'prompt_type' && brief.task_type !== 'teaching') {
      rejected.push({ key: t.key, reason: 'педагогический тип вне учебной задачи' });
      continue;
    }
    if (t.status !== 'ready') {
      rejected.push({ key: t.key, reason: `${t.status}: нет шаблона синтеза` });
      continue;
    }
    // Тип задачи: техника, заявленная для других задач, в короткий список не попадает.
    const types = t.task_types ?? [];
    if (types.length && !types.includes(brief.task_type)) {
      rejected.push({ key: t.key, reason: `не для ${brief.task_type}: заявлена для ${types.join(', ')}` });
      continue;
    }

    // Задача «ответить по материалам» требует техники, которая реально вставляет материал.
    if (brief.task_type === 'qa_over_docs' && !/\{\{\s*(document|text|context|external_text)\s*\}\}/.test(t.template ?? '')) {
      rejected.push({ key: t.key, reason: 'нет опоры на материал, а задача требует источник' });
      continue;
    }

    const [min] = costRange(t.cost_calls);
    if (budget != null && min > budget) {
      rejected.push({ key: t.key, reason: `дороже бюджета: минимум ${min} вызовов при бюджете ${budget}` });
      continue;
    }
    if (opts.derivablePlaceholders) {
      const need = t.template ? placeholdersOf(t.template) : [];
      const unknown = [...new Set(need)].filter((n) => !opts.derivablePlaceholders!.has(n));
      if (unknown.length) {
        rejected.push({ key: t.key, reason: `в офлайн-режиме нечем заполнить: ${unknown.join(', ')}` });
        continue;
      }
    }
    candidates.push(t);
  }

  candidates.sort((a, b) => costRange(a.cost_calls)[0] - costRange(b.cost_calls)[0]);

  // Если фильтр по типу задачи отсёк всё — ослабляем его, но материал оставляем обязательным.
  if (candidates.length === 0) {
    const relaxed = catalog.techniques.filter(
      (t) =>
        t.status === 'ready' &&
        ['technique', 'prompt_type'].includes(t.kind) &&
        (bestEffortBudget(t, budget)) &&
        (brief.task_type !== 'qa_over_docs' ||
          /\{\{\s*(document|text|context|external_text)\s*\}\}/.test(t.template ?? '')),
    );
    if (relaxed.length) {
      rejected.push({ key: '*', reason: 'фильтр по типу задачи ослаблен: подходящих не осталось' });
      relaxed.sort((a, b) => costRange(a.cost_calls)[0] - costRange(b.cost_calls)[0]);
      return { candidates: relaxed, rejected };
    }
  }

  return { candidates, rejected };
}

function bestEffortBudget(t: Technique, budget: number | null): boolean {
  return budget == null || costRange(t.cost_calls)[0] <= budget;
}

export const SUPPORTED_MODALITIES: Modality[] = ['text'];
