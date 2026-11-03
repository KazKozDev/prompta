import { PipelineError } from './types.ts';

/** Достать JSON из ответа модели: снимает ```-обёртку и берёт первый сбалансированный объект. */
export function extractJson(raw: string, step: string): unknown {
  if (!raw || !raw.trim()) throw new PipelineError('пустой ответ модели', step);

  const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const text = (fenced ? fenced[1] : raw).trim();

  const start = text.indexOf('{');
  if (start === -1) throw new PipelineError(`в ответе нет JSON-объекта: ${text.slice(0, 120)}`, step);

  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < text.length; i += 1) {
    const ch = text[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === '\\') escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') inString = true;
    else if (ch === '{') depth += 1;
    else if (ch === '}') {
      depth -= 1;
      if (depth === 0) {
        const slice = text.slice(start, i + 1);
        try {
          return JSON.parse(slice);
        } catch (e) {
          throw new PipelineError(`невалидный JSON: ${(e as Error).message}`, step);
        }
      }
    }
  }
  throw new PipelineError('JSON-объект не закрыт', step);
}

/** Строковое поле с проверкой на непустоту. */
export function requireString(obj: Record<string, unknown>, field: string, step: string): string {
  const v = obj[field];
  if (typeof v !== 'string' || !v.trim()) {
    throw new PipelineError(`поле ${field} отсутствует или пустое`, step);
  }
  return v.trim();
}

export function optionalStringArray(obj: Record<string, unknown>, field: string): string[] {
  const v = obj[field];
  if (!Array.isArray(v)) return [];
  return v.filter((x): x is string => typeof x === 'string' && x.trim().length > 0).map((x) => x.trim());
}

export function clamp01(n: unknown): number {
  const x = typeof n === 'number' && Number.isFinite(n) ? n : 0.5;
  return Math.min(1, Math.max(0, x));
}
