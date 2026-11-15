import ruleData from '../agent_rules/rules.json' with { type: 'json' };
import sourceData from '../agent_rules/sources.json' with { type: 'json' };
import { PipelineError } from './types.ts';

/** Which subagent definition to write: Claude Code and Cursor (Markdown + YAML frontmatter),
 *  Codex (TOML) or a GitHub Copilot custom agent (.agent.md). */
export type AgentTarget = 'claudeCode' | 'cursor' | 'codex' | 'copilot';
export const AGENT_TARGETS: readonly AgentTarget[] = ['claudeCode', 'cursor', 'codex', 'copilot'];

/** Where the file goes, relative to the project root, for an agent called `name`. */
export function agentFileName(target: AgentTarget, name: string): string {
  return {
    claudeCode: `.claude/agents/${name}.md`,
    cursor: `.cursor/agents/${name}.md`,
    codex: `.codex/agents/${name}.toml`,
    copilot: `.github/agents/${name}.agent.md`,
  }[target];
}

export interface AgentRule {
  id: string;
  rule_text: string;
  targets: AgentTarget[];
  source_id: string;
  source_url: string;
  source_title: string;
}
export interface AgentRuleSet {
  version: string;
  verified_at: string;
  rules: AgentRule[];
}

interface RawSource { id: string; title: string; url: string }

/** Rules from agent_rules/rules.json joined with their sources, kept for one target. */
export function loadAgentRules(target: AgentTarget, raw: unknown = ruleData, sources: unknown = sourceData): AgentRuleSet {
  const bundle = raw as { version?: unknown; verified_at?: unknown; rules?: unknown } | null;
  const list = (sources as { sources?: unknown } | null)?.sources;
  if (!bundle || typeof bundle.version !== 'string' || !Array.isArray(bundle.rules) || !Array.isArray(list)) {
    throw new PipelineError('Agent rules are missing or invalid.', 'agent');
  }
  const byId = new Map((list as RawSource[]).map((s) => [s.id, s]));
  const rules = (bundle.rules as Omit<AgentRule, 'source_url' | 'source_title'>[]).map((rule) => {
    const source = byId.get(rule.source_id);
    const targetsOk = Array.isArray(rule.targets) && rule.targets.length > 0
      && rule.targets.every((t) => AGENT_TARGETS.includes(t));
    if (!source || typeof rule.id !== 'string' || typeof rule.rule_text !== 'string' || !targetsOk) {
      throw new PipelineError(`Agent rule "${String(rule.id)}" is invalid or has no source.`, 'agent');
    }
    return { id: rule.id, rule_text: rule.rule_text, targets: rule.targets, source_id: rule.source_id, source_url: source.url, source_title: source.title };
  });
  return {
    version: bundle.version,
    verified_at: String(bundle.verified_at ?? ''),
    rules: rules.filter((r) => r.targets.includes(target)),
  };
}
