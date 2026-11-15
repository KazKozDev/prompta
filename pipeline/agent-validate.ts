import type { AgentTarget } from './agent-rules.ts';
import { readFrontmatter } from './skill-validate.ts';

/** Deterministic checks of a subagent definition, from the formats in agent_rules/ (see AGENT-guide.md). */

const CLAUDE_KEYS = ['name', 'description', 'tools', 'disallowedTools', 'model', 'permissionMode', 'maxTurns',
  'autoCompactWindow', 'skills', 'mcpServers', 'hooks', 'memory', 'background', 'omitClaudeMd', 'effort',
  'isolation', 'color', 'initialPrompt', 'experimental'];
const CURSOR_KEYS = ['name', 'description', 'model', 'readonly', 'is_background'];
const COPILOT_KEYS = ['name', 'description', 'target', 'tools', 'model', 'disable-model-invocation', 'user-invocable',
  'mcp-servers', 'metadata', 'infer', 'argument-hint', 'handoffs'];
const CLAUDE_MODELS = /^(sonnet|opus|haiku|fable|inherit|claude-[\w.-]+)$/;
const PERMISSION_MODES = ['default', 'acceptEdits', 'auto', 'dontAsk', 'bypassPermissions', 'plan', 'manual'];
const CODEX_REQUIRED = ['name', 'description', 'developer_instructions'];
const CODEX_IGNORED = ['sandbox_mode', 'approval_policy', 'model_provider', 'mcp_servers'];
const COPILOT_MAX_CHARS = 30_000;
const NAME = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const READ_ONLY_ROLE = /\b(review|reviewer|reviews|audit|auditor|research|researcher|explore|explorer|analy[sz]e|analyst)\b/i;
const PLACEHOLDER = /«INSERT HERE[^»]*»/g;

export interface AgentCheck {
  valid: boolean;
  errors: string[];
  warnings: string[];
  name: string;
  placeholders: number;
}

/** Top-level keys of a small TOML document: strings ("…", '…', """…""", '''…'''), numbers, booleans,
 *  arrays on one line, dotted keys and [tables]. Enough to check a Codex agent file; not a full parser. */
export function readToml(text: string): { values: Map<string, string>; error?: string } {
  const values = new Map<string, string>();
  const lines = text.split(/\r?\n/);
  let table = '';
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line || line.startsWith('#')) continue;
    const header = line.match(/^\[([\w.-]+)\]$/);
    if (header) { table = header[1] + '.'; continue; }
    const bracketed = line.match(/^\[([\w.-]+)\]\s*=/);
    if (bracketed) return { values, error: `Line ${i + 1}: write ${bracketed[1]} = …, without square brackets around the key.` };
    const pair = line.match(/^([\w.-]+|"[^"]+")\s*=\s*(.*)$/);
    if (!pair) return { values, error: `Line ${i + 1} is not valid TOML (expected key = value): ${line.slice(0, 60)}` };
    const key = table + pair[1].replace(/^"|"$/g, '');
    let value = pair[2].trim();
    const multi = value.match(/^("""|''')/);
    if (multi) {
      const quote = multi[1];
      const rest = value.slice(3);
      const parts: string[] = [];
      if (rest.includes(quote)) parts.push(rest.slice(0, rest.indexOf(quote)));
      else {
        if (rest) parts.push(rest);
        let closed = false;
        for (i++; i < lines.length; i++) {
          const end = lines[i].indexOf(quote);
          if (end >= 0) { parts.push(lines[i].slice(0, end)); closed = true; break; }
          parts.push(lines[i]);
        }
        if (!closed) return { values, error: `${key}: the ${quote} string is never closed.` };
      }
      values.set(key, parts.join('\n').trim());
      continue;
    }
    value = value.replace(/\s+#.*$/, '');
    const quoted = value.match(/^"((?:[^"\\]|\\.)*)"$/) ?? value.match(/^'([^']*)'$/);
    if (quoted) values.set(key, quoted[1]);
    else if (/^(true|false|[+-]?\d[\d_.]*|\[.*\])$/.test(value)) values.set(key, value);
    else return { values, error: `${key}: "${value.slice(0, 40)}" is not a TOML value (strings need quotes).` };
  }
  return { values };
}

function checkName(name: string, errors: string[]): void {
  if (!name) errors.push('Missing "name": the agent file is named after it.');
  else if (!NAME.test(name)) errors.push(`name "${name}" must be lowercase letters, digits and hyphens, such as code-reviewer.`);
  else if (name.length > 64) errors.push(`name is ${name.length} characters: keep it under 64.`);
}

export function validateAgent(text: string, target: AgentTarget): AgentCheck {
  const errors: string[] = [];
  const warnings: string[] = [];
  const source = text.trimStart();
  let name = '';
  let description = '';
  let prompt = '';
  let canEdit = true;

  if (target === 'codex') {
    if (source.startsWith('---')) errors.push('A Codex agent is a TOML file, not Markdown with frontmatter.');
    const { values, error } = readToml(source);
    if (error) errors.push(error);
    for (const key of CODEX_REQUIRED) if (!error && !values.get(key)?.trim()) errors.push(`Missing "${key}".`);
    name = values.get('name') ?? '';
    description = values.get('description') ?? '';
    prompt = values.get('developer_instructions') ?? '';
    const ignored = CODEX_IGNORED.filter((k) => values.has(k));
    if (ignored.length) warnings.push(`${ignored.join(', ')} ${ignored.length === 1 ? 'does' : 'do'} not override the parent session in an agent file: remove it.`);
    canEdit = values.get('features.shell_tool') !== 'false' && !/\b(do not|don't|never) (edit|modify|change)\b/i.test(prompt);
    if (name) checkName(name, errors);
  } else {
    const parsed = readFrontmatter(source);
    if (!parsed) {
      errors.push('No YAML frontmatter: the file must start with a "---" block holding name and description.');
    } else {
      const fields = parsed.fields;
      prompt = parsed.body;
      name = (fields.get('name') ?? '').trim();
      description = (fields.get('description') ?? '').trim();
      checkName(name, errors);
      if (!description) errors.push('Missing "description": it decides when the agent is used.');
      const keys = [...fields.keys()];
      const known = target === 'claudeCode' ? CLAUDE_KEYS : target === 'cursor' ? CURSOR_KEYS : COPILOT_KEYS;
      const unknown = keys.filter((k) => !known.includes(k));
      if (unknown.length && target === 'cursor') errors.push(`Unknown Cursor subagent fields: ${unknown.join(', ')}. Allowed: ${CURSOR_KEYS.join(', ')}.`);
      else if (unknown.length) warnings.push(`Unknown field${unknown.length === 1 ? '' : 's'} ${unknown.join(', ')}: ignored without an error; check the spelling.`);
      const tools = fields.has('tools') ? (fields.get('tools') || source.match(/^tools:\s*\n((?:\s+-.*\n?)+)/m)?.[1] || '') : null;
      if (target === 'claudeCode') {
        const model = fields.get('model');
        if (model && !CLAUDE_MODELS.test(model)) errors.push(`model "${model}": use sonnet, opus, haiku, fable, inherit or a full claude-… ID.`);
        const mode = fields.get('permissionMode');
        if (mode && !PERMISSION_MODES.includes(mode)) errors.push(`permissionMode "${mode}": use ${PERMISSION_MODES.slice(0, 6).join(', ')}.`);
        canEdit = tools === null || /\b(Edit|Write|MultiEdit|NotebookEdit)\b/.test(tools);
      } else if (target === 'cursor') {
        for (const key of ['readonly', 'is_background']) {
          const value = fields.get(key);
          if (value !== undefined && !['true', 'false'].includes(value)) errors.push(`${key} must be true or false.`);
        }
        canEdit = fields.get('readonly') !== 'true';
      } else {
        const where = fields.get('target');
        if (where && !['vscode', 'github-copilot'].includes(where)) errors.push(`target "${where}": use vscode or github-copilot, or leave it out.`);
        canEdit = tools === null || /\b(edit|Edit|Write|\*)\b|"\*"/.test(tools);
        if (prompt.length > COPILOT_MAX_CHARS) errors.push(`The prompt is ${prompt.length} characters; Copilot allows at most 30,000.`);
      }
      const stray = prompt.match(/^(name|description|tools|model):\s/m);
      if (stray) errors.push(`"${stray[1]}:" is below the frontmatter: move it inside the --- block or remove it.`);
    }
  }

  if (!prompt.trim() && !errors.length) {
    errors.push('The agent has no prompt: write its role, steps and report format.');
  }
  if (canEdit && READ_ONLY_ROLE.test(`${name} ${description}`)) {
    warnings.push({
      claudeCode: 'A reviewing or research agent that can edit files: list its tools without Edit and Write.',
      cursor: 'A reviewing or research agent that can edit files: add readonly: true.',
      codex: 'A reviewing or research agent that can edit files: add "Do not edit files." to developer_instructions.',
      copilot: 'A reviewing or research agent that can edit files: list its tools, such as ["read", "search"].',
    }[target]);
  }
  const placeholders = (source.match(PLACEHOLDER) ?? []).length;
  if (placeholders) warnings.push(`${placeholders} «INSERT HERE» placeholder${placeholders === 1 ? '' : 's'} to fill in.`);
  return { valid: errors.length === 0, errors, warnings, name, placeholders };
}
