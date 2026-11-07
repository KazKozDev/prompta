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
  "topic": "короткая естественная тема, 2–6 слов на языке пользователя: Платформер на Pygame; не обрывок запроса и без вводных слов",
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

/** Модели отвечают по-русски или синонимами — приводим к канону, а не падаем. */
export function normalizeModality(value: unknown): Modality {
  const v = String(value ?? 'text').trim().toLowerCase();
  if (['text', 'текст', 'текстовый', 'text-only'].includes(v)) return 'text';
  if (['image', 'изображение', 'картинка', 'изображения'].includes(v)) return 'image';
  if (['audio', 'аудио', 'звук'].includes(v)) return 'audio';
  if (['video', 'видео'].includes(v)) return 'video';
  return 'text';
}

export function normalizeStakes(value: unknown): Stakes {
  const v = String(value ?? 'medium').trim().toLowerCase();
  if (['low', 'низкий', 'низкая', 'низкие'].includes(v)) return 'low';
  if (['high', 'высокий', 'высокая', 'высокие'].includes(v)) return 'high';
  if (['medium', 'средний', 'средняя', 'средние', 'normal'].includes(v)) return 'medium';
  return 'medium';
}

export function parseBrief(raw: string): TaskBrief {
  const step = 'brief';
  const obj = extractJson(raw, step) as Record<string, unknown>;
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) {
    throw new PipelineError('Expected a JSON object', step);
  }

  const taskType = requireString(obj, 'task_type', step);
  if (!(TASK_TYPES as readonly string[]).includes(taskType)) {
    throw new PipelineError(
      `Unknown task_type=${taskType}; allowed values: ${TASK_TYPES.join(', ')}`,
      step,
    );
  }

  const modality = normalizeModality(obj.modality);
  const stakes = normalizeStakes(obj.stakes);

  const budget = obj.budget_calls;
  const budgetCalls =
    typeof budget === 'number' && Number.isFinite(budget) && budget >= 1 ? Math.floor(budget) : null;

  const topic = typeof obj.topic === 'string' ? obj.topic.trim().replace(/\s+/g, ' ') : '';
  return {
    ...(topic && topic.length <= 80 ? { topic } : {}),
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
