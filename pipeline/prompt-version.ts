import { BRIEF_SCHEMA, buildBriefPrompt } from './brief.ts';
import { sanitizeBrief } from './injection.ts';
import { buildManualPrompt } from './manual.ts';
import { runOfficialPipeline } from './official.ts';
import { ONE_SHOT_INSTRUCTION } from './prompt-defaults.ts';
import { buildSelectionPrompt } from './select.ts';
import { buildSynthesisPrompt, INJECTION_GUARDS } from './synthesize.ts';
import { buildZeroShotPrompt, generateZeroShotPrompt } from './zero-shot.ts';

/** Ручная метка набора промптов: меняйте при осознанной переработке, чтобы отчёты читались людьми. */
export const PROMPT_SET = '2026-11-09';

/** FNV-1a 32 bit: без зависимостей, одинаково в Node и в браузере. */
export function fnv1a(text: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, '0');
}

/** Всё, что формирует текст внутренних промптов пайплайна. Добавили новый промпт — добавьте сюда. */
const PROMPT_SOURCES: readonly unknown[] = [
  buildBriefPrompt, BRIEF_SCHEMA, buildSelectionPrompt, buildSynthesisPrompt, JSON.stringify(INJECTION_GUARDS),
  buildZeroShotPrompt, generateZeroShotPrompt, buildManualPrompt, ONE_SHOT_INSTRUCTION, runOfficialPipeline, sanitizeBrief,
];

let cached: string | undefined;

/** Отпечаток промптов: `<метка>+<хеш исходников>`. Хеш меняется сам при любой правке текста промпта,
 *  поэтому балл eval нельзя случайно приписать другой версии. В минифицированной веб-сборке хеш
 *  отличается от Node — сравнивайте отпечатки только из одного окружения. */
export function promptVersion(): string {
  cached ??= `${PROMPT_SET}+${fnv1a(PROMPT_SOURCES.map((s) => String(s)).join('␞'))}`;
  return cached;
}
