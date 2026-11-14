import ruleData from '../skill_rules/rules.json' with { type: 'json' };
import sourceData from '../skill_rules/sources.json' with { type: 'json' };
import { PipelineError } from './types.ts';

/** Where the skill must work: "portable" keeps to the six standard frontmatter keys (claude.ai, API,
 *  Claude Code); "claudeCode" also allows the Claude Code extensions. */
export type SkillSurface = 'portable' | 'claudeCode';

export interface SkillRule {
  id: string;
  rule_text: string;
  surface: 'all' | 'claude-code';
  source_id: string;
  source_url: string;
  source_title: string;
}
export interface SkillRuleSet {
  version: string;
  verified_at: string;
  rules: SkillRule[];
}

interface RawSource { id: string; title: string; url: string }

/** Rules from skill_rules/rules.json joined with their sources; Claude Code-only rules are dropped for portable skills. */
export function loadSkillRules(surface: SkillSurface, raw: unknown = ruleData, sources: unknown = sourceData): SkillRuleSet {
  const bundle = raw as { version?: unknown; verified_at?: unknown; rules?: unknown } | null;
  const list = (sources as { sources?: unknown } | null)?.sources;
  if (!bundle || typeof bundle.version !== 'string' || !Array.isArray(bundle.rules) || !Array.isArray(list)) {
    throw new PipelineError('Skill rules are missing or invalid.', 'skill');
  }
  const byId = new Map((list as RawSource[]).map((s) => [s.id, s]));
  const rules = (bundle.rules as Omit<SkillRule, 'source_url' | 'source_title'>[]).map((rule) => {
    const source = byId.get(rule.source_id);
    if (!source || typeof rule.id !== 'string' || typeof rule.rule_text !== 'string' || !['all', 'claude-code'].includes(rule.surface)) {
      throw new PipelineError(`Skill rule "${String(rule.id)}" is invalid or has no source.`, 'skill');
    }
    return { ...rule, source_url: source.url, source_title: source.title };
  });
  return {
    version: bundle.version,
    verified_at: String(bundle.verified_at ?? ''),
    rules: rules.filter((r) => surface === 'claudeCode' || r.surface === 'all'),
  };
}
