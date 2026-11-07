import ruleData from '../claude_prompt_rules/rules.json' with { type: 'json' };
import sourceData from '../claude_prompt_rules/sources.json' with { type: 'json' };
import { loadOfficialRules, runOfficialPipeline } from './official.ts';
import type { OfficialGuidance, OfficialProfile, OfficialRule } from './official.ts';
import type { LLM } from './types.ts';

export type ClaudeRule = OfficialRule;
export type ClaudeGuidance = OfficialGuidance;
const profile: OfficialProfile = {
  target: 'claude', label: 'Claude', organization: 'Anthropic', guidanceKey: 'claudeGuidance',
  policy: 'Do not request hidden chain-of-thought or expose thinking in <thinking> tags. Do not add legacy assistant prefills. Do not add blanket self-check loops: the source documents model-specific exceptions.',
};
export function loadClaudeRules(raw: unknown = ruleData, sources: unknown = sourceData) {
  return loadOfficialRules(raw, sources, profile);
}
export function runClaudePipeline(opts: { thoughts: string; llm: LLM; variants?: number; oneShot?: boolean; onProgress?: (percent: number, stage: string) => void }) {
  return runOfficialPipeline(opts, profile, ruleData, sourceData);
}
