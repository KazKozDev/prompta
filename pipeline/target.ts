import type { OfficialTarget } from './official.ts';

/** The model a prompt is written for, from its official or saved guides. No target means any LLM: the technique catalog. */
export type PromptTarget =
  | { kind: Exclude<OfficialTarget, 'openModel'> }
  | { kind: 'openModel'; model: string };

export const NAMED_TARGETS = ['claude', 'chatgpt', 'gemini', 'grok', 'hermes'] as const;
export const OPEN_PREFIX = 'open:';

export const TARGET_LABELS: Record<PromptTarget['kind'], string> = {
  claude: 'Claude',
  chatgpt: 'ChatGPT',
  gemini: 'Gemini',
  grok: 'Grok',
  hermes: 'Hermes Agent',
  openModel: 'Open-weight model',
};

/** The wire form shared by the bridge, MCP and eval: "claude" … "hermes", or "open:<model id>". Absent or "" is any LLM. */
export function parseTarget(value: unknown): PromptTarget | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  if (typeof value !== 'string') throw new Error('target must be a string.');
  if ((NAMED_TARGETS as readonly string[]).includes(value)) return { kind: value as (typeof NAMED_TARGETS)[number] };
  const model = value.startsWith(OPEN_PREFIX) ? value.slice(OPEN_PREFIX.length).trim() : '';
  if (model) return { kind: 'openModel', model };
  throw new Error(`Unknown target "${value}": use ${NAMED_TARGETS.join(', ')} or ${OPEN_PREFIX}<model id>.`);
}
