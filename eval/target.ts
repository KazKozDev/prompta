import type { RunOptions } from '../pipeline/index.ts';
import { parseTarget as parsePromptTarget } from '../pipeline/target.ts';
import type { OfficialGuidance } from '../pipeline/official.ts';
import type { PipelineResult } from '../pipeline/types.ts';

/** The generation mode eval measures: the technique catalog or a specific target's official rules. */
export type EvalTarget = 'catalog' | 'claude' | 'chatgpt' | 'gemini' | 'grok' | `open:${string}`;

export const OFFICIAL_TARGETS = ['claude', 'chatgpt', 'gemini', 'grok'] as const;

export function parseTarget(value: string): EvalTarget {
  if (value === 'catalog' || (OFFICIAL_TARGETS as readonly string[]).includes(value)) return value as EvalTarget;
  if (/^open:[\w.-]+$/.test(value)) return value as EvalTarget;
  throw new Error(`--target: catalog, ${OFFICIAL_TARGETS.join(', ')} or open:<model id> (got "${value}")`);
}

export const isOfficial = (target: EvalTarget): boolean => target !== 'catalog';

/** runPipeline options for the target. Offline mode and a forced technique are forbidden for official targets by the pipeline itself. */
export function targetOptions(target: EvalTarget): Partial<RunOptions> {
  return target === 'catalog' ? {} : { target: parsePromptTarget(target) };
}

/** The rules the generator cited in official-target mode. */
export function guidanceOf(result: PipelineResult): OfficialGuidance | undefined {
  return result.claudeGuidance ?? result.chatgptGuidance ?? result.geminiGuidance ?? result.grokGuidance ?? result.openModelGuidance;
}
