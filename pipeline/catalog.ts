import { hints, names, procedures, rationales } from '../catalog/display.en.ts';
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
    throw new PipelineError('Catalog is empty or missing techniques', 'catalog');
  }
  const seen = new Set<string>();
  for (const t of data.techniques) {
    if (!t.key) throw new PipelineError('Entry is missing a key', 'catalog');
    if (seen.has(t.key)) throw new PipelineError(`Duplicate key: ${t.key}`, 'catalog');
    seen.add(t.key);
    if (t.status === 'ready' && !t.template) {
      throw new PipelineError(`${t.key}: Ready technique has no template`, 'catalog');
    }
  }
  return { version: data.version ?? 'unknown', techniques: data.techniques.map((t) => ({
    ...t,
    name: names[t.key] ?? t.name,
    when_to_use: hints[t.key] ?? t.when_to_use,
    procedure: procedures[t.key] ?? t.procedure,
    config: { ...t.config, rationale: rationales[t.config.rationale] ?? t.config.rationale },
  })) };
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
/** The task itself is about prompt security: only then is a defense technique a prompt variant. */
const SECURITY_TASK = /инъекц|injection|jailbreak|джейлбрейк|взлом промпт|prompt (security|hacking|attack)|защит\w* (от атак|промпт)/i;
/** Answer-engineering techniques parse a model's answer into labels or structured data for a program. */
const MACHINE_FORMAT = /json|yaml|csv|xml|tsv|метк|label|класс|class|регуляр|regex|enum|одно слово|single word/i;

/** Categories that are never a way to write the prompt for this task; null when the technique may be offered. */
function misfit(t: Technique, brief: TaskBrief): string | null {
  if (t.category === 'security' && !SECURITY_TASK.test(`${brief.goal} ${brief.constraints.join(' ')}`)) {
    return 'Security guard is added automatically when the prompt processes external material';
  }
  if (t.category === 'answer_engineering' && !MACHINE_FORMAT.test(brief.output_format)) {
    return 'Parses answers into machine-readable output; this task needs a human-readable answer';
  }
  return null;
}

export function gateTechniques(brief: TaskBrief, catalog: Catalog, opts: GateOptions = {}): Gated {
  const budget = opts.budgetCalls ?? brief.budget_calls;
  const rejected: { key: string; reason: string }[] = [];
  const candidates: Technique[] = [];

  if (brief.modality !== 'text') {
    throw new PipelineError(
      `The catalog supports text techniques only; the brief requires modality=${brief.modality}`,
      'gate',
    );
  }

  for (const t of catalog.techniques) {
    if (t.kind === 'setting' || t.kind === 'risk') {
      rejected.push({ key: t.key, reason: `kind=${t.kind}: Not a synthesis technique` });
      continue;
    }
    if (t.kind === 'prompt_type' && brief.task_type !== 'teaching') {
      rejected.push({ key: t.key, reason: 'Teaching technique outside a teaching task' });
      continue;
    }
    if (t.status !== 'ready') {
      rejected.push({ key: t.key, reason: `${t.status}: No synthesis template` });
      continue;
    }
    const unfit = misfit(t, brief);
    if (unfit) {
      rejected.push({ key: t.key, reason: unfit });
      continue;
    }
    // Тип задачи: техника, заявленная для других задач, в короткий список не попадает.
    const types = t.task_types ?? [];
    if (types.length && !types.includes(brief.task_type)) {
      rejected.push({ key: t.key, reason: `Not intended for ${brief.task_type}; designed for ${types.join(', ')}` });
      continue;
    }

    // Задача «ответить по материалам» требует техники, которая реально вставляет материал.
    if (brief.task_type === 'qa_over_docs' && !/\{\{\s*(document|text|context|external_text)\s*\}\}/.test(t.template ?? '')) {
      rejected.push({ key: t.key, reason: 'This task requires a source-grounded technique' });
      continue;
    }

    const [min] = costRange(t.cost_calls);
    if (budget != null && min > budget) {
      rejected.push({ key: t.key, reason: `Over budget: at least ${min} calls, budget ${budget}` });
      continue;
    }
    if (opts.derivablePlaceholders) {
      const need = t.template ? placeholdersOf(t.template) : [];
      const unknown = [...new Set(need)].filter((n) => !opts.derivablePlaceholders!.has(n));
      if (unknown.length) {
        rejected.push({ key: t.key, reason: `Cannot fill these fields without LLM synthesis: ${unknown.join(', ')}` });
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
        (t.kind !== 'prompt_type' || brief.task_type === 'teaching') &&
        !misfit(t, brief) &&
        (!opts.derivablePlaceholders || placeholdersOf(t.template ?? '').every((name) => opts.derivablePlaceholders!.has(name))) &&
        (bestEffortBudget(t, budget)) &&
        (brief.task_type !== 'qa_over_docs' ||
          /\{\{\s*(document|text|context|external_text)\s*\}\}/.test(t.template ?? '')),
    );
    if (relaxed.length) {
      rejected.push({ key: '*', reason: 'Task-type filter relaxed because no techniques remained' });
      relaxed.sort((a, b) => costRange(a.cost_calls)[0] - costRange(b.cost_calls)[0]);
      const accepted = new Set(relaxed.map((t) => t.key));
      return { candidates: relaxed, rejected: rejected.filter((item) => !accepted.has(item.key)) };
    }
  }

  return { candidates, rejected };
}

function bestEffortBudget(t: Technique, budget: number | null): boolean {
  return budget == null || costRange(t.cost_calls)[0] <= budget;
}

export const SUPPORTED_MODALITIES: Modality[] = ['text'];
