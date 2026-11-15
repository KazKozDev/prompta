import type { InstructionTarget } from './instructions-rules.ts';
import { readFrontmatter } from './skill-validate.ts';

/** Deterministic checks of a project-instruction file, from the limits and formats in
 *  instructions_rules/ (see INSTRUCTIONS-guide.md). Contradictions are left to the model. */

export const CURSOR_KEYS = ['description', 'globs', 'alwaysApply'] as const;
/** Size guidance per target: CLAUDE.md under 200 lines, a Cursor rule under 500, Copilot well under ~1,000;
 *  Codex reads at most 32 KiB of AGENTS.md files combined. */
const MAX_LINES: Partial<Record<InstructionTarget, number>> = { claudeMd: 200, cursor: 500, copilot: 1000 };
const AGENTS_MAX_BYTES = 32 * 1024;
const SHOUTING = /\b(IMPORTANT|CRITICAL|MUST|NEVER|ALWAYS)\b/;
const PLACEHOLDER = /«INSERT HERE[^»]*»/g;

export interface InstructionCheck {
  valid: boolean;
  errors: string[];
  warnings: string[];
  lines: number;
  bytes: number;
  placeholders: number;
}

export function validateInstructions(text: string, target: InstructionTarget): InstructionCheck {
  const errors: string[] = [];
  const warnings: string[] = [];
  const source = text.trimStart();
  const parsed = readFrontmatter(source);
  let body = source;

  if (target === 'cursor') {
    if (!parsed) {
      errors.push('A Cursor rule needs YAML frontmatter (alwaysApply, globs, description): a rule without it is ignored.');
    } else {
      body = parsed.body;
      const keys = [...parsed.fields.keys()];
      const unknown = keys.filter((k) => !(CURSOR_KEYS as readonly string[]).includes(k));
      if (unknown.length) errors.push(`Unknown Cursor rule keys: ${unknown.join(', ')}. Allowed: ${CURSOR_KEYS.join(', ')}.`);
      const always = parsed.fields.get('alwaysApply');
      if (always !== undefined && !['true', 'false'].includes(always)) errors.push('alwaysApply must be true or false.');
      if (always !== 'true' && !parsed.fields.get('globs') && !parsed.fields.get('description')) {
        warnings.push('With no alwaysApply: true, globs or description, Cursor loads this rule only when you @-mention it.');
      }
      const stray = body.match(/^(alwaysApply|globs|description):/m);
      if (stray) errors.push(`"${stray[1]}:" is below the frontmatter: move it inside the --- block or remove it.`);
    }
  } else if (parsed) {
    const file = target === 'copilot' ? 'copilot-instructions.md' : target === 'claudeMd' ? 'CLAUDE.md' : 'AGENTS.md';
    errors.push(`${file} is plain Markdown: remove the frontmatter block.`);
  }

  const lines = body.trim() ? body.trim().split(/\r?\n/).length : 0;
  const bytes = new TextEncoder().encode(text).length;
  if (!lines) errors.push('The file has no instructions.');
  const maxLines = MAX_LINES[target];
  if (maxLines && lines > maxLines) warnings.push(`${lines} lines: keep this file under ${maxLines} lines.`);
  if (target === 'agentsMd' && bytes > AGENTS_MAX_BYTES) warnings.push(`${bytes} bytes: Codex reads at most 32 KiB of AGENTS.md files.`);
  if (lines && !/^#{1,6}\s/m.test(body)) warnings.push('No headings: group the instructions under Markdown headings.');
  if (lines && !/`[^`\n]+`/.test(body)) warnings.push('No command or path in backticks: name the exact build and test commands.');
  if (SHOUTING.test(body.replace(/`[^`\n]*`/g, ''))) {
    warnings.push('Capitalised emphasis (IMPORTANT, MUST, NEVER…): it does not make a rule stick; a rule without exceptions belongs in a hook or CI.');
  }
  const placeholders = (body.match(PLACEHOLDER) ?? []).length;
  if (placeholders) warnings.push(`${placeholders} «INSERT HERE» placeholder${placeholders === 1 ? '' : 's'} to fill in.`);
  return { valid: errors.length === 0, errors, warnings, lines, bytes, placeholders };
}
