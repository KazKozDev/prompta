import type { Modality, Stakes, TaskBrief } from './types.ts';
import { PipelineError } from './types.ts';
import { extractJson, optionalStringArray, requireString } from './json.ts';

const TASK_TYPES = [
  'classification',
  'extraction',
  'generation',
  'reasoning',
  'planning',
  'coding',
  'qa_over_docs',
  'agentic',
  'teaching',
] as const;

export const BRIEF_SCHEMA = `{
  "goal": "одно предложение: чего хочет пользователь",
  "task_type": ${TASK_TYPES.map((t) => `"${t}"`).join(' | ')},
  "input": "что именно модель получит на вход (текст, документы, код, пусто)",
  "output_format": "точный формат ответа: JSON, markdown-таблица, список, число, письмо…",
  "constraints": ["существенные ограничения: объём, стиль, запреты, источники"],
  "language": "язык ответа (ru, en, …)",
  "modality": "text | image | audio | video",
  "stakes": "low | medium | high — цена ошибки",
  "assumptions": ["что пришлось домыслить, потому что в мыслях этого нет"],
  "budget_calls": "число вызовов LLM, которое пользователь готов потратить, или null"
}`;

/** Промпт для стадии 1: сырые мысли → бриф. */
export function buildBriefPrompt(thoughts: string): string {
  return `Ты разбираешь сырой поток мыслей пользователя и превращаешь его в техническое задание для генерации промпта.

Правила:
1. Не выдумывай факты. Если чего-то нет — сделай минимальное разумное допущение и запиши его в assumptions.
2. task_type выбирай по сути работы, а не по словам: «сравни 3 варианта» — reasoning, «вытащи поля» — extraction, «ответь по документам» — qa_over_docs.
3. output_format должен быть исполнимым: не «хороший ответ», а «JSON с полями X, Y» или «таблица markdown, 3 колонки».
4. modality — только по тому, что реально нужно на входе или выходе.
5. budget_calls: если пользователь говорит про экономию или скорость — поставь 1; если явно нужен многошаговый разбор — null.
6. Отвечай ТОЛЬКО JSON-объектом по схеме, без пояснений и markdown-обёртки.

Схема:
${BRIEF_SCHEMA}

Поток мыслей:
"""
${thoughts}
"""

JSON:`;
}

export function parseBrief(raw: string): TaskBrief {
  const step = 'brief';
  const obj = extractJson(raw, step) as Record<string, unknown>;
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) {
    throw new PipelineError('ожидался JSON-объект', step);
  }

  const taskType = requireString(obj, 'task_type', step);
  if (!(TASK_TYPES as readonly string[]).includes(taskType)) {
    throw new PipelineError(
      `неизвестный task_type=${taskType}; допустимые: ${TASK_TYPES.join(', ')}`,
      step,
    );
  }

  const modality = (obj.modality ?? 'text') as Modality;
  if (!['text', 'image', 'audio', 'video'].includes(modality)) {
    throw new PipelineError(`неизвестная modality=${String(obj.modality)}`, step);
  }

  const stakes = (obj.stakes ?? 'medium') as Stakes;
  if (!['low', 'medium', 'high'].includes(stakes)) {
    throw new PipelineError(`неизвестный stakes=${String(obj.stakes)}`, step);
  }

  const budget = obj.budget_calls;
  const budgetCalls =
    typeof budget === 'number' && Number.isFinite(budget) && budget >= 1 ? Math.floor(budget) : null;

  return {
    goal: requireString(obj, 'goal', step),
    task_type: taskType,
    input: requireString(obj, 'input', step),
    output_format: requireString(obj, 'output_format', step),
    constraints: optionalStringArray(obj, 'constraints'),
    language: requireString(obj, 'language', step),
    modality,
    stakes,
    assumptions: optionalStringArray(obj, 'assumptions'),
    budget_calls: budgetCalls,
  };
}

/** Бриф → компактный вид для следующих стадий. */
export function briefToJson(brief: TaskBrief): string {
  return JSON.stringify(
    {
      goal: brief.goal,
      task_type: brief.task_type,
      input: brief.input,
      output_format: brief.output_format,
      constraints: brief.constraints,
      language: brief.language,
      stakes: brief.stakes,
      budget_calls: brief.budget_calls,
    },
    null,
    2,
  );
}
