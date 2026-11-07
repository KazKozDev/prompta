import ruleData from '../chatgpt_prompt_rules/rules.json' with { type: 'json' };
import sourceData from '../chatgpt_prompt_rules/sources.json' with { type: 'json' };
import { loadOfficialRules, runOfficialPipeline } from './official.ts';
import type { OfficialProfile } from './official.ts';
import type { LLM } from './types.ts';

const profile: OfficialProfile = {
  target: 'chatgpt', label: 'ChatGPT', organization: 'OpenAI', guidanceKey: 'chatgptGuidance',
  policy: 'Target a normal paste-ready ChatGPT prompt, not an API configuration. Start with the outcome and use only helpful structure or examples. Do not require hidden chain-of-thought, rigid reasoning steps, or <thinking> output. Do not assume an exact GPT model, subscription, memory, browsing, plugins, developer messages, or API Structured Outputs. Do not import Anthropic-specific or Google-specific recommendations.',
};
export function loadChatGPTRules(raw: unknown = ruleData, sources: unknown = sourceData) {
  return loadOfficialRules(raw, sources, profile);
}
export function runChatGPTPipeline(opts: { thoughts: string; llm: LLM; variants?: number; oneShot?: boolean; onProgress?: (percent: number, stage: string) => void }) {
  return runOfficialPipeline(opts, profile, ruleData, sourceData);
}
