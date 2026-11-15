import ruleData from '../instructions_rules/rules.json' with { type: 'json' };
import sourceData from '../instructions_rules/sources.json' with { type: 'json' };
import { PipelineError } from './types.ts';

/** Which project-instruction file to write: the open AGENTS.md, Claude Code's CLAUDE.md,
 *  a Cursor project rule (.mdc) or GitHub Copilot's repository-wide instructions. */
export type InstructionTarget = 'agentsMd' | 'claudeMd' | 'cursor' | 'copilot';
export const INSTRUCTION_TARGETS: readonly InstructionTarget[] = ['agentsMd', 'claudeMd', 'cursor', 'copilot'];

/** Where the file goes, relative to the project root. */
export const INSTRUCTION_FILES: Record<InstructionTarget, string> = {
  agentsMd: 'AGENTS.md',
  claudeMd: 'CLAUDE.md',
  cursor: '.cursor/rules/project.mdc',
  copilot: '.github/copilot-instructions.md',
};

export interface InstructionRule {
  id: string;
  rule_text: string;
  targets: InstructionTarget[];
  source_id: string;
  source_url: string;
  source_title: string;
}
export interface InstructionRuleSet {
  version: string;
  verified_at: string;
  rules: InstructionRule[];
}

interface RawSource { id: string; title: string; url: string }

/** Rules from instructions_rules/rules.json joined with their sources, kept for one target. */
export function loadInstructionRules(target: InstructionTarget, raw: unknown = ruleData, sources: unknown = sourceData): InstructionRuleSet {
  const bundle = raw as { version?: unknown; verified_at?: unknown; rules?: unknown } | null;
  const list = (sources as { sources?: unknown } | null)?.sources;
  if (!bundle || typeof bundle.version !== 'string' || !Array.isArray(bundle.rules) || !Array.isArray(list)) {
    throw new PipelineError('Instruction rules are missing or invalid.', 'instructions');
  }
  const byId = new Map((list as RawSource[]).map((s) => [s.id, s]));
  const rules = (bundle.rules as Omit<InstructionRule, 'source_url' | 'source_title'>[]).map((rule) => {
    const source = byId.get(rule.source_id);
    const targetsOk = Array.isArray(rule.targets) && rule.targets.length > 0
      && rule.targets.every((t) => INSTRUCTION_TARGETS.includes(t));
    if (!source || typeof rule.id !== 'string' || typeof rule.rule_text !== 'string' || !targetsOk) {
      throw new PipelineError(`Instruction rule "${String(rule.id)}" is invalid or has no source.`, 'instructions');
    }
    return { id: rule.id, rule_text: rule.rule_text, targets: rule.targets, source_id: rule.source_id, source_url: source.url, source_title: source.title };
  });
  return {
    version: bundle.version,
    verified_at: String(bundle.verified_at ?? ''),
    rules: rules.filter((r) => r.targets.includes(target)),
  };
}
