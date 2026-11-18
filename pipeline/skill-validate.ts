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
  /** Lines of SKILL-template.md left unfilled in the draft: not a format error, but the file is not finished. */
  leftovers: string[];
  /** Sections used for the wrong thing (the spec under Additional resources, a project file under Scripts). */
  structure: string[];
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
    return { valid: false, errors: ['No YAML frontmatter: SKILL.md must start with a "---" block.'], warnings, name: '', description: '', keys: [], bodyLines: 0, leftovers: [], structure: [] };
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

  errors.push(...fenceErrors(body));

  const bodyLines = body.trim() ? body.trim().split(/\r?\n/).length : 0;
  if (!bodyLines) errors.push('The body after the frontmatter is empty.');
  if (bodyLines > BODY_LINES) warnings.push(`The body is ${bodyLines} lines; keep it under ${BODY_LINES} and move detail into referenced files.`);

  const leftovers = skeletonLeftovers(body);
  if (leftovers.length) warnings.push(`Unfilled template lines: ${leftovers.map((l) => `"${l}"`).join(', ')}.`);
  const structure = [...structureProblems(body), ...meaningProblems(description, body)];
  warnings.push(...structure);
  const placeholders = (body.match(PLACEHOLDER) ?? []).length;
  if (placeholders) warnings.push(`${placeholders} «INSERT HERE» placeholder${placeholders === 1 ? '' : 's'} to fill in.`);

  return { valid: errors.length === 0, errors, warnings, name, description, keys, bodyLines, leftovers, structure };
}

/** Above this many MUST lines the emphasis stops meaning anything (a real draft had 60 of 75 lines). */
const MUST_LINES = 8;

/** The body's ## sections: heading and text, in order. */
function sections(body: string): { heading: string; text: string }[] {
  return body.split(/^## /m).slice(1).map((part) => {
    const end = part.indexOf('\n');
    return { heading: (end < 0 ? part : part.slice(0, end)).trim(), text: end < 0 ? '' : part.slice(end + 1).trim() };
  });
}

/** Template sections filled with the wrong thing: both send the agent looking in the wrong place.
 *  Additional resources only links reference files shipped with the skill; the skill's own instructions there
 *  read as optional. Scripts only lists scripts/ shipped with the skill; a file the skill writes in the user's
 *  project is a workflow step, and listing it here makes the agent look for a file that does not exist. */
export function structureProblems(body: string): string[] {
  const problems: string[] = [];
  const musts = body.split(/\r?\n/).filter((line) => /\bMUST\b/.test(line)).length;
  if (musts > MUST_LINES) {
    problems.push(`MUST is on ${musts} lines. Keep MUST and Never for the few rules whose breach ruins the result or does harm, at most ${MUST_LINES}; write the rest as plain imperatives ("Use 15 fps.").`);
  }
  for (const { heading, text } of sections(body)) {
    if (/^additional resources$/i.test(heading) && text && !/\]\([^)]+\)|\b(?:references?|assets)\//.test(text)) {
      problems.push('"## Additional resources" holds the skill\'s own instructions; it is only for links to reference files shipped with the skill. Give each topic its own ## section after Workflow, or drop the section.');
    }
    if (/^scripts$/i.test(heading)) {
      const listed = [...text.matchAll(/^\s*[-*]\s+\**`?([\w./-]+\.\w+)/gm)].map((m) => m[1]);
      const foreign = listed.filter((path) => !/^scripts\//.test(path));
      if (foreign.length) {
        problems.push(`"## Scripts" lists ${foreign.join(', ')}, which is not shipped in the skill's scripts/ folder. A file the skill writes in the user's project is a Workflow step ("Write ${foreign[0]} that ..."); drop it from Scripts, and drop the section if nothing is left.`);
      }
    }
  }
  return problems;
}

/** Sections the skeleton defines; a short one of these is fine. */
const SKELETON_SECTIONS = /^(quick start|workflow|rules|output format|scripts|additional resources)$/i;
/** Stand-ins for a value the skill needs: the agent reading the skill cannot act on them. */
const VAGUE = [
  /\b(?:based on|from|by|according to|depending on) (?:the )?(?:project(?:'s)? )?context\b/i,
  /\bstandard (?:build|way|method|command|procedure|settings|location|tool)s?\b/i,
  /\b(?:as usual|the usual way|the usual command)\b/i,
  /\b(?:appropriate|relevant|proper|suitable) (?:command|tool|script|setting|path|flag)s?\b/i,
];
/** A step that cannot be undone, and the words that show it is guarded (a check, a confirmation, a plan, an order). */
const IRREVERSIBLE = /\brm -rf\b|\b(?:delete|overwrite|drop table|force[- ]push|git push|publish|deploy|release to|move (?:the )?\S+ (?:copy )?to (?:the )?trash)\b/i;
/** How far up, within the same section, a guard for an irreversible line may sit. */
const GUARD_LINES = 8;
const GUARDED = /\b(?:only after|after [^.]*(?:succeed|pass)|once [^.]*(?:succeed|pass)|confirm|ask|approval|verify|check|backup|back up|plan|dry[- ]run|roll ?back|if [^.]*(?:fail|succeed|pass))/i;

/** Letters outside the Latin script, outside code and quotes: the file is written in English, and a quoted trigger
 *  phrase or a code sample may keep its own language. */
function foreignText(text: string): string[] {
  const plain = text
    .replace(/^ {0,3}(`{3,})[\s\S]*?^ {0,3}\1/gm, '')
    .replace(/`[^`\n]*`/g, '')
    .replace(/"[^"\n]*"|«[^»\n]*»|“[^”\n]*”|\([^()\n]*\)/g, '');
  return [...new Set(plain.match(/[^\s\p{Script=Latin}\p{N}\p{P}\p{S}\p{M}]+(?:\s+[^\s\p{Script=Latin}\p{N}\p{P}\p{S}\p{M}]+)*/gu) ?? [])];
}

/** What the structure checks cannot see: mixed languages, sections that only repeat a step, vague stand-ins for
 *  values, and an irreversible step with nothing guarding it. Each problem sends the draft to the repair pass. */
export function meaningProblems(description: string, body: string): string[] {
  const problems: string[] = [];
  const foreign = [...foreignText(description), ...foreignText(body)];
  if (foreign.length) {
    problems.push(`Not in English: ${foreign.slice(0, 3).map((f) => `"${f}"`).join(', ')}. Write the whole file in English; only a trigger phrase quoted in the description keeps the user's language.`);
  }
  for (const { heading, text } of sections(body)) {
    if (SKELETON_SECTIONS.test(heading)) continue;
    const lines = text.split(/\r?\n/).filter((line) => line.trim());
    if (lines.length === 1) {
      problems.push(`"## ${heading}" holds one line. Fold it into its Workflow step, or give the section what the step does not say (settings, numbers, conditions).`);
    }
  }
  const lines = body.split(/\r?\n/);
  const vague = new Set<string>();
  for (const line of lines) {
    for (const re of VAGUE) {
      const hit = line.match(re);
      if (hit) vague.add(hit[0]);
    }
  }
  if (vague.size) {
    problems.push(`Vague stand-in for a value: ${[...vague].map((v) => `"${v}"`).join(', ')}. Name the value (a command, a path, a number) or where the skill reads it (README, build_*.sh, package.json); if neither is known, write «INSERT HERE: <what>».`);
  }
  let heading = '';
  let since = 0; // the guard may sit a few lines up: a step's prose, or a check at the top of its code block
  lines.forEach((line, i) => {
    if (/^#{2,4} /.test(line)) {
      heading = line;
      since = i;
    }
    if (!IRREVERSIBLE.test(line) || /\b(?:never|do not|don't|must not|not)\b/i.test(line)) return;
    const before = [heading, ...lines.slice(Math.max(since, i - GUARD_LINES), i + 1)].join(' ');
    if (!GUARDED.test(before)) {
      problems.push(`"${line.trim()}" cannot be undone and nothing guards it. Say what must have succeeded first or what is checked or confirmed before it.`);
    }
  });
  return problems;
}

const PLACEHOLDER = /«INSERT HERE[^»]*»/g;

/** The placeholder lines of skill_rules/SKILL-template.md. Matched one by one, not as any <...>: an output
 *  template in a skill legitimately holds slots like <alt text> or <model, version>. */
const SKELETON = [
  /For <case>, use <alternative> instead/,
  /Does X with Y/,
  /^#\s+Skill Name\s*$/,
  /^- \[ \] Step \d+: \.\.\.\s*$/,
  /^- (?:MUST|Never) \.\.\.\s*$/,
  /^One default approach for the most common case/,
  /INSERT HERE[^»\n]*«\s*INSERT HERE/,
];

/** Template lines the draft kept instead of filling in or dropping. */
export function skeletonLeftovers(body: string): string[] {
  return body.split(/\r?\n/).map((line) => line.trim()).filter((line) => SKELETON.some((re) => re.test(line)));
}

/** Code blocks that break: one left open, or one that opens inside a block fenced with as many backticks
 *  (Markdown ends the outer block at the inner one's closing fence, so a template splits in two). */
export function fenceErrors(body: string): string[] {
  const errors: string[] = [];
  let open: { char: string; len: number; line: string } | null = null;
  for (const line of body.split(/\r?\n/)) {
    const fence = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    if (!fence) continue;
    const [, marks, rest] = fence;
    if (!open) {
      open = { char: marks[0], len: marks.length, line: line.trim() };
    } else if (marks[0] === open.char && marks.length >= open.len) {
      if (rest.trim()) {
        errors.push(`"${line.trim()}" opens a code block inside the one opened by "${open.line}": fence the outer block with more backticks (\`\`\`\`).`);
      }
      open = null;
    }
  }
  if (open) errors.push(`The code block opened by "${open.line}" is never closed.`);
  return errors;
}
