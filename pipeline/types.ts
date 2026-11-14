import type { OfficialGuidance } from './official.ts';
/** Contracts of the "stream of thoughts → prompt" pipeline.
 *
 *  Every pipeline module is a pure function: the LLM is passed in as a dependency,
 *  so the logic is tested without network and without UI.
 */

export type Kind = 'technique' | 'setting' | 'prompt_type' | 'risk' | 'procedure';
export type Status = 'ready' | 'procedure' | 'index-only';
export type Execution =
  | 'single_call'
  | 'multi_step'
  | 'n_calls_vote'
  | 'tool_loop'
  | 'optimizer_loop'
  | 'postprocess'
  | 'none';
export type Modality = 'text' | 'image' | 'audio' | 'video';
export type Stakes = 'low' | 'medium' | 'high';

export interface TechniqueConfig {
  temperature: number | null;
  top_p: number | null;
  max_tokens_hint?: string;
  rationale: string;
}

export interface Technique {
  key: string;
  name: string;
  kind: Kind;
  category: string;
  /** Which task types the technique suits. Empty — no restriction. */
  task_types?: string[];
  execution: Execution;
  when_to_use: string;
  when_not: string | null;
  cost_calls: number | string;
  config: TechniqueConfig;
  template: string | null;
  /** Execution steps for procedural techniques (KNN, RL optimisers, ensembles). */
  procedure?: string[] | null;
  example: string;
  source_ref: string;
  source_docs: string[];
  related: string[];
  status: Status;
}

export interface Catalog {
  version: string;
  techniques: Technique[];
}

/** A question to the user and what is assumed while it stays unanswered. */
export interface BriefQuestion {
  question: string;
  /** The assumption used until the user answers; not repeated in `assumptions`. */
  default?: string;
}

/** The analysis of the input stream of thoughts. Everything the model inferred goes into `assumptions`. */
export const CAPABILITIES = ['web', 'files', 'code', 'integrations'] as const;
export type Capability = typeof CAPABILITIES[number];
export type ExecutionCapabilities = Partial<Record<Capability, 'available' | 'unavailable' | 'unknown'>>;

export interface TaskBrief {
  /** Short model-written topic for the result and history. */
  topic?: string;
  verify_current_facts?: boolean;
  require_evidence?: boolean;
  requires_tools?: boolean;
  required_capabilities?: Capability[];
  validate_output?: boolean;
  goal: string;
  task_type: string;
  input: string;
  output_format: string;
  /** Who reads the answer, only as the user stated it; a guess goes to assumptions, where the user can correct it. */
  audience?: string;
  /** The answer's tone, only as the user stated it; a guess goes to assumptions. */
  tone?: string;
  constraints: string[];
  language: string;
  modality: Modality;
  stakes: Stakes;
  assumptions: string[];
  /** Up to 3 questions whose answers would change the result materially; empty when nothing important is missing. */
  questions?: BriefQuestion[];
  /** How many LLM calls the user is willing to spend. null — unlimited. */
  budget_calls: number | null;
}

export interface TechniqueChoice {
  key: string;
  name: string;
  reason: string;
  confidence: number;
  /** Why not a cheaper technique: the mandatory answer to the key question. */
  whyNotCheaper: string;
  /** The model picked a non-cheapest technique without explaining: the choice is accepted but flagged. */
  cheapestOverride?: boolean;
}

export interface PromptConfig {
  temperature: number | null;
  top_p: number | null;
  max_tokens: string;
  rationale: string;
}

export interface Synthesis {
  techniqueKey: string;
  prompt: string;
  config: PromptConfig;
  /** Placeholders there was nothing to fill with. Empty = the prompt is ready. */
  missing: string[];
  warnings: string[];
}

export interface PipelineTrace {
  step: string;
  ms: number;
  prompt?: string;
  raw?: string;
}

export interface PipelineResult {
  /** Additional standalone baseline, preceding all selected variants. */
  zeroShotPrompt?: string;
  claudeGuidance?: OfficialGuidance;
  chatgptGuidance?: OfficialGuidance;
  geminiGuidance?: OfficialGuidance;
  grokGuidance?: OfficialGuidance;
  hermesGuidance?: OfficialGuidance;
  openModelGuidance?: OfficialGuidance;
  brief: TaskBrief;
  choice: TechniqueChoice;
  synthesis: Synthesis;
  /** Additional technique variants with their prompts (if more than one was requested). */
  alternatives?: { choice: TechniqueChoice; synthesis: Synthesis }[];
  /** Techniques that dropped out before selection, and why. */
  rejected: { key: string; reason: string }[];
  trace: PipelineTrace[];
  /** Usage for the whole run: all stages and parse retries. Zeros — the provider did not report usage. */
  usage?: TokenUsage & { calls: number };
  /** The fingerprint of the pipeline's internal prompts: ties the result and the eval score to a prompt version. */
  promptVersion?: string;
}

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
}

export interface LLMCallOptions {
  temperature?: number;
  json?: boolean;
  maxTokens?: number;
  /** The adapter reports token usage if the provider returned it. */
  onUsage?: (usage: TokenUsage) => void;
}

export type LLM = (prompt: string, opts?: LLMCallOptions) => Promise<string>;

export class PipelineError extends Error {
  readonly step: string;

  constructor(message: string, step: string) {
    super(`[${step}] ${message}`);
    this.name = 'PipelineError';
    this.step = step;
  }
}
