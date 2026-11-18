import { attachedInput, composeFiles, embedFilesInResult, MAX_FILES, MAX_FILES_INPUT } from '../pipeline/context.ts';
import type { ProjectFile } from '../pipeline/context.ts';
import { sanitizeBrief } from '../pipeline/injection.ts';
import { resolveExecutionCapabilities } from '../pipeline/prompt-defaults.ts';
import { generateZeroShotPrompt } from '../pipeline/zero-shot.ts';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadCatalog } from '../pipeline/catalog.ts';
import { runPipeline } from '../pipeline/index.ts';
import { promptVersion } from '../pipeline/prompt-version.ts';
import { parseTarget, TARGET_LABELS } from '../pipeline/target.ts';
import { extractJson } from '../pipeline/json.ts';
import { createLLM, meterLLM } from '../pipeline/llm.ts';
import { generateManualPrompt } from '../pipeline/manual.ts';
import { generateBrief, parseBrief } from '../pipeline/brief.ts';
import { settleWithLimit } from '../pipeline/limit.ts';
import { generateSkill } from '../pipeline/skill.ts';
import { generateClarify, parseClarify } from '../pipeline/clarify.ts';
import type { ClarifyKind } from '../pipeline/clarify.ts';
import type { SkillSurface } from '../pipeline/skill-rules.ts';
import { generateInstructions } from '../pipeline/instructions.ts';
import { INSTRUCTION_TARGETS } from '../pipeline/instructions-rules.ts';
import type { InstructionTarget } from '../pipeline/instructions-rules.ts';
import { generateAgent } from '../pipeline/agent.ts';
import { AGENT_TARGETS } from '../pipeline/agent-rules.ts';
import type { AgentTarget } from '../pipeline/agent-rules.ts';
import type { Provider } from '../pipeline/llm.ts';
import techniqueSources from '../catalog/source-links.json' with { type: 'json' };

/** Bridge for the desktop UI: JSON on stdin → JSON on stdout. No arguments, so there is no quoting to get wrong. */

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

/** "Select all" can send the whole catalog; at most this many generations run at once. */
const MAX_MANUAL_TECHNIQUES = 100;
const MANUAL_CONCURRENCY = 4;

interface BridgeRequest {
  thoughts: string;
  brief?: unknown;
  /** Skill, Project, Subagent: the edited questions and assumptions (Rebuild); no new clarify call then. */
  clarify?: unknown;
  reportProgress?: boolean;
  oneShot?: boolean;
  executionProfile?: string;
  agentCapabilities?: string[];
  provider?: Provider;
  model?: string;
  apiKey?: string;
  baseUrl?: string;
  deterministic?: boolean;
  /** The model the prompt is written for: "claude" … "hermes" or "open:<model id>"; absent — any LLM. */
  target?: string;
  budgetCalls?: number | null;
  /** The technique list for the UI dropdown. */
  listTechniques?: boolean;
  /** Force a prompt built with one specific technique's method. */
  manualTechnique?: string;
  /** Several techniques at once: one prompt per technique, in parallel. */
  manualTechniques?: string[];
  /** How many technique variants to offer (1–5). */
  variants?: number;
  /** Write a SKILL.md instead of a prompt, for this surface. */
  skill?: SkillSurface;
  /** Write a project-instruction file (AGENTS.md, CLAUDE.md, Cursor rule, Copilot) instead of a prompt. */
  instructions?: InstructionTarget;
  /** Write a subagent definition (Claude Code, Cursor, Codex, Copilot) instead of a prompt. */
  agent?: AgentTarget;
  /** Project files read by the UI, used as reference next to the request in every mode. */
  files?: unknown;
}

/** At most this much text per attached file reaches the bridge; the pipeline keeps less. */
const MAX_FILE_INPUT = 1_000_000;

function parseFiles(value: unknown): ProjectFile[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > MAX_FILES) throw new Error(`files must list at most ${MAX_FILES} files.`);
  const files = value.map((file) => {
    const { path, content } = (file ?? {}) as { path?: unknown; content?: unknown };
    if (typeof path !== 'string' || !path.trim() || typeof content !== 'string' || content.length > MAX_FILE_INPUT) {
      throw new Error('Each file needs a path and text content under 1 MB.');
    }
    return { path: path.trim(), content };
  });
  if (files.reduce((sum, file) => sum + file.content.length, 0) > MAX_FILES_INPUT) {
    throw new Error(`The attached files hold more than ${MAX_FILES_INPUT / 1_000_000} MB of text together.`);
  }
  return files;
}

/** A title when no brief was made: a missing title must not discard completed prompts. */
async function topicFor(thoughts: string, llm: ReturnType<typeof createLLM>): Promise<string | undefined> {
  try {
    const raw = await llm(`Name the task below with a natural concise 2–6 word topic in the user's language. Do not clip a sentence. Return JSON {"topic":"..."}. Task data: ${JSON.stringify(thoughts)}`, { temperature: 0, json: true });
    const data = extractJson(raw, 'topic') as { topic?: unknown };
    if (typeof data?.topic === 'string' && data.topic.trim().length <= 80) return data.topic.trim();
  } catch { /* no title */ }
  return undefined;
}

async function main() {
  const raw = readFileSync(0, 'utf8');
  const req = JSON.parse(raw) as BridgeRequest;

  if (!req.thoughts || !req.thoughts.trim()) {
    throw new Error('Enter your thoughts');
  }
  // The request alone is checked above: files come next to it, never instead of it.
  const files = parseFiles(req.files);
  // A prompt works on the files (a report to check): they are its material and are appended to it in full.
  // Skill, Project and Subagent read them as project reference.
  const promptMode = req.skill === undefined && req.instructions === undefined && req.agent === undefined;
  const { thoughts, uses } = composeFiles(req.thoughts, files, promptMode ? 'material' : 'reference');
  const withFiles = <T,>(result: T): T => embedFilesInResult(result, files);
  // Every answer says how each attached file reached the model (whole, outline, only in the tree): the rows show it.
  const filesUsed = files.length ? Object.fromEntries(files.map((file, i) => [file.path, uses[i] ?? 'tree'])) : undefined;
  const reply = (payload: Record<string, unknown>) => process.stdout.write(JSON.stringify(filesUsed ? { ...payload, filesUsed } : payload));

  const target = parseTarget(req.target);
  const provider = req.provider ?? 'ollama';
  const model = req.model ?? '';
  if (!model) throw new Error('Choose a model');
  let baseUrl: string | undefined;
  if (req.baseUrl) {
    const url = URL.parse(req.baseUrl.trim());
    if (!url || !['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
      throw new Error('Enter an HTTP or HTTPS model base URL without credentials, query parameters or a fragment.');
    }
    baseUrl = url.href.replace(/\/+$/, '');
  }

  const onProgress = req.reportProgress === true
    ? (percent: number, stage: string) => process.stderr.write(`PROMPTA_PROGRESS ${JSON.stringify({ percent, stage })}\n`)
    : undefined;
  const executionCapabilities = resolveExecutionCapabilities(req.executionProfile, req.agentCapabilities);
  const revisedBrief = req.brief === undefined ? undefined : parseBrief(JSON.stringify(req.brief));
  const oneShot = req.oneShot === true;  // opt-in: an invented example at the top buries the real task
  const meter = meterLLM(createLLM({ provider, model, apiKey: req.apiKey, baseUrl }));
  const { llm, usage } = meter;
  const getManualBrief = async () => {
    const brief = revisedBrief ?? await generateBrief(thoughts, llm);
    const clean = brief && sanitizeBrief(brief, thoughts).brief;
    return clean && files.length ? { ...clean, input: attachedInput(files, clean.language) } : clean;
  };

  // What the request leaves open: asked once, then the window's edited answers come back on Rebuild.
  const getClarify = async (kind: ClarifyKind) => {
    if (req.clarify !== undefined) return parseClarify(req.clarify);
    onProgress?.(5, 'Checking what the request leaves open');
    const asked = await generateClarify(kind, thoughts, llm);
    if (!asked) return undefined;
    // As in a prompt's brief: a question or assumption carried over from a command in attached text is dropped.
    const { brief } = sanitizeBrief({ constraints: [], ...asked } as unknown as Parameters<typeof sanitizeBrief>[0], thoughts);
    return { questions: brief.questions ?? [], assumptions: brief.assumptions };
  };

  if ([req.skill, req.instructions, req.agent].filter((v) => v !== undefined).length > 1) {
    throw new Error('Choose one of a skill, project instructions or an agent.');
  }
  if (req.agent !== undefined) {
    if (!AGENT_TARGETS.includes(req.agent)) throw new Error(`agent must be one of ${AGENT_TARGETS.join(', ')}.`);
    if (target || req.manualTechnique || req.manualTechniques) throw new Error('An agent cannot be combined with a prompt target or technique.');
    const clarify = await getClarify('agent');
    onProgress?.(30, 'Writing the agent');
    const agent = await generateAgent({ thoughts, llm, target: req.agent, clarify });
    reply({ ok: true, agent: { ...agent, usage: usage() } });
    return;
  }
  if (req.skill !== undefined) {
    if (!['portable', 'claudeCode'].includes(req.skill)) throw new Error('skill must be "portable" or "claudeCode".');
    if (target || req.manualTechnique || req.manualTechniques) throw new Error('A skill cannot be combined with a prompt target or technique.');
    const clarify = await getClarify('skill');
    onProgress?.(30, 'Writing SKILL.md');
    const skill = await generateSkill({ thoughts, llm, surface: req.skill, clarify });
    reply({ ok: true, skill: { ...skill, usage: usage() } });
    return;
  }

  if (req.instructions !== undefined) {
    if (!INSTRUCTION_TARGETS.includes(req.instructions)) throw new Error(`instructions must be one of ${INSTRUCTION_TARGETS.join(', ')}.`);
    if (target || req.manualTechnique || req.manualTechniques) throw new Error('Project instructions cannot be combined with a prompt target or technique.');
    const clarify = await getClarify('instructions');
    onProgress?.(30, 'Writing project instructions');
    const instructions = await generateInstructions({ thoughts, llm, target: req.instructions, clarify });
    reply({ ok: true, instructions: { ...instructions, usage: usage() } });
    return;
  }

  const catalog = target && !req.listTechniques ? { version: 'official-only', techniques: [] } : loadCatalog(JSON.parse(readFileSync(join(root, 'catalog', 'catalog.json'), 'utf8')));

  if (req.listTechniques) {
    const ready = catalog.techniques
      .filter(
        (t) =>
          ['ready', 'procedure'].includes(t.status) &&
          ['technique', 'prompt_type', 'procedure'].includes(t.kind),
      )
      .map((t) => ({
        key: t.key,
        name: t.name,
        category: t.category,
        status: t.status,
        sources: (techniqueSources as Record<string, { title: string; url: string; reference: string }[]>)[t.key] ?? [],
        // A one-sentence hint: the first sentence of when_to_use, without the rest.
        hint: t.when_to_use.split(/[.;]/)[0].trim().slice(0, 90),
      }));
    process.stdout.write(JSON.stringify({ ok: true, techniques: ready, promptVersion: promptVersion() }));
    return;
  }

  if (target && req.manualTechniques) {
    throw new Error('Official-guidance targets cannot use generic manual techniques.');
  }

  if (req.manualTechniques !== undefined) {
    const keys = req.manualTechniques;
    if (!Array.isArray(keys) || keys.length < 2 || keys.length > MAX_MANUAL_TECHNIQUES || !keys.every((k) => typeof k === 'string' && k)
        || new Set(keys).size !== keys.length || req.manualTechnique) {
      throw new Error(`manualTechniques must list 2–${MAX_MANUAL_TECHNIQUES} distinct technique keys.`);
    }
    if (req.deterministic) throw new Error('Manual technique selection requires LLM synthesis. Disable Skip LLM synthesis.');
    const techniques = keys.map((key) => {
      const technique = catalog.techniques.find((t) => t.key === key);
      if (!technique) throw new Error(`Unknown technique: ${key}`);
      if (technique.status === 'procedure') throw new Error(`${technique.name} is a procedure and cannot be combined with other techniques.`);
      if (!technique.template) throw new Error(`${technique.key}: No synthesis template`);
      return technique;
    });
    onProgress?.(5, 'Techniques loaded');
    // The same brief as automatic choice: format, constraints, assumptions and questions for every prompt.
    const brief = await getManualBrief();
    onProgress?.(15, 'Brief ready');
    const zeroShot = generateZeroShotPrompt(thoughts, brief, llm, executionCapabilities);  // Variant 0, by the model too
    let finished = 0;
    const settled = await settleWithLimit(techniques, MANUAL_CONCURRENCY, async (technique) => {
      try {
        return await generateManualPrompt(thoughts, technique, llm, oneShot, brief, executionCapabilities);
      } finally {
        finished += 1;
        onProgress?.(15 + Math.round(75 * finished / techniques.length), `Prompts ready: ${finished}/${techniques.length}`);
      }
    });
    const meta = (t: (typeof techniques)[number]) => ({ key: t.key, name: t.name, category: t.category });
    const variants = techniques.flatMap((t, i) => {
      const r = settled[i];
      return r.status === 'fulfilled' ? [{ technique: meta(t), prompt: r.value, config: t.config, source_ref: t.source_ref, why: t.when_to_use }] : [];
    });
    const failed = techniques.flatMap((t, i) => {
      const r = settled[i];
      return r.status === 'rejected' ? [{ key: t.key, name: t.name, error: r.reason instanceof Error ? r.reason.message : String(r.reason) }] : [];
    });
    if (!variants.length) throw new Error(`No technique produced a prompt: ${failed.map((f) => `${f.name}: ${f.error}`).join('; ')}`);
    const topic = brief?.topic ?? await topicFor(req.thoughts, llm);
    onProgress?.(95, 'Topic ready');
    const first = variants[0];
    reply({ ok: true, manual: withFiles({
      zeroShotPrompt: (await zeroShot).prompt, topic, brief, usage: usage(), promptVersion: promptVersion(),
      // First variant at the top level keeps older readers (and saved history) working.
      technique: first.technique, prompt: first.prompt, config: first.config, source_ref: first.source_ref,
      variants, failed,
    }) });
    return;
  }

  if (target && req.manualTechnique) {
    throw new Error(`${TARGET_LABELS[target.kind]} mode cannot use a generic manual technique.`);
  }

  if (req.manualTechnique) {
    onProgress?.(10, 'Technique loaded');
    const technique = catalog.techniques.find((t) => t.key === req.manualTechnique);
    if (!technique) throw new Error(`Unknown technique: ${req.manualTechnique}`);

    if (technique.status === 'procedure') {
      const brief = await getManualBrief();
      reply({
          ok: true,
          procedure: withFiles({
            zeroShotPrompt: (await generateZeroShotPrompt(thoughts, brief, llm, executionCapabilities)).prompt,
            technique: { key: technique.key, name: technique.name, category: technique.category },
            steps: technique.procedure ?? [],
            when_to_use: technique.when_to_use,
            source_ref: technique.source_ref,
            topic: technique.name,
            usage: usage(),
            promptVersion: promptVersion(),
          }),
        });
      return;
    }

    if (!technique.template) throw new Error(`${technique.key}: No synthesis template`);

    if (req.deterministic) throw new Error('Manual technique selection requires LLM synthesis. Disable Skip LLM synthesis.');
    const brief = await getManualBrief();
    onProgress?.(30, 'Brief ready');
    const [prompt, zeroShot] = await Promise.all([generateManualPrompt(thoughts, technique, llm, oneShot, brief, executionCapabilities),
      generateZeroShotPrompt(thoughts, brief, llm, executionCapabilities)]);
    onProgress?.(85, 'Prompt ready');
    const topic = brief?.topic ?? await topicFor(req.thoughts, llm);
    onProgress?.(95, 'Topic ready');

    reply({
        ok: true,
        manual: withFiles({
          zeroShotPrompt: zeroShot.prompt,
          topic,
          brief,
          usage: usage(),
          promptVersion: promptVersion(),
          technique: { key: technique.key, name: technique.name, category: technique.category },
          prompt,
          config: technique.config,
          source_ref: technique.source_ref,
          why: technique.when_to_use,
        }),
      });
    return;
  }

  const result = await runPipeline({
    onProgress,
    oneShot,
    executionCapabilities,
    brief: revisedBrief,
    thoughts,
    target,
    catalog,
    llm,
    mode: req.deterministic ? 'deterministic' : 'llm',
    budgetCalls: req.budgetCalls ?? null,
    variants: req.variants ?? 3,
    attachedFiles: files,
  });

  reply({ ok: true, result: withFiles(result) });
}

main().catch((e) => {
  process.stdout.write(JSON.stringify({ ok: false, error: e instanceof Error ? e.message : String(e) }));
  process.exitCode = 1;
});
