import type { TaskBrief } from './types.ts';

/** A standalone baseline, built from task data without demonstrations or technique templates. */
export function buildZeroShotPrompt(thoughts: string, brief?: TaskBrief): string {
  const ru = brief?.language === 'ru' || (!brief && /[а-яё]/i.test(thoughts));
  const sections = [ `${ru ? 'Задача' : 'Task'}:\n${brief?.goal || thoughts.trim()}` ];
  if (brief?.input?.trim()) sections.push(`${ru ? 'Входные данные' : 'Input'}:\n${brief.input}`);
  if (brief?.output_format) sections.push(`${ru ? 'Формат ответа' : 'Output format'}:\n${brief.output_format}`);
  if (brief?.constraints.length) sections.push(`${ru ? 'Ограничения' : 'Constraints'}:\n${brief.constraints.join('\n')}`);
  sections.push(ru
    ? 'Выполни задачу напрямую. Не выдумывай отсутствующие факты; если не хватает исходных данных, явно укажи, что нужно предоставить.'
    : 'Complete the task directly. Do not invent missing facts; clearly identify any required input that has not been supplied.');
  return sections.join('\n\n');
}
