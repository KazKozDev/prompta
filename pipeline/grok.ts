import ruleData from '../grok_prompt_rules/rules.json' with { type: 'json' };
import sourceData from '../grok_prompt_rules/sources.json' with { type: 'json' };
import { loadOfficialRules, runOfficialPipeline } from './official.ts';
import type { OfficialProfile } from './official.ts';
import type { LLM } from './types.ts';

const profile: OfficialProfile = {
  target: 'grok', label: 'Grok', organization: 'xAI', guidanceKey: 'grokGuidance',
  requiredRuleIds: ['clear', 'output-schema'],
  policy: 'State the task, constraints and output format directly. Grok reasoning models reason internally; do not demand hidden reasoning. Do not assume tools, API settings or multi-agent research capabilities. API and evaluation guidance is configuration guidance, not prompt prose. Do not import recommendations from other providers.',
};
export function loadGrokRules(raw: unknown = ruleData, sources: unknown = sourceData) {
  return loadOfficialRules(raw, sources, profile);
}
export function runGrokPipeline(opts: { thoughts: string; llm: LLM; variants?: number; oneShot?: boolean; onProgress?: (percent: number, stage: string) => void }) {
  return runOfficialPipeline(opts, profile, ruleData, sourceData);
}
