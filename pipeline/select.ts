import type { TaskBrief, Technique, TechniqueChoice } from './types.ts';
import { PipelineError } from './types.ts';
import { clamp01, extractJson } from './json.ts';
import { briefToJson } from './brief.ts';
import { projectForSelection, costRange } from './catalog.ts';

/** Промпт стадии 2: бриф + список допустимых техник → выбор одной. */
export function buildSelectionPrompt(brief: TaskBrief, candidates: Technique[], count = 1): string {
  const cheapest = candidates[0];
  return `Ты выбираешь одну технику промптинга для задачи. Из списка уже отфильтровано всё, что не подходит по типу, статусу и бюджету.

Задача (бриф):
${briefToJson(brief)}

Доступные техники (отсортированы от дешёвой к дорогой):
${projectForSelection(candidates)}

${count > 1 ? `Нужно ${count} варианта, от лучшего к худшему. Первый — самый уместный, второй и третий — реальные альтернативы, а не копии того же подхода.` : 'Нужен один вариант.'}

Правила выбора:
1. Выбирай САМУЮ ДЕШЁВУЮ технику, которая закрывает задачу. Дорогая техника допустима только если дешёвая не решает.
2. Если у техники в поле «не подходит» описан твой случай — она запрещена, даже если кажется удачной.
3. Не выбирай технику только потому, что она известнее.
4. В whyNotCheaper объясни, почему нельзя было взять более дешёвую (или «взял самую дешёвую», если ${cheapest ? cheapest.key : 'первая'} и есть выбор).
5. Учитывай budget_calls: если бюджета мало, многошаговые техники отпадают.
6. Отвечай ТОЛЬКО JSON, без пояснений.

Формат ответа:
${count > 1
    ? '{"choices": [{"key": "…", "reason": "…", "confidence": 0.0-1.0, "whyNotCheaper": "…"}, …]}'
    : '{"key": "ключ из списка", "reason": "почему эта техника решает задачу", "confidence": 0.0-1.0, "whyNotCheaper": "почему не более дешёвая"}'}

JSON:`;
}

/** Разбор одного или нескольких вариантов выбора (модель может вернуть choices[]). */
export function parseChoices(raw: string, candidates: Technique[]): TechniqueChoice[] {
  const step = 'select';
  const obj = extractJson(raw, step) as Record<string, unknown>;
  const list = Array.isArray(obj.choices) ? (obj.choices as Record<string, unknown>[]) : null;
  if (!list) return [parseChoice(raw, candidates)];

  const seen = new Set<string>();
  const out: TechniqueChoice[] = [];
  for (const item of list) {
    try {
      const choice = parseChoice(JSON.stringify(item), candidates);
      if (seen.has(choice.key)) continue;
      seen.add(choice.key);
      out.push(choice);
    } catch {
      // один битый вариант не должен ронять весь выбор
    }
  }
  if (out.length === 0) return [parseChoice(raw, candidates)];
  return out;
}

export function parseChoice(raw: string, candidates: Technique[]): TechniqueChoice {
  const step = 'select';
  const obj = extractJson(raw, step) as Record<string, unknown>;
  // Слабые модели называют поле по-разному — принимаем известные синонимы.
  const candidateKey = [obj.key, obj.technique, obj.technique_key, obj.id, obj.name, obj.choice]
    .find((v) => typeof v === 'string' && v.trim().length > 0) as string | undefined;
  if (!candidateKey) {
    throw new PipelineError(
      'в ответе нет ключа техники (ожидалось поле key/technique/id/name)',
      step,
    );
  }
  const rawKey = candidateKey;

  const key = rawKey.trim().toLowerCase();
  const found =
    candidates.find((c) => c.key === key) ??
    candidates.find((c) => c.key.toLowerCase() === key) ??
    candidates.find((c) => c.name.toLowerCase() === key);

  if (!found) {
    const allowed = candidates.map((c) => c.key).join(', ');
    throw new PipelineError(`модель выбрала «${rawKey}», которой нет среди допустимых: ${allowed}`, step);
  }

  const reason = typeof obj.reason === 'string' && obj.reason.trim() ? obj.reason.trim() : 'причина не указана';
  const whyNotCheaper =
    typeof obj.whyNotCheaper === 'string' && obj.whyNotCheaper.trim() ? obj.whyNotCheaper.trim() : '';

  const cheapest = candidates[0];
  const overrides = Boolean(cheapest && cheapest.key !== found.key && !whyNotCheaper);

  return {
    key: found.key,
    name: found.name,
    reason,
    confidence: clamp01(obj.confidence),
    whyNotCheaper: whyNotCheaper || 'не объяснено',
    cheapestOverride: overrides || undefined,
  };
}

/** Ближайшая по цене альтернатива — чтобы показать пользователю второй вариант. */
export function pickAlternative(candidates: Technique[], chosenKey: string): Technique | undefined {
  return candidates.find((c) => c.key !== chosenKey);
}

export function describeCost(t: Technique): string {
  const [min, max] = costRange(t.cost_calls);
  return max === Infinity ? `${min}+ вызовов` : min === max ? `${min} вызов(ов)` : `${min}–${max} вызовов`;
}
