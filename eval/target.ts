import type { RunOptions } from '../pipeline/index.ts';
import type { OfficialGuidance } from '../pipeline/official.ts';
import type { PipelineResult } from '../pipeline/types.ts';

/** Режим генерации, который меряет eval: каталог техник или официальные правила конкретной цели. */
export type EvalTarget = 'catalog' | 'claude' | 'chatgpt' | 'gemini' | 'grok' | `open:${string}`;

export const OFFICIAL_TARGETS = ['claude', 'chatgpt', 'gemini', 'grok'] as const;

export function parseTarget(value: string): EvalTarget {
  if (value === 'catalog' || (OFFICIAL_TARGETS as readonly string[]).includes(value)) return value as EvalTarget;
  if (/^open:[\w.-]+$/.test(value)) return value as EvalTarget;
  throw new Error(`--target: catalog, ${OFFICIAL_TARGETS.join(', ')} или open:<id модели> (получено "${value}")`);
}

export const isOfficial = (target: EvalTarget): boolean => target !== 'catalog';

/** Флаги runPipeline для цели. Офлайн-режим и принудительная техника для официальных целей запрещены самим пайплайном. */
export function targetOptions(target: EvalTarget): Partial<RunOptions> {
  switch (target) {
    case 'catalog': return {};
    case 'claude': return { claudeOnly: true };
    case 'chatgpt': return { chatgptOnly: true };
    case 'gemini': return { geminiOnly: true };
    case 'grok': return { grokOnly: true };
    default: return { openModel: target.slice('open:'.length) };
  }
}

/** Правила, на которые сослался генератор в режиме официальной цели. */
export function guidanceOf(result: PipelineResult): OfficialGuidance | undefined {
  return result.claudeGuidance ?? result.chatgptGuidance ?? result.geminiGuidance ?? result.grokGuidance ?? result.openModelGuidance;
}
