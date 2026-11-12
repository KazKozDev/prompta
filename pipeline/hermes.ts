import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import rules from '../hermes_agent_prompt_guides/rules.json' with { type: 'json' };
import sources from '../hermes_agent_prompt_guides/sources.json' with { type: 'json' };
import { runOfficialPipeline, type OfficialProfile } from './official.ts';
import { PipelineError } from './types.ts';

export const HERMES_PROFILE: OfficialProfile = {
  target: 'hermes',
  label: 'Hermes Agent',
  organization: 'Nous Research',
  guidanceKey: 'hermesGuidance',
  requiredRuleIds: ['tips'],
  policy: 'Write a task message for Hermes Agent unless the user asks for a different artifact. State the outcome and relevant context up front. For tasks with dependent stages, describe milestones and completion checks while leaving tool choice to the agent. Respect the user’s permitted actions and supplied execution capabilities. Do not assume tools or skills are installed. Treat project context and persistent persona as separate artifacts only when explicitly requested.',
};

export function runHermesPipeline(opts: Parameters<typeof runOfficialPipeline>[0]) {
  for (const source of sources.sources) {
    const bytes = readFileSync(new URL(`../hermes_agent_prompt_guides/${source.snapshot}`, import.meta.url));
    if (createHash('sha256').update(bytes).digest('hex') !== source.sha256) {
      throw new PipelineError(`Hermes Agent source integrity check failed: ${source.title}.`, 'hermes-rules');
    }
  }
  return runOfficialPipeline(opts, HERMES_PROFILE, rules, sources);
}
