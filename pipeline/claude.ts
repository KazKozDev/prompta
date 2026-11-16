import ruleData from '../claude_prompt_rules/rules.json' with { type: 'json' };
import sourceData from '../claude_prompt_rules/sources.json' with { type: 'json' };
import { loadOfficialRules, runOfficialPipeline } from './official.ts';
import type { OfficialProfile } from './official.ts';

const profile: OfficialProfile = {
  target: 'claude', label: 'Claude', organization: 'Anthropic', guidanceKey: 'claudeGuidance',
  briefRules: [
    { ids: ['scope', 'general-solutions'], when: 'task_type is coding', test: (b) => b.task_type === 'coding' },
    { ids: ['ordered-steps'], when: 'task_type is agentic or planning', test: (b) => ['agentic', 'planning'].includes(b.task_type) },
    { ids: ['claim-evidence'], when: 'require_evidence is true', test: (b) => b.require_evidence === true },
    { ids: ['action'], when: 'required_capabilities is not empty', test: (b) => (b.required_capabilities?.length ?? 0) > 0 },
    { ids: ['injection-policy'], when: 'required_capabilities includes web, files or integrations',
      test: (b) => (b.required_capabilities ?? []).some((c) => ['web', 'files', 'integrations'].includes(c)) },
  ],
  policy: 'Do not request hidden chain-of-thought or expose thinking in <thinking> tags. Do not add legacy assistant prefills. Do not add blanket self-check loops: the source documents model-specific exceptions.',
};
export function loadClaudeRules(raw: unknown = ruleData, sources: unknown = sourceData) {
  return loadOfficialRules(raw, sources, profile);
}
export function runClaudePipeline(opts: Parameters<typeof runOfficialPipeline>[0]) {
  return runOfficialPipeline(opts, profile, ruleData, sourceData);
}
