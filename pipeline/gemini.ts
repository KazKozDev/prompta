import ruleData from '../gemini_prompt_rules/rules.json' with { type: 'json' };
import sourceData from '../gemini_prompt_rules/sources.json' with { type: 'json' };
import { loadOfficialRules, runOfficialPipeline } from './official.ts';
import type { OfficialProfile } from './official.ts';

const profile: OfficialProfile = {
  target: 'gemini', label: 'Gemini', organization: 'Google', guidanceKey: 'geminiGuidance',
  policy: 'Use direct, concise Gemini instructions and consistent structure only when useful. Reasoning-capable Gemini thinks internally; do not request exposed hidden chain-of-thought. Do not copy fixed dates, knowledge cutoffs, model identities, temperature recipes, or tools from examples. Treat multimodal and API settings as conditional on the actual target capabilities. Do not import Anthropic-specific or OpenAI-specific recommendations.',
};
export function loadGeminiRules(raw: unknown = ruleData, sources: unknown = sourceData) {
  return loadOfficialRules(raw, sources, profile);
}
export function runGeminiPipeline(opts: Parameters<typeof runOfficialPipeline>[0]) {
  return runOfficialPipeline(opts, profile, ruleData, sourceData);
}
