import { HERMES_PROFILE } from './hermes.ts';
import { BRIEF_SCHEMA, buildBriefPrompt } from './brief.ts';
import { sanitizeBrief } from './injection.ts';
import { buildManualPrompt } from './manual.ts';
import { runOfficialPipeline } from './official.ts';
import { CAPABILITY_TEXT, FRESHNESS_CRITERION, FRESHNESS_INSTRUCTIONS, ONE_SHOT_INSTRUCTION, QUALITY_CRITERIA, QUALITY_INSTRUCTIONS, applyPromptDefaults, executionContext, OFFICIAL_REQUIREMENTS, promptDefaultsText, promptRequirements } from './prompt-defaults.ts';
import { buildSelectionPrompt } from './select.ts';
import { buildSynthesisPrompt, INJECTION_GUARDS } from './synthesize.ts';
import { buildZeroShotPrompt, generateZeroShotPrompt } from './zero-shot.ts';

/** A manual label for the prompt set: change it on a deliberate rework so reports stay readable for people. */
export const PROMPT_SET = '2026-11-14';

/** FNV-1a 32 bit: no dependencies. */
export function fnv1a(text: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, '0');
}

/** Everything that shapes the text of the pipeline's internal prompts. Added a new prompt? Add it here. */
const PROMPT_SOURCES: readonly unknown[] = [
  JSON.stringify(HERMES_PROFILE), JSON.stringify(CAPABILITY_TEXT), executionContext, FRESHNESS_CRITERION, JSON.stringify(FRESHNESS_INSTRUCTIONS), QUALITY_CRITERIA, JSON.stringify(QUALITY_INSTRUCTIONS), applyPromptDefaults, promptDefaultsText, promptRequirements, OFFICIAL_REQUIREMENTS,
  buildBriefPrompt, BRIEF_SCHEMA, buildSelectionPrompt, buildSynthesisPrompt, JSON.stringify(INJECTION_GUARDS),
  buildZeroShotPrompt, generateZeroShotPrompt, buildManualPrompt, ONE_SHOT_INSTRUCTION, runOfficialPipeline, sanitizeBrief,
];

let cached: string | undefined;

/** The prompt fingerprint: `<label>+<source hash>`. The hash changes by itself on any edit of a prompt's text,
 *  so an eval score can never be attributed to another version by mistake. */
export function promptVersion(): string {
  cached ??= `${PROMPT_SET}+${fnv1a(PROMPT_SOURCES.map((s) => String(s)).join('␞'))}`;
  return cached;
}
