import type { SkillSurface } from './skill-rules.ts';

/** Deterministic SKILL.md checks: the rules of skill-creator's quick_validate.py plus the
 *  documented name, description and Claude Code frontmatter rules (skill_rules/sources.json). */

/** Standard keys: quick_validate.py ALLOWED_PROPERTIES and the agentskills.io specification. */
export const PORTABLE_KEYS = ['name', 'description', 'license', 'compatibility', 'metadata', 'allowed-tools'] as const;
/** Claude Code frontmatter (code.claude.com/docs/en/skills). */
export const CLAUDE_CODE_KEYS = [
  ...PORTABLE_KEYS, 'when_to_use', 'argument-hint', 'arguments', 'disable-model-invocation', 'user-invocable',
  'disallowed-tools', 'model', 'effort', 'context', 'agent', 'background', 'hooks', 'paths', 'shell',
] as const;
const LISTING_CAP = 1536;
const BODY_LINES = 500;

export interface SkillCheck {
  valid: boolean;
  errors: string[];
  warnings: string[];
  name: string;
  description: string;
  keys: string[];
  bodyLines: number;
}

/** Top-level frontmatter keys with their scalar text. Indented lines belong to the key above
 *  (metadata maps, hooks, block scalars); only a plain, quoted or block-scalar value is read as text. */
export function readFrontmatter(markdown: string): { fields: Map<string, string>; body: string } | null {
  const match = markdown.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
  if (!match) return null;
  const fields = new Map<string, string>();
  let key = '';
  let block: string[] | null = null;
  for (const line of match[1].split(/\r?\n/)) {
    const top = line.match(/^([A-Za-z_][\w-]*):(?:\s+(.*))?$/);
    if (top) {
      if (block) fields.set(key, block.join(' ').trim());
      key = top[1];
      const value = (top[2] ?? '').trim();
      block = /^[>|][+-]?$/.test(value) ? [] : null;
      fields.set(key, block ? '' : unquote(value));
    } else if (block && /^\s+\S/.test(line)) {
      block.push(line.trim());
    }
  }
  if (block) fields.set(key, block.join(' ').trim());
  return { fields, body: markdown.slice(match[0].length) };
}

function unquote(value: string): string {
  const quoted = value.match(/^(["'])([\s\S]*)\1$/);
  return quoted ? quoted[2] : value.replace(/\s+#.*$/, '');
}

export function validateSkill(markdown: string, surface: SkillSurface): SkillCheck {
  const errors: string[] = [];
  const warnings: string[] = [];
  const parsed = readFrontmatter(markdown.trimStart());
  if (!parsed) {
    return { valid: false, errors: ['No YAML frontmatter: SKILL.md must start with a "---" block.'], warnings, name: '', description: '', keys: [], bodyLines: 0 };
  }
  const { fields, body } = parsed;
  const keys = [...fields.keys()];
  const allowed: readonly string[] = surface === 'claudeCode' ? CLAUDE_CODE_KEYS : PORTABLE_KEYS;
  const unexpected = keys.filter((k) => !allowed.includes(k));
  if (unexpected.length) {
    errors.push(surface === 'claudeCode'
      ? `Unknown frontmatter key(s): ${unexpected.join(', ')}.`
      : `Not portable: ${unexpected.join(', ')}. Allowed: ${PORTABLE_KEYS.join(', ')}.`);
  }

  const name = (fields.get('name') ?? '').trim();
  if (!fields.has('name')) errors.push('Missing "name".');
  else if (!name) errors.push('"name" is empty.');
  else {
    if (!/^[a-z0-9-]+$/.test(name)) errors.push(`name "${name}" must be lowercase letters, digits and hyphens.`);
    if (name.startsWith('-') || name.endsWith('-') || name.includes('--')) errors.push(`name "${name}" cannot start or end with a hyphen or contain "--".`);
    if (name.length > 64) errors.push(`name is ${name.length} characters; the maximum is 64.`);
    if (/anthropic|claude/.test(name)) errors.push(`name "${name}" must not contain "anthropic" or "claude".`);
  }

  const description = (fields.get('description') ?? '').trim();
  if (!fields.has('description')) errors.push('Missing "description".');
  else if (!description) errors.push('"description" is empty.');
  else {
    if (/[<>]/.test(description)) errors.push('description cannot contain angle brackets (< or >).');
    if (description.length > 1024) errors.push(`description is ${description.length} characters; the maximum is 1024.`);
    if (!/\bwhen\b/i.test(description)) warnings.push('description does not say when to use the skill ("Use when ...").');
    if (/^(I|You)\b/.test(description)) warnings.push('description should be in the third person ("Extracts ...").');
  }
  const listing = description.length + (fields.get('when_to_use') ?? '').trim().length;
  if (surface === 'claudeCode' && listing > LISTING_CAP) warnings.push(`description + when_to_use is ${listing} characters; Claude Code truncates the listing at ${LISTING_CAP}.`);

  const compatibility = fields.get('compatibility') ?? '';
  if (compatibility.length > 500) errors.push(`compatibility is ${compatibility.length} characters; the maximum is 500.`);

  const files = [...new Set(body.match(/\b(?:scripts|references|reference|assets)\/[\w./-]*\w/g) ?? [])];
  if (files.length) warnings.push(`Ship these files next to SKILL.md or remove the mentions: ${files.join(', ')}.`);

  const bodyLines = body.trim() ? body.trim().split(/\r?\n/).length : 0;
  if (!bodyLines) errors.push('The body after the frontmatter is empty.');
  if (bodyLines > BODY_LINES) warnings.push(`The body is ${bodyLines} lines; keep it under ${BODY_LINES} and move detail into referenced files.`);

  return { valid: errors.length === 0, errors, warnings, name, description, keys, bodyLines };
}
